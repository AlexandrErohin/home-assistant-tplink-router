import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant.common import MockConfigEntry, MockEntityPlatform

from custom_components.tplink_router import (
    BLOCK_DEVICE_SCHEMA,
    UNBLOCK_DEVICE_SCHEMA,
    async_setup_entry as async_setup_integration,
    async_unload_entry,
    get_coordinator_for_device,
    register_services,
)
from custom_components.tplink_router.access_control import (
    TPLinkBlockedDeviceSwitch,
    setup_blocked_device_entities,
)
from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.coordinator import (
    TPLinkRouterCoordinator,
    collect_status,
    supports_access_control,
)
from custom_components.tplink_router.switch import (
    ACCESS_CONTROL_SWITCH_TYPES,
    STATUS_SWITCH_TYPES,
    TPLinkRouterSwitch,
    async_setup_entry as async_setup_switches,
)

from custom_components.tplink_router.const import DEFAULT_SCAN_PAUSE

PHONE = "AA-BB-CC-DD-EE-01"
TV = "AA-BB-CC-DD-EE-02"


class FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = Mock()
        self.config_entries.async_forward_entry_setups = AsyncMock()

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class FakeRouter:
    def get_status(self):
        return "STATUS_OK"


class PlainClient:
    """Client without Access Control."""

    def __init__(self):
        firmware = Mock(model="Archer C6", firmware_version="1.1.0", hardware_version="6.0")
        status = Mock(lan_macaddr="00:11:22:33:44:55")
        self.host = "http://192.168.0.1"
        self.get_firmware = Mock(return_value=firmware)
        self.get_status = Mock(return_value=status)
        self.authorize = Mock()
        self.logout = Mock()


def _entry():
    entry = Mock()
    entry.entry_id = "entry-1"
    entry.data = {
        "host": "192.168.0.1",
        "password": "pass",
        "username": "admin",
        "verify_ssl": False,
        "client_class": "TplinkRouterSG",
        "scan_interval": 60,
        "support_tracker": True,
        "support_vpn": False,
    }
    entry.async_on_unload = Mock()
    entry.add_update_listener = Mock(return_value=Mock())
    return entry


def _bare_coordinator(router):
    coord = TPLinkRouterCoordinator.__new__(TPLinkRouterCoordinator)
    coord.hass = FakeHass()
    coord.router = router
    coord.scan_pause_minutes = DEFAULT_SCAN_PAUSE
    coord._lock = asyncio.Lock()
    coord.logger = logging.getLogger("test")
    coord.async_update_listeners = Mock()
    coord.access_control = router.access
    coord.blocked_devices = []
    return coord


def _blocked(mac, name=""):
    return SimpleNamespace(macaddr=mac, hostname=name)


def _client(mac, hostname=""):
    return SimpleNamespace(macaddr=mac, hostname=hostname)


class AccessControlRouter(FakeRouter):
    """Router with the tplinkrouterc6u Access Control API, backed by a list."""

    def __init__(self, blocked=None, enable=False):
        self.blocked = list(blocked or [])
        self.access = SimpleNamespace(enable=enable, mode="blacklist")
        self.calls = []

    def get_access_control(self):
        return self.access

    def set_access_control(self, enable=None, mode=None):
        self.calls.append(("set_access_control", enable, mode))
        self.access.enable = enable

    def get_blocked_devices(self):
        return list(self.blocked)

    def block_device(self, mac, name=""):
        self.calls.append(("block_device", mac, name))
        self.blocked.append(_blocked(mac, name))

    def unblock_device(self, mac):
        self.calls.append(("unblock_device", mac))
        self.blocked = [d for d in self.blocked if d.macaddr != mac]


def test_supports_access_control_needs_list_block_and_unblock():
    assert supports_access_control(AccessControlRouter())
    assert not supports_access_control(FakeRouter())
    partial = FakeRouter()
    partial.get_blocked_devices = Mock()
    assert not supports_access_control(partial)


