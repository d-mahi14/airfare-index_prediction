"""
scraper/framework/circuit_breaker.py
Per-source Circuit Breaker to prevent hammering blocked or rate-limited endpoints.

State Machine:
  - CLOSED: Normal operation. All requests are allowed.
  - OPEN: Source has failed/been blocked N consecutive times. All requests are rejected/paused.
  - HALF_OPEN: Cooldown period has elapsed. Allows a single probe request to test recovery.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Tripped / Paused
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    cooldown_seconds: float = 300.0  # 5 minutes


class CircuitBreaker:
    """
    Per-source circuit breaker managing health state and blocking transitions.
    """

    def __init__(
        self,
        source_name: str,
        config: Optional[CircuitBreakerConfig] = None,
        clock_fn=time.monotonic,
    ):
        self.source_name = source_name
        self.config = config or CircuitBreakerConfig()
        self.clock_fn = clock_fn

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._last_state_change: float = self.clock_fn()
        self._last_trip_reason: Optional[str] = None
        self._trip_count: int = 0

    @property
    def state(self) -> CircuitState:
        # Check if OPEN state has expired cooldown and should transition to HALF_OPEN
        if self._state == CircuitState.OPEN:
            elapsed = self.clock_fn() - self._last_state_change
            if elapsed >= self.config.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._last_state_change = self.clock_fn()
                logger.info(
                    f"CircuitBreaker [{self.source_name}]: Cooldown of {self.config.cooldown_seconds}s "
                    f"elapsed. Transitioning OPEN -> HALF_OPEN (probing recovery)."
                )
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def last_trip_reason(self) -> Optional[str]:
        return self._last_trip_reason

    @property
    def trip_count(self) -> int:
        return self._trip_count

    def allow_request(self) -> bool:
        """
        Check whether a request is permitted under current circuit state.
        """
        current_state = self.state
        if current_state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            return True
        logger.warning(
            f"CircuitBreaker [{self.source_name}]: Request rejected — circuit is OPEN. "
            f"Reason: {self._last_trip_reason}"
        )
        return False

    def record_success(self) -> None:
        """
        Record a successful request. Resets failure count and closes circuit if half-open.
        """
        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                f"CircuitBreaker [{self.source_name}]: Probe request succeeded. "
                f"Transitioning HALF_OPEN -> CLOSED."
            )
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_state_change = self.clock_fn()

    def record_block(self, reason: str, block_type: str = "block") -> None:
        """
        Record a blocked response, CAPTCHA challenge, or HTTP 429 error.
        If consecutive failures reach threshold, trips to OPEN state.
        """
        self._consecutive_failures += 1
        logger.warning(
            f"CircuitBreaker [{self.source_name}]: Block #{self._consecutive_failures} recorded "
            f"(type={block_type}, reason={reason})"
        )

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed — trip back to OPEN immediately
            self._state = CircuitState.OPEN
            self._last_state_change = self.clock_fn()
            self._last_trip_reason = f"Probe request failed in HALF_OPEN: {reason}"
            self._trip_count += 1
            logger.error(
                f"CircuitBreaker [{self.source_name}]: Probe request failed. "
                f"Re-tripping HALF_OPEN -> OPEN. Reason: {self._last_trip_reason}"
            )
        elif self._state == CircuitState.CLOSED and self._consecutive_failures >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
            self._last_state_change = self.clock_fn()
            self._last_trip_reason = (
                f"Threshold reached ({self._consecutive_failures} consecutive blocks): {reason}"
            )
            self._trip_count += 1
            logger.error(
                f"CircuitBreaker [{self.source_name}]: Tripped CLOSED -> OPEN! "
                f"Pausing collection for source. Reason: {self._last_trip_reason}"
            )

    def reset(self) -> None:
        """Reset the circuit breaker to clean CLOSED state."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_state_change = self.clock_fn()
        self._last_trip_reason = None
