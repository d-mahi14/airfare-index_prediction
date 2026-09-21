"""
scraper/framework package
Exports core collector framework abstractions, rate limiter, robots guard, retry,
circuit breaker, and block detector.
"""
from scraper.base import BaseCollector, BlockedResult, CollectorError, DisallowedError
from scraper.framework.block_detector import BlockDetector, detect_block
from scraper.framework.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from scraper.framework.rate_limiter import RateLimiter
from scraper.framework.retry import compute_backoff_delay, retry_with_backoff
from scraper.framework.robots_guard import RobotsGuard

__all__ = [
    "BaseCollector",
    "CollectorError",
    "DisallowedError",
    "BlockedResult",
    "RateLimiter",
    "RobotsGuard",
    "retry_with_backoff",
    "compute_backoff_delay",
    "BlockDetector",
    "detect_block",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
]
