"""
Retry logic with exponential backoff.

Used by collectors and any component that makes network requests.
Configurable via the retry section of config.yaml.
"""
from __future__ import annotations

import time
import functools
from typing import Callable, TypeVar, Any
from core.logger import get_logger

logger = get_logger("retry")

T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    initial_backoff: float = 1.0,
    max_backoff: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
) -> Callable:
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        initial_backoff: Initial backoff in seconds.
        max_backoff: Maximum backoff in seconds.
        retryable_exceptions: Tuple of exception types that trigger a retry.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            last_exception = None
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    attempt += 1
                    last_exception = e
                    if attempt >= max_attempts:
                        logger.error(
                            f"Retry exhausted for {func.__name__}",
                            extra={"attempts": attempt, "error": str(e)}
                        )
                        raise
                    backoff = min(initial_backoff * (2 ** (attempt - 1)), max_backoff)
                    logger.warning(
                        f"Retry {attempt}/{max_attempts} for {func.__name__} in {backoff:.1f}s",
                        extra={"attempt": attempt, "backoff": backoff, "error": str(e)}
                    )
                    time.sleep(backoff)
            raise last_exception  # type: ignore
        return wrapper
    return decorator


class RetryConfig:
    """Parse retry config from a dict."""

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.max_attempts: int = config.get("max_attempts", 3)
        self.initial_backoff: float = config.get("initial_backoff", 1.0)
        self.max_backoff: float = config.get("max_backoff", 10.0)
        self.retryable_status_codes: list[int] = config.get("retryable_status_codes", [429, 500, 502, 503, 504])

    def get_decorator(self) -> Callable:
        return retry(
            max_attempts=self.max_attempts,
            initial_backoff=self.initial_backoff,
            max_backoff=self.max_backoff,
        )