def test_collect_status_polls_access_control_when_supported():
    router = AccessControlRouter([_blocked(PHONE)], enable=True)
    result = collect_status(
        router, None, None, None, None, None, None, logging.getLogger("test"),
        access_control=SimpleNamespace(enable=False, mode="blacklist"), blocked_devices=[],
    )
    assert result[10].enable is True
    assert [d.macaddr for d in result[11]] == [PHONE]


def test_collect_status_skips_access_control_when_unsupported():
    router = AccessControlRouter([_blocked(PHONE)])
    router.get_blocked_devices = Mock()
    router.get_access_control = Mock()
    result = collect_status(router, None, None, None, None, None, None, logging.getLogger("test"))
    assert result[10] is None
    assert result[11] is None
    router.get_blocked_devices.assert_not_called()
    router.get_access_control.assert_not_called()


def test_collect_status_keeps_last_access_control_on_failure():
    router = FakeRouter()
    router.get_access_control = Mock(side_effect=RuntimeError("session dropped"))
    router.get_blocked_devices = Mock(side_effect=RuntimeError("session dropped"))
    last_access = SimpleNamespace(enable=False, mode="blacklist")
    last_blocked = [_blocked(PHONE)]
    result = collect_status(
        router, None, None, None, None, None, None, logging.getLogger("test"),
        access_control=last_access, blocked_devices=last_blocked,
    )
    assert result[10] is last_access
    assert result[11] is last_blocked


def _live_coordinator(router):
    router.authorize = Mock()
    router.logout = Mock()
    return _bare_coordinator(router)


def test_coordinator_block_and_unblock_refresh_the_list():
    router = AccessControlRouter()
    coord = _live_coordinator(router)

    asyncio.run(coord.block_device(PHONE, "phone"))
    assert router.calls == [("block_device", PHONE, "phone")]
    assert [d.macaddr for d in coord.blocked_devices] == [PHONE]
    coord.async_update_listeners.assert_called_once()

    asyncio.run(coord.unblock_device(PHONE))
    assert router.calls[-1] == ("unblock_device", PHONE)
    assert coord.blocked_devices == []
    # Blocking never touches the Access Control switch or its mode.
    assert not any(call[0] == "set_access_control" for call in router.calls)


def test_coordinator_set_access_control_changes_only_enable():
    router = AccessControlRouter()
    coord = _live_coordinator(router)
    asyncio.run(coord.set_access_control(True))
    assert router.calls == [("set_access_control", True, None)]


def _switch_coordinator(blocked=None, access_control=None, devices=()):
    router = AccessControlRouter(blocked)
    coordinator = Mock()
    coordinator.unique_id = "entry-1"
    coordinator.device_info = {"identifiers": {(DOMAIN, "aa:bb")}}
    coordinator.last_update_success = True
    coordinator.router = router
    coordinator.status = SimpleNamespace(
        **{switch.property: None for switch in STATUS_SWITCH_TYPES},
        ewan_connected=None,
        devices=list(devices),
    )
    coordinator.vpn_server_status = None
    coordinator.vpn_client_status = None
    coordinator.led_status = None
    coordinator.parental_status = None
    coordinator.access_control = access_control
    coordinator.blocked_devices = router.get_blocked_devices() if blocked is not None else None
    coordinator.block_device = AsyncMock()
    coordinator.unblock_device = AsyncMock()
    coordinator.set_access_control = AsyncMock()
    coordinator.async_add_listener = Mock(return_value=Mock())
    return coordinator


def _setup_switches(coordinator, **entry_data):
    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}
    entry = Mock()
    entry.entry_id = "entry-1"
    entry.data = {"support_tracker": True, **entry_data}
    added = []
    with patch(
        "custom_components.tplink_router.access_control.er.async_entries_for_config_entry", return_value=[]
    ), patch("custom_components.tplink_router.access_control.er.async_get"):
        asyncio.run(async_setup_switches(hass, entry, lambda entities, update=False: added.extend(entities)))
    return added, entry


