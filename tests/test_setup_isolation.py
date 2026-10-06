import asyncio
import logging
from unittest.mock import AsyncMock, Mock, patch

from tplinkrouterc6u import TPLinkSG108EClient

from custom_components.tplink_router import async_setup_entry
from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator


class FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = Mock()
        self.config_entries.async_forward_entry_setups = AsyncMock()

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
    entry.async_on_unload = Mock()
    entry.add_update_listener = Mock(return_value=Mock())
    return entry


def _firmware_status():
    firmware = Mock()
    firmware.model = "TL-SG108E"
    firmware.firmware_version = "1.0.0"
    firmware.hardware_version = "6.0"
    status = Mock()
    status.lan_macaddr = "00:11:22:33:44:55"
    return firmware, status


class PlainClient:
    """Client without LED set API (led_status alone must not enable LED)."""

    def __init__(self):
        firmware, status = _firmware_status()
        self.host = "http://192.168.1.254"
        self.get_firmware = Mock(return_value=firmware)
        self.get_status = Mock(return_value=status)
        self.authorize = Mock()
        self.logout = Mock()
        self.led_status = Mock(return_value=True)


def _sg108e_client(*, led_status):
    client = TPLinkSG108EClient.__new__(TPLinkSG108EClient)
    firmware, status = _firmware_status()
    client.host = "http://192.168.1.254"
    client.get_firmware = Mock(return_value=firmware)
    client.get_status = Mock(return_value=status)
    client.led_status = led_status
    client.set_led = Mock()
    client.authorize = Mock()
    client.logout = Mock()
    return client


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


def test_async_setup_entry_reads_sg108e_led_successfully():
    hass = FakeHass()
    entry = _entry(client_class="TPLinkSG108EClient")
    client = _sg108e_client(led_status=Mock(return_value=True))

    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch(
        "custom_components.tplink_router.collect_mesh_nodes", return_value=None
    ), patch(
        "custom_components.tplink_router.register_services"
    ), patch(
        "custom_components.tplink_router._async_add_listeners"
    ), patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ):
        assert asyncio.run(async_setup_entry(hass, entry)) is True

    client.led_status.assert_called_once()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.led_status is True


def test_async_setup_entry_led_failure_does_not_fail_setup(caplog):
    hass = FakeHass()
    entry = _entry(client_class="TPLinkSG108EClient")
    client = _sg108e_client(
        led_status=Mock(side_effect=RuntimeError("led page unavailable"))
    )

    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch(
        "custom_components.tplink_router.collect_mesh_nodes", return_value=None
    ), patch(
        "custom_components.tplink_router.register_services"
    ), patch(
        "custom_components.tplink_router._async_add_listeners"
    ), patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ), caplog.at_level(logging.DEBUG):
        assert asyncio.run(async_setup_entry(hass, entry)) is True

    client.led_status.assert_called_once()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.led_status is None
    assert "led_status failed" in caplog.text


def test_async_setup_entry_skips_led_without_set_led():
    hass = FakeHass()
    entry = _entry()
    client = PlainClient()

    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch(
        "custom_components.tplink_router.collect_mesh_nodes", return_value=None
    ), patch(
        "custom_components.tplink_router.register_services"
    ), patch(
        "custom_components.tplink_router._async_add_listeners"
    ), patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ):
        assert asyncio.run(async_setup_entry(hass, entry)) is True

    client.led_status.assert_not_called()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.led_status is None
