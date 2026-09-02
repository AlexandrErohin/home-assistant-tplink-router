import asyncio
import logging
from unittest.mock import Mock, patch

from custom_components.tplink_router import async_setup_entry
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator


class FakeHass:
    def __init__(self):
        self.data = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _entry(**overrides):
    entry = Mock()
    entry.entry_id = "entry-1"
    entry.data = {
        "host": "192.168.1.254",
        "password": "pass",
        "username": "admin",
        "verify_ssl": False,
        "client_class": "MockRouter",
        "scan_interval": 60,
        "support_tracker": True,
        "support_vpn": True,
    }
    entry.data.update(overrides)
    return entry


def test_async_setup_entry_returns_false_when_initial_request_fails(caplog):
    """A failing initial request must fail this entry gracefully, not raise."""
    hass = FakeHass()
    entry = _entry()
    client = Mock()
    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch.object(
        TPLinkRouterCoordinator, "request", side_effect=Exception("Cannot authorize!")
    ):
        with caplog.at_level(logging.ERROR):
            assert asyncio.run(async_setup_entry(hass, entry)) is False
    assert "TPLink Router setup failed for" in caplog.text


def test_async_setup_entry_returns_false_when_client_init_fails(caplog):
    """Client construction/discovery failures must also isolate the entry."""
    hass = FakeHass()
    entry = _entry()
    del entry.data["client_class"]
    with patch.object(
        TPLinkRouterCoordinator,
        "get_client",
        side_effect=Exception("connection timed out"),
    ):
        with caplog.at_level(logging.ERROR):
            assert asyncio.run(async_setup_entry(hass, entry)) is False
    assert "TPLink Router setup failed for" in caplog.text
