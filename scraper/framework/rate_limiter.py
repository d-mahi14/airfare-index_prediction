"""
scraper/framework/rate_limiter.py
Per-source rate limiter with randomized jitter.

Enforces polite, compliant scraping behavior:
  - max_rps: requests per second limit (e.g. 0.5 rps = 1 request every 2.0s).
  - jitter_pct: random variation to avoid synchronized bursts (e.g. +/-20%).
"""
import asyncio
import logging
import random
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token-bucket / interval rate limiter with configurable jitter.
    Thread-safe and async-compatible.
    """

    def __init__(
        self,
        max_rps: float = 0.5,
        jitter_pct: float = 0.2,
        clock_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if max_rps <= 0:
            raise ValueError(f"max_rps must be strictly positive, got {max_rps}")
        if not (0.0 <= jitter_pct <= 1.0):
            raise ValueError(f"jitter_pct must be between 0.0 and 1.0, got {jitter_pct}")

        self.max_rps = float(max_rps)
        self.jitter_pct = float(jitter_pct)
        self.clock_fn = clock_fn
        self.sleep_fn = sleep_fn
        self._last_request_time: Optional[float] = None
        self._rng = random.Random()

    @property
    def base_interval(self) -> float:
        """Nominal interval between requests in seconds."""
        return 1.0 / self.max_rps

    def compute_delay(
        self,
        last_time: Optional[float] = None,
        current_time: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> float:
        """
        Compute required delay in seconds before the next request is allowed.
        """
        curr = current_time if current_time is not None else self.clock_fn()
        last = last_time if last_time is not None else self._last_request_time

        effective_rng = rng if rng is not None else self._rng
        # Apply jitter: uniform between base * (1 - jitter_pct) and base * (1 + jitter_pct)
        min_interval = self.base_interval * (1.0 - self.jitter_pct)
        max_interval = self.base_interval * (1.0 + self.jitter_pct)
        target_interval = effective_rng.uniform(min_interval, max_interval)

        if last is None:
            return 0.0

        elapsed = curr - last
        if elapsed < target_interval:
            return target_interval - elapsed
        return 0.0

    def acquire(self) -> float:
        """
        Synchronously block until rate limit allows the next request.
        Returns the duration slept in seconds.
        """
        now = self.clock_fn()
        delay = self.compute_delay(current_time=now)
        if delay > 0:
            logger.debug(f"Rate limiting: sleeping {delay:.3f}s (max_rps={self.max_rps})")
            self.sleep_fn(delay)
        self._last_request_time = self.clock_fn()
        return delay

    async def async_acquire(self) -> float:
        """
        Asynchronously await until rate limit allows the next request.
        Returns the duration slept in seconds.
        """
        now = self.clock_fn()
        delay = self.compute_delay(current_time=now)
        if delay > 0:
            logger.debug(f"Rate limiting (async): sleeping {delay:.3f}s (max_rps={self.max_rps})")
            await asyncio.sleep(delay)
        self._last_request_time = self.clock_fn()
        return delay

    def reset(self) -> None:
        """Reset the rate limiter state."""
        self._last_request_time = None