def test_switches_added_when_access_control_supported():
    coordinator = _switch_coordinator(
        blocked=[_blocked(TV, "tv")],
        access_control=SimpleNamespace(enable=False, mode="blacklist"),
        devices=[_client(PHONE, "phone")],
    )
    added, _ = _setup_switches(coordinator)

    master = [e for e in added if isinstance(e, TPLinkRouterSwitch) and e.entity_description.key == "access_control"]
    assert len(master) == 1
    assert master[0].is_on is False
    assert master[0].unique_id == f"entry-1_{DOMAIN}_access_control"

    blocked = {e._mac: e for e in added if isinstance(e, TPLinkBlockedDeviceSwitch)}
    # Connected clients and blocked (often offline) devices both get a switch.
    assert set(blocked) == {PHONE, TV}
    assert blocked[TV].is_on is True
    assert blocked[PHONE].is_on is False
    assert blocked[PHONE].entity_registry_enabled_default is False
    assert blocked[PHONE].unique_id == f"entry-1_{DOMAIN}_blocked_aa:bb:cc:dd:ee:01"
    assert blocked[PHONE].device_info["connections"] == {("mac", PHONE)}
    assert blocked[PHONE].device_info["name"] == "phone"


def test_switches_skipped_without_access_control():
    added, _ = _setup_switches(_switch_coordinator(devices=[_client(PHONE)]))
    assert not any(isinstance(e, TPLinkBlockedDeviceSwitch) for e in added)
    assert not any(
        isinstance(e, TPLinkRouterSwitch) and e.entity_description.key == "access_control" for e in added
    )


def test_blocked_switches_skipped_without_trackers():
    coordinator = _switch_coordinator(blocked=[], access_control=SimpleNamespace(enable=False, mode="blacklist"),
                                      devices=[_client(PHONE)])
    added, _ = _setup_switches(coordinator, support_tracker=False)
    assert not any(isinstance(e, TPLinkBlockedDeviceSwitch) for e in added)


def test_blocked_switch_added_for_new_client_on_update():
    coordinator = _switch_coordinator(blocked=[], devices=[_client(PHONE)])
    added, _ = _setup_switches(coordinator)
    listener = coordinator.async_add_listener.call_args[0][0]

    coordinator.status.devices.append(_client(TV))
    listener()
    listener()  # a second update must not add duplicates
    assert sorted(e._mac for e in added if isinstance(e, TPLinkBlockedDeviceSwitch)) == [PHONE, TV]


def test_blocked_switch_turn_on_off_calls_coordinator():
    coordinator = _switch_coordinator(blocked=[], devices=[_client(PHONE, "phone")])
    entity = TPLinkBlockedDeviceSwitch(coordinator, PHONE)

    asyncio.run(entity.async_turn_on())
    coordinator.block_device.assert_awaited_once_with(PHONE, "phone")
    asyncio.run(entity.async_turn_off())
    coordinator.unblock_device.assert_awaited_once_with(PHONE)

    # MAC formats from the router may differ; matching is by normalised MAC.
    coordinator.blocked_devices = [_blocked("aa:bb:cc:dd:ee:01")]
    assert entity.is_on is True
    coordinator.blocked_devices = None
    assert entity.available is False


def test_access_control_switch_lists_mode_and_blocked_devices():
    """The blacklist is readable even for devices whose own Blocked switch is disabled."""
    coordinator = _switch_coordinator(
        blocked=[_blocked(TV, "tv")],
        access_control=SimpleNamespace(enable=True, mode="blacklist"),
        devices=[_client(PHONE, "phone")],
    )
    added, _ = _setup_switches(coordinator)
    master = next(
        e for e in added if isinstance(e, TPLinkRouterSwitch) and e.entity_description.key == "access_control"
    )
    assert master.extra_state_attributes == {
        "mode": "blacklist",
        "blocked_devices": [{"name": "tv", "mac": TV}],
    }
    coordinator.blocked_devices = None
    assert master.extra_state_attributes == {"mode": "blacklist", "blocked_devices": []}


def test_access_control_master_switch_turns_on():
    coordinator = _switch_coordinator(blocked=[], access_control=SimpleNamespace(enable=False, mode="blacklist"))
    entity = TPLinkRouterSwitch(coordinator, ACCESS_CONTROL_SWITCH_TYPES[0])
    entity.async_write_ha_state = Mock()
    asyncio.run(entity.async_turn_on())
    coordinator.set_access_control.assert_awaited_once_with(True)
    assert coordinator.access_control.enable is True


