# tests/test_utils.py
from unittest.mock import Mock

import pytest

from tplinkrouterc6u import AuthorizeError

from custom_components.tplink_router.utils import (
    is_retryable_error,
    prefer,
    run_with_retry,
    safe_call,
)


def test_run_with_retry_with_zero_retries_still_runs_once():
    calls = []

    def cb():
        calls.append(1)
        return "ok"

    assert run_with_retry(cb, retries=0, backoff_seconds=0) == "ok"
    assert calls == [1]


def test_run_with_retry_succeeds_immediately():
    calls = []

    def cb():
        calls.append(1)
        return "ok"

    assert run_with_retry(cb, retries=3, backoff_seconds=0) == "ok"
    assert calls == [1]


def test_run_with_retry_retries_then_succeeds():
    calls = []

    def cb():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("boom")
        return "ok"

    assert run_with_retry(cb, retries=5, backoff_seconds=0) == "ok"
    assert len(calls) == 3


def test_run_with_retry_gives_up_and_raises_last_error():
    def cb():
        raise TimeoutError("boom")

    with pytest.raises(TimeoutError):
        run_with_retry(cb, retries=2, backoff_seconds=0)


def test_run_with_retry_logs_warning():
    logger = Mock()
    calls = []

    def cb():
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        run_with_retry(cb, retries=2, backoff_seconds=0, logger=logger)
    assert logger.warning.call_count == 2


def test_run_with_retry_does_not_retry_non_retryable_error():
    calls = []

    def cb():
        calls.append(1)
        raise AuthorizeError("Login failed")

    with pytest.raises(AuthorizeError):
        run_with_retry(cb, retries=5, backoff_seconds=0, is_retryable=is_retryable_error)
    assert calls == [1]


def test_is_retryable_error_rejects_authorize_error():
    assert not is_retryable_error(AuthorizeError("Login failed"))


def test_is_retryable_error_rejects_cannot_authorize_message():
    assert not is_retryable_error(ValueError("TplinkRouter - Cannot authorize! Error - 'data'"))


def test_is_retryable_error_rejects_401():
    assert not is_retryable_error(RuntimeError("Network error: 401 Client Error: OK"))


def test_is_retryable_error_accepts_transient_errors():
    assert is_retryable_error(TimeoutError("Read timed out"))


def test_safe_call_returns_value():
    assert safe_call(lambda: 42, None, "fetch") == 42


def test_safe_call_returns_default_on_error():
    def cb():
        raise RuntimeError("inbox too big")

    assert safe_call(cb, Mock(), "fetch SMS") is None


def test_prefer_current_when_meaningful():
    assert prefer("10.0.0.5", "192.168.1.1") == "10.0.0.5"


def test_prefer_falls_back_to_last_known_for_zero_ip():
    assert prefer("0.0.0.0", "192.168.1.1") == "192.168.1.1"


def test_prefer_falls_back_to_last_known_for_none():
    assert prefer(None, "192.168.1.1") == "192.168.1.1"


def test_prefer_uses_fallback_when_nothing_known():
    assert prefer(None, "") == ""
