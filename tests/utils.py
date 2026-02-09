"""Retry utilities for integration tests.

Provides a decorator that retries test functions on transient network
failures, rate limit errors, and timeout errors.  Designed for tests
that hit Meta's live API servers.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, TypeVar

import requests

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Exception types that are considered transient and worth retrying.
_TRANSIENT_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.HTTPError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry_on_transient(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = _TRANSIENT_EXCEPTIONS,
) -> Callable[[F], F]:
    """Decorator that retries a function on transient failures.

    Uses exponential backoff between attempts.  On final failure the
    original exception is re-raised so pytest can report it properly.

    Args:
        max_retries: Maximum number of retry attempts (total calls = max_retries + 1).
        backoff_factor: Multiplier for the wait time between retries.
            Wait time = backoff_factor ** attempt.
        exceptions: Tuple of exception types to catch and retry on.

    Returns:
        Decorated function.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff_factor ** attempt
                        logger.warning(
                            "Transient failure in %s (attempt %d/%d): %s. "
                            "Retrying in %.1fs...",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            exc,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_retries + 1,
                            func.__name__,
                            exc,
                        )
            # Should not reach here, but satisfy type checker
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("retry_on_transient: unexpected state")

        return wrapper  # type: ignore[return-value]

    return decorator
