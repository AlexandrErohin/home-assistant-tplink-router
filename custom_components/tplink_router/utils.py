from __future__ import annotations

import time
from collections.abc import Callable
from logging import Logger
from typing import Any, TypeVar

T = TypeVar("T")


def run_with_retry(
        callback: Callable[[], T],
        retries: int = 3,
        backoff_seconds: float = 1.0,
        logger: Logger | None = None,
) -> T:
    """Run a blocking callback, retrying transient errors with a growing backoff."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return callback()
        except Exception as error:
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
