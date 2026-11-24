"""Unit coverage for Deco Wi-Fi readback and entity state propagation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tplinkrouterc6u import (
    Connection,
    Status,
    TPLinkDecoClient,
    TplinkDecoE4RRouter,
    TplinkDecoSGRouter,
    WifiVerificationUnavailable,
    WifiWriteNotObserved,
    WifiWriteResult,
)

from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.coordinator import (
    TPLinkRouterCoordinator,
    is_verified_deco_wifi_client,
)
from custom_components.tplink_router.switch import (
    DHCP_SERVER_SWITCH_TYPES,
    LED_SWITCH_TYPES,
    STATUS_SWITCH_TYPES,
    TPLinkRouterSwitch,
)


class FakeHass:
    async def async_add_executor_job(self, callback, *args):
        await asyncio.sleep(0)
        return callback(*args)


class FakeDecoClient(TPLinkDecoClient):
    """Keep the real Deco type while replacing every transport operation."""

    def __init__(self):
        self.authorize = Mock()
        self.logout = Mock()
        self.set_wifi = Mock()
        self.set_wifi_verified = Mock()
        self.get_status = Mock(side_effect=RuntimeError("WAN read unavailable"))


class FakeLegacyDecoClient(FakeDecoClient):
    supports_verified_wifi = False


def make_coordinator(router=None, **status):
    coordinator = TPLinkRouterCoordinator.__new__(TPLinkRouterCoordinator)
    coordinator.hass = FakeHass()
    coordinator.router = router if router is not None else FakeDecoClient()
    coordinator.status = Status(**status)
    coordinator._lock = asyncio.Lock()
    coordinator.config_entry = None
    coordinator.last_update_success = True
    coordinator.unique_id = "entry-1"
    coordinator.device_info = {"identifiers": {(DOMAIN, "00:00:00:00:00:00")}}
    coordinator.async_update_listeners = Mock()
    return coordinator


def make_entity(coordinator, key="wifi_guest_24g"):
    switch = next(item for item in STATUS_SWITCH_TYPES if item.description.key == key)
    entity = TPLinkRouterSwitch(coordinator, switch)
    entity.async_write_ha_state = Mock()
    return entity


def observed_result(**states):
    return WifiWriteResult(
        Connection.GUEST_2G,
        True,
        {getattr(Connection, connection): value for connection, value in states.items()},
    )


def test_verified_deco_write_updates_only_observed_wifi_without_full_status_poll():
    coordinator = make_coordinator(
        guest_2g_enable=False,
        guest_5g_enable=True,
        wifi_2g_enable=True,
        ewan_connected=True,
        lan_ipv4_dhcp_enable=True,
    )
    router = coordinator.router
    router.set_wifi_verified.return_value = observed_result(
        GUEST_2G=True, GUEST_5G=False, HOST_2G=False
    )
    calls = Mock()
    for name in ("authorize", "set_wifi_verified", "logout"):
        calls.attach_mock(getattr(router, name), name)

    asyncio.run(coordinator.set_wifi(Connection.GUEST_2G, True))

    router.set_wifi_verified.assert_called_once_with(Connection.GUEST_2G, True)
    router.set_wifi.assert_not_called()
    router.get_status.assert_not_called()
    assert [call[0] for call in calls.mock_calls] == [
        "authorize", "set_wifi_verified", "logout"
    ]
    assert coordinator.status.guest_2g_enable is True
    assert coordinator.status.guest_5g_enable is False
    assert coordinator.status.wifi_2g_enable is False
    assert coordinator.status.ewan_connected is True
    assert coordinator.status.lan_ipv4_dhcp_enable is True
    coordinator.async_update_listeners.assert_called_once()


@pytest.mark.parametrize(
    ("connection", "field"),
    [
        (Connection.HOST_2G, "wifi_2g_enable"),
        (Connection.HOST_5G, "wifi_5g_enable"),
        (Connection.HOST_6G, "wifi_6g_enable"),
        (Connection.GUEST_2G, "guest_2g_enable"),
        (Connection.GUEST_5G, "guest_5g_enable"),
        (Connection.GUEST_6G, "guest_6g_enable"),
    ],
)
def test_every_supported_deco_band_uses_observed_state(connection, field):
    coordinator = make_coordinator(**{field: True})
    coordinator.router.set_wifi_verified.return_value = SimpleNamespace(
        states={connection: False}
    )

    asyncio.run(coordinator.set_wifi(connection, False))

    assert getattr(coordinator.status, field) is False
    coordinator.router.set_wifi_verified.assert_called_once_with(connection, False)


@pytest.mark.parametrize("invalid", [None, 0, 1, "off", "false", {}, []])
def test_invalid_readback_values_do_not_replace_known_state(invalid):
    coordinator = make_coordinator(guest_2g_enable=True, guest_5g_enable=True)
    coordinator.router.set_wifi_verified.return_value = SimpleNamespace(
        states={
            Connection.GUEST_2G: invalid,
            Connection.GUEST_5G: False,
            "ewan_connected": False,
        }
    )

    asyncio.run(coordinator.set_wifi(Connection.GUEST_5G, False))

    assert coordinator.status.guest_2g_enable is True
    assert coordinator.status.guest_5g_enable is False
    assert coordinator.status.ewan_connected is None


def test_failure_publishes_latest_observed_state_before_reraising():
    coordinator = make_coordinator(guest_2g_enable=False, guest_5g_enable=False)
    error = WifiWriteNotObserved({Connection.GUEST_2G: True, Connection.GUEST_5G: True})
    coordinator.router.set_wifi_verified.side_effect = error
    notifications = []
    coordinator.async_update_listeners.side_effect = lambda: notifications.append(
        (coordinator.status.guest_2g_enable, coordinator.status.guest_5g_enable)
    )

    with pytest.raises(WifiWriteNotObserved) as raised:
        asyncio.run(coordinator.set_wifi(Connection.GUEST_5G, False))

    assert raised.value is error
    assert notifications == [(True, True)]
    coordinator.router.logout.assert_called_once()
    coordinator.router.get_status.assert_not_called()


@pytest.mark.parametrize("latest_states", [None, {}, {Connection.GUEST_2G: "off"}])
def test_unavailable_readback_retains_last_state(latest_states):
    coordinator = make_coordinator(guest_2g_enable=True)
    error = WifiVerificationUnavailable(latest_states)
    coordinator.router.set_wifi_verified.side_effect = error

    with pytest.raises(WifiVerificationUnavailable, match="could not be verified"):
        asyncio.run(coordinator.set_wifi(Connection.GUEST_2G, False))

    assert coordinator.status.guest_2g_enable is True
    coordinator.async_update_listeners.assert_not_called()
    coordinator.router.logout.assert_called_once()


@pytest.mark.parametrize("capability", [True, "missing"])
def test_deco_without_verifier_fails_before_any_router_write(capability, monkeypatch):
    if capability == "missing":
        monkeypatch.delattr(TPLinkDecoClient, "supports_verified_wifi", raising=False)
    coordinator = make_coordinator(guest_2g_enable=True)
    coordinator.router.set_wifi_verified = None

    with pytest.raises(RuntimeError, match="does not support verified Wi-Fi writes"):
        asyncio.run(coordinator.set_wifi(Connection.GUEST_2G, False))

    coordinator.router.authorize.assert_not_called()
    coordinator.router.set_wifi.assert_not_called()
    coordinator.router.logout.assert_not_called()
    assert coordinator.status.guest_2g_enable is True


@pytest.mark.parametrize("router_class", [FakeLegacyDecoClient, TplinkDecoSGRouter, TplinkDecoE4RRouter])
def test_deco_transport_without_verification_keeps_legacy_write_and_display(router_class):
    router = router_class.__new__(router_class)
    FakeDecoClient.__init__(router)
    coordinator = make_coordinator(router, guest_2g_enable=False)
    entity = make_entity(coordinator)

    assert router.supports_verified_wifi is False
    assert is_verified_deco_wifi_client(router) is False

    asyncio.run(entity.async_turn_on())

    router.set_wifi.assert_called_once_with(Connection.GUEST_2G, True)
    assert entity.is_on is True
    router.set_wifi.reset_mock()

    asyncio.run(entity.async_turn_off())

    router.set_wifi.assert_called_once_with(Connection.GUEST_2G, False)
    assert entity.is_on is False
    router.set_wifi_verified.assert_not_called()
    assert router.authorize.call_count == router.logout.call_count == 2


def test_non_deco_client_keeps_existing_write_path_even_with_verifier_method():
    router = SimpleNamespace(
        authorize=Mock(), logout=Mock(), set_wifi=Mock(), set_wifi_verified=Mock()
    )
    coordinator = make_coordinator(router, guest_2g_enable=True)

    asyncio.run(coordinator.set_wifi(Connection.GUEST_2G, False))

    router.set_wifi.assert_called_once_with(Connection.GUEST_2G, False)
    router.set_wifi_verified.assert_not_called()
    router.authorize.assert_called_once()
    router.logout.assert_called_once()
    assert coordinator.status.guest_2g_enable is True


def test_verified_writes_and_state_notifications_hold_router_lock():
    coordinator = make_coordinator(guest_2g_enable=False)
    observations = []

    def verify(connection, enable):
        observations.append(("write", coordinator._lock.locked(), enable))
        return SimpleNamespace(states={connection: enable})

    coordinator.router.set_wifi_verified.side_effect = verify
    coordinator.async_update_listeners.side_effect = lambda: observations.append(
        ("notify", coordinator._lock.locked(), coordinator.status.guest_2g_enable)
    )

    async def write_both():
        await asyncio.gather(
            coordinator.set_wifi(Connection.GUEST_2G, True),
            coordinator.set_wifi(Connection.GUEST_2G, False),
        )

    asyncio.run(write_both())

    assert observations == [
        ("write", True, True),
        ("notify", True, True),
        ("write", True, False),
        ("notify", True, False),
    ]
    assert not coordinator._lock.locked()


def test_logout_failure_does_not_discard_verified_result():
    coordinator = make_coordinator(guest_2g_enable=False)
    coordinator.router.set_wifi_verified.return_value = observed_result(GUEST_2G=True)
    coordinator.router.logout.side_effect = RuntimeError("Session already closed")

    asyncio.run(coordinator.set_wifi(Connection.GUEST_2G, True))

    assert coordinator.status.guest_2g_enable is True
    coordinator.async_update_listeners.assert_called_once()


@pytest.mark.parametrize("enable", [False, True])
def test_deco_switch_uses_coordinator_state_instead_of_requested_value(enable):
    coordinator = make_coordinator(guest_2g_enable=not enable)
    coordinator.set_wifi = AsyncMock()
    entity = make_entity(coordinator)

    asyncio.run(entity.async_turn_on() if enable else entity.async_turn_off())

    coordinator.set_wifi.assert_awaited_once_with(Connection.GUEST_2G, enable)
    assert entity.is_on is not enable
    entity.async_write_ha_state.assert_called_once()


def test_switch_failure_retains_latest_readback_for_entity_and_listeners():
    coordinator = make_coordinator(guest_2g_enable=False)
    error = WifiWriteNotObserved({Connection.GUEST_2G: True})
    coordinator.router.set_wifi_verified.side_effect = error
    entity = make_entity(coordinator)

    with pytest.raises(WifiWriteNotObserved, match="was not observed"):
        asyncio.run(entity.async_turn_off())

    assert entity.is_on is True
    coordinator.async_update_listeners.assert_called_once()
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.parametrize("switch", [DHCP_SERVER_SWITCH_TYPES[0], LED_SWITCH_TYPES[0]])
def test_other_deco_switches_keep_existing_state_behavior(switch):
    coordinator = make_coordinator(lan_ipv4_dhcp_enable=False)
    coordinator.led_status = False
    coordinator.set_ipv4_dhcps = AsyncMock()
    coordinator.set_led = AsyncMock()
    entity = TPLinkRouterSwitch(coordinator, switch)
    entity.async_write_ha_state = Mock()

    asyncio.run(entity.async_turn_on())
    assert entity.is_on is True
    asyncio.run(entity.async_turn_off())
    assert entity.is_on is False


def test_deco_wifi_entity_preserves_domain_key_unique_id_and_device():
    coordinator = make_coordinator(guest_2g_enable=False)
    entity = make_entity(coordinator)

    assert DOMAIN == "tplink_router"
    assert entity.entity_description.key == "wifi_guest_24g"
    assert entity.unique_id == "entry-1_tplink_router_wifi_guest_24g"
    assert entity.device_info is coordinator.device_info