def test_block_device_schemas_validate_mac():
    assert BLOCK_DEVICE_SCHEMA({"device": "d", "mac": "aa:bb:cc:dd:ee:01"}) == {
        "device": "d", "mac": "aa:bb:cc:dd:ee:01", "name": "",
    }
    assert UNBLOCK_DEVICE_SCHEMA({"device": "d", "mac": PHONE})["mac"] == PHONE
    with pytest.raises(vol.Invalid):
        BLOCK_DEVICE_SCHEMA({"device": "d", "mac": "bad"})
    with pytest.raises(vol.Invalid):
        UNBLOCK_DEVICE_SCHEMA({"device": "d", "mac": "bad"})


def _service_hass(coordinator):
    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}
    hass.services.has_service.return_value = False
    return hass


def test_block_services_registered_and_routed():
    coordinator = _switch_coordinator(blocked=[])
    coordinator.lte_status = None
    coordinator.support_dhcp_reservations = False
    hass = _service_hass(coordinator)
    register_services(hass, coordinator)

    handlers = {call.args[1]: call for call in hass.services.async_register.call_args_list}
    assert handlers["block_device"].kwargs["schema"] is BLOCK_DEVICE_SCHEMA
    assert handlers["unblock_device"].kwargs["schema"] is UNBLOCK_DEVICE_SCHEMA

    entry = SimpleNamespace(entry_id="entry-1", domain=DOMAIN)
    with patch(
        "custom_components.tplink_router.device_registry.async_get_device_and_config_entry_for_domain",
        return_value=(SimpleNamespace(id="dev-1"), entry),
        create=True,
    ):
        asyncio.run(handlers["block_device"].args[2](
            SimpleNamespace(data={"device": "dev-1", "mac": PHONE, "name": "phone"})))
        asyncio.run(handlers["unblock_device"].args[2](SimpleNamespace(data={"device": "dev-1", "mac": PHONE})))
    coordinator.block_device.assert_awaited_once_with(PHONE, "phone")
    coordinator.unblock_device.assert_awaited_once_with(PHONE)


def test_block_services_not_registered_without_access_control():
    coordinator = _switch_coordinator()
    coordinator.lte_status = None
    coordinator.support_dhcp_reservations = False
    hass = _service_hass(coordinator)
    register_services(hass, coordinator)
    registered = [call.args[1] for call in hass.services.async_register.call_args_list]
    assert "block_device" not in registered
    assert "unblock_device" not in registered


def test_get_coordinator_for_device_rejects_block_without_access_control():
    entry = SimpleNamespace(entry_id="entry-1", domain=DOMAIN)
    coordinator = _switch_coordinator()
    hass = _service_hass(coordinator)
    with patch(
        "custom_components.tplink_router.device_registry.async_get_device_and_config_entry_for_domain",
        return_value=(SimpleNamespace(id="dev-1"), entry),
        create=True,
    ):
        assert get_coordinator_for_device(hass, "dev-1", "block_device") is None
        coordinator.blocked_devices = []
        assert get_coordinator_for_device(hass, "dev-1", "block_device") is coordinator


class AccessControlClient(PlainClient):
    def __init__(self, blocked_error=None):
        super().__init__()
        self.get_blocked_devices = Mock(side_effect=blocked_error, return_value=[_blocked(PHONE)])
        self.get_access_control = Mock(return_value=SimpleNamespace(enable=False, mode="blacklist"))
        self.set_access_control = Mock()
        self.block_device = Mock()
        self.unblock_device = Mock()


def _run_setup(client):
    hass = FakeHass()
    entry = _entry()
    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch(
        "custom_components.tplink_router.collect_mesh_nodes", return_value=None
    ), patch(
        "custom_components.tplink_router.register_services"
    ), patch(
        "custom_components.tplink_router._async_add_listeners"
    ), patch(
        "custom_components.tplink_router.setup_network_panel", new_callable=AsyncMock
    ), patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ), patch(
        "custom_components.tplink_router.device_registry.async_get",
        return_value=Mock(),
    ):
        assert asyncio.run(async_setup_integration(hass, entry)) is True
    return hass.data[DOMAIN][entry.entry_id]


