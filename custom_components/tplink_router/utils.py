from __future__ import annotations

import re
import time
from collections.abc import Callable
from logging import Logger
from typing import Any, TypeVar

from tplinkrouterc6u import AuthorizeError

T = TypeVar("T")

_AUTH_FAILURE_RE = re.compile(
    r"(?i)(?:cannot\s+authorize|\b401\b(?:\s+client\s+error)?|unauthorized|login\s+failed)"
)
_TRANSIENT_RE = re.compile(
    r"(?i)(?:session\s+timed?\s*out|timed?\s*out|timeout|temporarily|connection\s+reset|"
    r"connection\s+aborted|remote\s+end\s+closed)"
)


def run_with_retry(
        callback: Callable[[], T],
        retries: int = 3,
        backoff_seconds: float = 1.0,
        logger: Logger | None = None,
        is_retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """Run a blocking callback, retrying transient errors with a growing backoff.

    Used by unit tests and any sync callers. Live coordinator polling does not
    use this helper: ``TPLinkRouterCoordinator._async_update_data`` retries with
    ``asyncio.sleep`` between attempts so the router lock is not held during backoff.
    """
    retries = max(1, retries)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return callback()
        except Exception as error:
            if is_retryable is not None and not is_retryable(error):
                raise
            last_error = error
            if logger is not None:
                logger.warning(
                    "TPLink Router request attempt %s/%s failed: %s",
                    attempt + 1,
                    retries,
                    error,
                )
            if attempt < retries - 1:
                time.sleep(backoff_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


def is_retryable_error(error: Exception) -> bool:
    """Return whether a polling error should be retried.

    Transient failures (timeouts, dropped connections, session expiry) are
    retried because each attempt re-authorizes. Permanent auth failures
    (bad credentials / HTTP 401) are not retried — that only delays failure
    and may trigger the router's login attempt limit.
    """
    message = str(error)
    if _TRANSIENT_RE.search(message):
        return True
    if isinstance(error, AuthorizeError):
        return False
    if _AUTH_FAILURE_RE.search(message):
        return False
    return True


def safe_call(callback: Callable[[], T], logger: Logger | None, label: str, default: Any = None) -> Any:
    """Run a blocking callback, returning default instead of raising on failure."""
    try:
        return callback()
    except Exception:
        if logger is not None:
            logger.warning("TPLink Router failed to %s", label, exc_info=True)
        return default


def prefer(current: Any, last_known: Any, fallback: Any = "") -> Any:
    """Return current when meaningful, else last known, else fallback."""
    if current is not None and current != "" and str(current) != "0.0.0.0":
        return current
    if last_known:
        return last_known
    return fallback
