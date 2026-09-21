"""
scraper/framework/retry.py
Exponential backoff retry policy for collectors.

Guiding principles:
  1. Transient network errors (timeouts, connection resets, 5xx server errors) are retried.
  2. Compliance violations (DisallowedError, Robots.txt rejections) are NEVER retried.
  3. Security blocks, CAPTCHAs, 403 Forbidden, and BlockedResult are NEVER retried.
"""
import functools
import logging
import random
import time
from typing import Any, Callable, Optional, Sequence, Tuple, Type

from scraper.base import BlockedResult, DisallowedError

logger = logging.getLogger(__name__)

# Non-retryable error types
NON_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    DisallowedError,
    KeyboardInterrupt,
    SystemExit,
)


def compute_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    rng: Optional[random.Random] = None,
) -> float:
    """
    Calculate exponential backoff delay for attempt index (0-indexed or 1-indexed).
    """
    effective_attempt = max(0, attempt)
    delay = base_delay * (backoff_factor ** effective_attempt)
    if jitter:
        effective_rng = rng or random
        delay = effective_rng.uniform(delay * 0.75, delay * 1.25)
    return min(delay, max_delay)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable_exceptions: Sequence[Type[Exception]] = (Exception,),
    sleep_fn: Callable[[float], None] = time.sleep,
):
    """
    Decorator for retrying a function on transient exceptions with exponential backoff.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries + 1):
                try:
                    result = fn(*args, **kwargs)
                    # If the function returns a BlockedResult, do NOT retry
                    if isinstance(result, BlockedResult):
                        logger.warning(f"{fn.__name__} returned BlockedResult ({result.block_type}): no retry attempted.")
                        return result
                    return result
                except NON_RETRYABLE_EXCEPTIONS:
                    # Critical compliance or fatal abort
                    raise
                except tuple(retryable_exceptions) as exc:
                    last_exc = exc
                    if attempt >= max_retries:
                        logger.error(
                            f"{fn.__name__} failed after {max_retries + 1} attempts. Final error: {exc}"
                        )
                        raise
                    delay = compute_backoff_delay(
                        attempt=attempt,
                        base_delay=base_delay,
                        backoff_factor=backoff_factor,
                        max_delay=max_delay,
                        jitter=jitter,
                    )
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries + 1} failed for {fn.__name__}: {exc}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    sleep_fn(delay)

            if last_exc:
                raise last_exc

        return wrapper
    return decorator