def test_setup_probes_access_control():
    client = AccessControlClient()
    coordinator = _run_setup(client)
    assert [d.macaddr for d in coordinator.blocked_devices] == [PHONE]
    assert coordinator.access_control.enable is False
    # Probing only reads; it never changes Access Control.
    client.set_access_control.assert_not_called()
    client.block_device.assert_not_called()


def test_setup_disables_access_control_when_probe_fails(caplog):
    with caplog.at_level(logging.DEBUG):
        coordinator = _run_setup(AccessControlClient(blocked_error=RuntimeError("no such form")))
    assert coordinator.blocked_devices is None
    assert coordinator.access_control is None
    assert "Access Control failed" in caplog.text


def test_setup_skips_access_control_without_client_support():
    coordinator = _run_setup(PlainClient())
    assert coordinator.blocked_devices is None
    assert coordinator.access_control is None


async def _add_blocked_switches(hass, coordinator):
    """Run the real setup against Home Assistant's device and entity registries."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry-1", title="Archer C6")
    entry.add_to_hass(hass)
    platform = MockEntityPlatform(hass, domain="switch", platform_name=DOMAIN)
    platform.config_entry = entry
    collected = []
    setup_blocked_device_entities(hass, coordinator, entry, collected.extend)
    await platform.async_add_entities(collected)
    return entry, collected


async def test_blocked_switch_devices_are_named_after_the_client(hass):
    coordinator = _switch_coordinator(blocked=[_blocked(TV, "tv")], devices=[_client(PHONE, "phone")])
    entry, _ = await _add_blocked_switches(hass, coordinator)

    devices = dr.async_get(hass)
    found = {}
    for reg_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        found[reg_entry.entity_id] = (devices.async_get(reg_entry.device_id).name, reg_entry.disabled_by)
    # A connected client takes its hostname; a blocked offline device its blacklist name.
    # Never the router's name (a device with no name is named after the config entry).
    assert found == {
        "switch.phone_blocked": ("phone", er.RegistryEntryDisabler.INTEGRATION),
        "switch.tv_blocked": ("tv", er.RegistryEntryDisabler.INTEGRATION),
    }


async def test_blocked_switch_keeps_existing_device_name(hass):
    coordinator = _switch_coordinator(blocked=[_blocked(TV)], devices=[])
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry-1", title="Archer C6")
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, TV)}, name="living room tv"
    )
    entity = TPLinkBlockedDeviceSwitch(coordinator, TV)
    entity.hass = hass
    assert entity.device_info["name"] == "living room tv"


async def test_blocked_switches_restored_for_offline_clients(hass):
    coordinator = _switch_coordinator(blocked=[], devices=[_client(PHONE)])
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry-1", title="Archer C6")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create("switch", DOMAIN, f"entry-1_{DOMAIN}_blocked_aa:bb:cc:dd:ee:09", config_entry=entry)
    # Same client as the connected one: must not be added twice.
    registry.async_get_or_create("switch", DOMAIN, f"entry-1_{DOMAIN}_blocked_aa:bb:cc:dd:ee:01", config_entry=entry)
    # Other switches of the entry are not Blocked switches.
    registry.async_get_or_create("switch", DOMAIN, f"entry-1_{DOMAIN}_led", config_entry=entry)

    collected = []
    setup_blocked_device_entities(hass, coordinator, entry, collected.extend)
    assert [e._mac for e in collected] == [PHONE, "aa:bb:cc:dd:ee:09"]
    assert collected[1].is_on is False


def test_unload_removes_block_services():
    coordinator = Mock()
    hass = Mock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services.has_service.return_value = True
    entry = Mock()
    entry.entry_id = "entry-1"
    entry.data = {}
    assert asyncio.run(async_unload_entry(hass, entry)) is True
    removed = [call.args[1] for call in hass.services.async_remove.call_args_list]
    assert "block_device" in removed
    assert "unblock_device" in removed
