import logging

from custom_components.tplink_router.const import DEFAULT_SCAN_PAUSE
from custom_components.tplink_router.coordinator import collect_status


class FakeRouter:
    def __init__(self):
        self.status = "STATUS_OK"
        self.lte = "LTE_OK"
        self.ports = ["PORT_OK"]
        self.port_calls = 0

    def get_status(self):
        return self.status

    def get_lte_status(self):
        return self.lte

    def get_port_status(self):
        self.port_calls += 1
        return self.ports

    def get_sms(self):
        raise RuntimeError("inbox too big")


def test_collect_status_ignores_sms_failure():
    router = FakeRouter()
    result = collect_status(
        router, object(), None, None, None, None, logging.getLogger("test")
    )
    assert result[0] == "STATUS_OK"
    assert result[5] is None
    assert result[6] is None


def test_collect_status_does_not_call_get_sms_without_lte():
    router = FakeRouter()
    result = collect_status(
        router, None, None, None, None, None, logging.getLogger("test")
    )
    assert result[0] == "STATUS_OK"
    assert result[1] is None
    assert result[6] is None


def test_collect_status_refreshes_port_status_when_enabled():
    router = FakeRouter()
    result = collect_status(
        router, None, None, None, None, [], logging.getLogger("test")
    )
    assert result[5] == ["PORT_OK"]
    assert router.port_calls == 1


def test_collect_status_skips_port_status_when_disabled():
    router = FakeRouter()
    result = collect_status(
        router, None, None, None, None, None, logging.getLogger("test")
    )
    assert result[5] is None
    assert router.port_calls == 0


def test_scan_pause_default_is_twenty_minutes():
    assert DEFAULT_SCAN_PAUSE == 20
