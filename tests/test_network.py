"""Network workspace tests use synthetic devices only; no router or live HA access."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from json import dumps
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components import frontend
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, Unauthorized, UnknownUser
import pytest
import voluptuous as vol

from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.network import (
    PANEL_PATH, setup_network_panel, snapshot, unload_network_panel,
    websocket_action, websocket_network,
)
from custom_components.tplink_router.parental_control import (
    PROFILE_LIST_PATH, ParentalEditError, ParentalStatus, change_device_profile, parse_profiles,
    assign_profile_devices,
)
from custom_components.tplink_router.parental_services import register_parental_services
from custom_components.tplink_router.permissions import require_admin
from custom_components.tplink_router.switch import TPLinkParentalAccessSwitch, TPLinkParentalScheduleSwitch
from test_parental_control import LOGGER, coordinator
from test_parental_settings import DEVICE, FULL_RECORD, SECOND_DEVICE, firmware, service_hass


def records():
    return [
        {**deepcopy(FULL_RECORD), "client_list": [{**DEVICE, "owner_id": 0, "opaque": {"keep": True}}]},
        {**deepcopy(FULL_RECORD), "owner_id": "1", "name": "Second", "client_list": [SECOND_DEVICE]},
        {**deepcopy(FULL_RECORD), "owner_id": "2", "name": "Empty", "client_list": {}},
    ]


def run_move(client, destination="1", source="0"):
    return change_device_profile(client, LOGGER, DEVICE["mac"], source, destination)


@pytest.mark.parametrize("destination,source", [("1", "0"), ("", "0"), ("2", "")])
def test_explicit_move_assign_remove_preserves_other_memberships_and_fields(destination, source):
    rows = records()
    if not source:
        rows[0]["client_list"] = []
    client, state = firmware(rows)
    if source:
        state.devices[0]["owner_id"] = 0  # Can remain stale after removal; memberships are authoritative.
    before = deepcopy(state.records)
    status, error = run_move(client, destination, source)
    assert error is None
    expected = 2 if source and destination else 1
    assert len(state.writes) == expected
    for row, original in zip(state.records, before, strict=True):
        assert row["opaque_setting"] == original["opaque_setting"]
        assert row["internet_blocked"] == original["internet_blocked"]
        assert row["workday_daily_time"] == original["workday_daily_time"]
        assert row["categories_list"] == original["categories_list"]
    assert status.profiles["0"].clients == ()
    if destination:
        moved = next(c for c in state.records[int(destination)]["client_list"] if c["mac"] == DEVICE["mac"])
        if source:
            assert moved["opaque"] == {"keep": True}
            assert moved["owner_id"] == int(destination)
        assert any(c.device_id == DEVICE["device_id"] for c in status.profiles[destination].clients)
    assert any(c["device_id"] == SECOND_DEVICE["device_id"] for c in state.records[1]["client_list"])


@pytest.mark.parametrize("change,message", [
    ("stale", "membership changed"), ("removed", "target was removed"),
    ("full", "device limit"), ("duplicate", "conflicting"), ("invalid", "incomplete"),
    ("identity", "identity changed"), ("filters", "filter"),
    ("duplicate_id", "identity is ambiguous"), ("key", "row key"),
])
def test_move_preflight_fails_before_any_write(change, message):
    client, state = firmware(records())
    source, destination = "0", "1"
    if change == "stale":
        source = ""
    elif change == "removed":
        destination = "gone"
    elif change == "full":
        state.limits = {"devices_len": 1}
    elif change == "duplicate":
        state.records[1]["client_list"].append(DEVICE)
    elif change == "invalid":
        state.records[2]["client_list"] = {"not": "an array"}
    elif change == "identity":
        state.devices[0]["device_id"] = "changed"
    elif change == "filters":
        state.apps = None
    elif change == "duplicate_id":
        state.records[1]["client_list"][0]["device_id"] = DEVICE["device_id"]
    elif change == "key":
        state.records[1]["key"] = True
    with pytest.raises(ParentalEditError, match=message):
        run_move(client, destination, source)
    assert not state.writes


def test_move_noop_and_unsupported_coordinator_do_not_write():
    client, state = firmware(records())
    _, error = run_move(client, "0")
    assert error is None and not state.writes
    coord = coordinator(client)
    coord.parental_status = None
    with pytest.raises(HomeAssistantError, match="unsupported"):
        asyncio.run(coord.change_device_profile(DEVICE["mac"], "0", "1"))
    assert not state.writes


@pytest.mark.parametrize("failed_step,applied,cleanup_fails", [
    (1, True, False), (1, False, False), (2, True, False), (2, False, False), (2, True, True),
])
def test_move_failure_recovers_original_or_explicitly_reports_unconfirmed_cleanup(failed_step, applied, cleanup_fails):
    client, state = firmware(records())
    original = deepcopy(state.records[0]["client_list"])
    transport = client.request.side_effect

    def request(path, body):
        is_write = path == PROFILE_LIST_PATH and "operation=update" in body
        step = len(state.writes) + 1
        state.apply = not is_write or step != failed_step or applied
        if is_write and (step == failed_step or cleanup_fails and step == 3):
            state.acknowledgement = TimeoutError("do not expose private data")
        else:
            state.acknowledgement = True
        return transport(path, body)

    client.request.side_effect = request
    status, error = run_move(client)
    assert error and "private" not in error
    if cleanup_fails:
        assert "cleanup is unconfirmed" in error
        assert status.profiles["0"].clients == ()
    else:
        assert "restored" in error
        assert state.records[0]["client_list"] == original
        assert all(c.device_id != DEVICE["device_id"] for c in status.profiles["1"].clients)


def test_restore_uses_original_record_when_inventory_disappears():
    client, state = firmware(records())
    transport = client.request.side_effect

    def request(path, body):
        state.acknowledgement = TimeoutError() if len(state.writes) == 1 and "operation=update" in body else True
        result = transport(path, body)
        if len(state.writes) >= 1:
            state.devices = []  # Recovery must not depend on historical inventory being present.
        return result

    client.request.side_effect = request
    status, error = run_move(client)
    assert "restored" in error
    assert status.profiles["0"].clients[0].device_id == DEVICE["device_id"]


def test_failed_original_restoration_reports_actual_unassigned_state_and_sanitizes_errors():
    client, state = firmware(records())
    transport = client.request.side_effect

    def request(path, body):
        step = len(state.writes) + 1
        is_write = path == PROFILE_LIST_PATH and "operation=update" in body
        state.apply = not is_write or step != 4
        state.acknowledgement = TimeoutError("private data") if is_write and step in (2, 4) else True
        return transport(path, body)

    client.request.side_effect = request
    status, error = run_move(client)
    assert "original assignment could not be confirmed" in error
    assert "private" not in error
    assert status.profiles["0"].clients == ()
    assert all(c.device_id != DEVICE["device_id"] for c in status.profiles["1"].clients)


def test_move_coordinator_holds_existing_lock_authenticates_once_and_publishes_actual_error_state():
    client, state = firmware(records())
    coord = coordinator(client)
    transport = client.request.side_effect

    def request(*args):
        assert coord._lock.locked()
        return transport(*args)

    client.request.side_effect = request
    asyncio.run(coord.change_device_profile(DEVICE["mac"], "0", "1"))
    client.authorize.assert_called_once()
    client.logout.assert_called_once()
    coord.async_request_refresh.assert_awaited_once()
    coord.async_update_listeners.assert_called_once()
    assert len(state.writes) == 2
    assert coord.parental_status.profiles["0"].clients == ()


def network_fixture():
    coord = coordinator()
    coord.network_updated_at = datetime.now().astimezone()
    coord.update_interval = timedelta(seconds=30)
    coord.parental_status = ParentalStatus(parse_profiles(records()))
    coord.status = SimpleNamespace(devices=[SimpleNamespace(
        macaddr=DEVICE["mac"], ipaddr="192.0.2.10", hostname="Current Wi-Fi",
        type=SimpleNamespace(get_type=lambda: "host", get_band=lambda: "2.4G"),
        active=True, packets_sent=5, packets_received=9, traffic_usage="123",
    ), SimpleNamespace(
        macaddr="AA:BB:CC:DD:EE:03", ipaddr="192.0.2.11", hostname="Current wired",
        type=SimpleNamespace(get_type=lambda: "wired", get_band=lambda: None), active=True,
    )])
    states = {"device_tracker.old": SimpleNamespace(
        state="home", attributes={"mac": "AA:BB:CC:DD:EE:04", "host_name": "Restored home", "connection": "guest"},
    )}
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coord}}, states=SimpleNamespace(get=states.get),
        config_entries=SimpleNamespace(async_get_entry=lambda key: SimpleNamespace(title="Synthetic router")),
    )
    entries = [SimpleNamespace(domain="device_tracker", unique_id="entry-1_old", entity_id="device_tracker.old")]
    return hass, coord, entries


def read_snapshot(hass, coord, entries):
    with patch("custom_components.tplink_router.network.entity_registry.async_get", return_value=Mock()), patch(
        "custom_components.tplink_router.network.entity_registry.async_entries_for_config_entry", return_value=entries,
    ):
        return snapshot(hass, coord)


def test_snapshot_online_is_authoritative_cached_home_never_online_and_no_sensitive_data():
    hass, coord, entries = network_fixture()
    data = read_snapshot(hass, coord, entries)
    devices = {d["mac"]: d for d in data["devices"]}
    assert devices["aa:bb:cc:dd:ee:01"]["online"]
    assert devices["aa:bb:cc:dd:ee:01"]["owners"] == ["0"]
    assert devices["aa:bb:cc:dd:ee:01"]["device_type"] == 1
    assert devices["aa:bb:cc:dd:ee:03"]["connection"] == "wired"
    assert devices["aa:bb:cc:dd:ee:04"]["cached"] and not devices["aa:bb:cc:dd:ee:04"]["online"]
    assert not devices["aa:bb:cc:dd:ee:02"]["online"]  # Profile member not in current connected list.
    assert data["profiles"][2]["members"] == []
    serialized = dumps(data)
    assert "private.example" not in serialized and "custom-filter" not in serialized and "opaque" not in serialized
    assert "packets_sent" in serialized and data["capabilities"]["reports"]
    assert data["capabilities"]["create_profile"]
    coord.router.request.assert_not_called()  # Capability flags never load reports or creation metadata.
    assert "unverified" in data["capabilities"]["telemetry_note"]


@pytest.mark.parametrize("failure", ["stale", "paused", "failed", "nostamp", "inactive"])
def test_snapshot_never_claims_online_for_stale_unavailable_paused_or_inactive(failure):
    hass, coord, entries = network_fixture()
    if failure == "stale":
        coord.network_updated_at -= timedelta(minutes=5)
    elif failure == "paused":
        coord.scan_stopped_at = datetime.now()
    elif failure == "failed":
        coord.last_update_success = False
    elif failure == "nostamp":
        coord.network_updated_at = None
    else:
        for device in coord.status.devices:
            device.active = False
    data = read_snapshot(hass, coord, entries)
    assert not any(d["online"] for d in data["devices"])


@pytest.mark.parametrize("status", [None, ParentalStatus(None), ParentalStatus({})])
def test_snapshot_unsupported_failure_and_valid_empty_are_distinct(status):
    hass, coord, entries = network_fixture()
    coord.parental_status = status
    data = read_snapshot(hass, coord, entries)
    assert data["profiles"] == []
    assert data["profiles_available"] is (status is not None and status.profiles is not None)
    assert data["memberships_available"] is data["profiles_available"]
    assert len(data["devices"]) == 3


def test_snapshot_invalid_assignment_is_unknown_not_confirmed_unassigned():
    hass, coord, entries = network_fixture()
    coord.parental_status = ParentalStatus(parse_profiles([
        {**FULL_RECORD, "client_list": {"invalid": True}},
    ]))
    data = read_snapshot(hass, coord, entries)
    assert data["profiles_available"] and not data["memberships_available"]
    assert not data["profiles"][0]["assignments_valid"]


@pytest.mark.parametrize("user_id,user", [
    ("normal", SimpleNamespace(is_active=True, is_admin=False)),
    ("inactive", SimpleNamespace(is_active=False, is_admin=True)),
])
def test_admin_guard_rejects_missing_inactive_and_nonadmin(user_id, user):
    hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=AsyncMock(return_value=user)))
    with pytest.raises(Unauthorized):
        asyncio.run(require_admin(hass, Context(user_id=user_id)))


def test_admin_guard_unknown_user_matches_homeassistant_service_error():
    hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=AsyncMock(return_value=None)))
    with pytest.raises(UnknownUser):
        asyncio.run(require_admin(hass, Context(user_id="removed")))


@pytest.mark.parametrize("context", [None, Context(), Context(parent_id="automation-run")])
def test_admin_guard_preserves_system_and_automation_context_without_fabricating_identity(context):
    hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=AsyncMock()))
    asyncio.run(require_admin(hass, context))
    hass.auth.async_get_user.assert_not_called()


@pytest.mark.parametrize("service", [
    "get_parental_devices", "assign_parental_device", "remove_parental_device",
    "set_parental_bedtime", "set_parental_daily_limit",
])
@pytest.mark.parametrize("user,error", [
    (SimpleNamespace(is_active=True, is_admin=False), Unauthorized),
    (SimpleNamespace(is_active=False, is_admin=True), Unauthorized),
    (None, UnknownUser),
])
def test_all_parental_actions_authorize_before_resolving_or_contacting_router(service, user, error):
    hass, registrations = service_hass()
    hass.auth.async_get_user.return_value = user
    register_parental_services(hass)
    with patch("custom_components.tplink_router.parental_services._resolve_profile") as resolve:
        with pytest.raises(error):
            asyncio.run(registrations[service][0](ServiceCall(
                hass, DOMAIN, service, {}, context=Context(user_id="non-admin", parent_id="automation-run"),
            )))
        resolve.assert_not_called()


@pytest.mark.parametrize("schedule", [True, False])
@pytest.mark.parametrize("user,error", [
    (SimpleNamespace(is_active=True, is_admin=False), Unauthorized),
    (SimpleNamespace(is_active=False, is_admin=True), Unauthorized),
    (None, UnknownUser),
])
def test_switches_cannot_bypass_parental_admin_enforcement(schedule, user, error):
    coord = coordinator()
    profile = parse_profiles([FULL_RECORD])["0"]
    entity = (
        TPLinkParentalScheduleSwitch(coord, profile, "enable_workday_time_limit")
        if schedule else TPLinkParentalAccessSwitch(coord, profile)
    )
    entity.hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=AsyncMock(
        return_value=user,
    )))
    entity.async_set_context(Context(user_id="not-admin"))
    coord.set_profile_schedule = AsyncMock()
    coord.set_profile_access = AsyncMock()
    for method in (entity.async_turn_on, entity.async_turn_off):
        with pytest.raises(error):
            asyncio.run(method())
    coord.set_profile_schedule.assert_not_called()
    coord.set_profile_access.assert_not_called()


@pytest.mark.parametrize("schedule", [True, False])
@pytest.mark.parametrize("parent_id", [None, "automation-run"])
def test_existing_switches_allow_system_and_automation_without_user_identity(schedule, parent_id):
    coord = coordinator()
    profile = parse_profiles([FULL_RECORD])["0"]
    entity = (
        TPLinkParentalScheduleSwitch(coord, profile, "enable_workday_time_limit")
        if schedule else TPLinkParentalAccessSwitch(coord, profile)
    )
    entity.hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=AsyncMock()))
    entity.async_set_context(Context(parent_id=parent_id))
    coord.set_profile_schedule = AsyncMock()
    coord.set_profile_access = AsyncMock()
    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_turn_off())
    entity.hass.auth.async_get_user.assert_not_called()
    if schedule:
        assert coord.set_profile_schedule.await_count == 2
        coord.set_profile_schedule.assert_awaited_with("0", "workday", "time_limit", enabled=False)
    else:
        assert coord.set_profile_access.await_count == 2
        coord.set_profile_access.assert_awaited_with("0", False)


@pytest.mark.parametrize("handler", [websocket_network, websocket_action])
@pytest.mark.parametrize("user", [None, SimpleNamespace(is_admin=False)])
def test_actual_websocket_wrappers_deny_nonadmins_before_scheduling(handler, user):
    hass = Mock()
    connection = SimpleNamespace(user=user)
    with pytest.raises(Unauthorized):
        handler(hass, connection, {"id": 1})
    hass.async_create_background_task.assert_not_called()


def test_websocket_schema_rejects_invalid_mac_unknown_fields_actions_and_schedules():
    base = {"id": 1, "type": "tplink_router/network_action", "entry_id": "entry-1", "action": "refresh"}
    assert websocket_action._ws_schema(base) == base
    for changes in ({"action": "delete"}, {"mac": "bad"}, {"kind": "guess"}, {"period": "holiday"}, {"token": "no"}):
        with pytest.raises(vol.Invalid):
            websocket_action._ws_schema({**base, **changes})


def test_websocket_dispatch_and_missing_fields_use_existing_coordinator_only():
    async def run():
        hass, coord, _ = network_fixture()
        connection = SimpleNamespace(user=SimpleNamespace(is_admin=True, is_active=True), send_result=Mock())
        coord.change_device_profile = AsyncMock()
        coord.set_profile_schedule = AsyncMock()
        coord.set_profile_access = AsyncMock()
        handler = websocket_action.__wrapped__.__wrapped__
        base = {"id": 1, "entry_id": "entry-1"}
        with patch("custom_components.tplink_router.network.snapshot", return_value={"safe": True}):
            for payload in (
                {"action": "refresh"},
                {"action": "change_profile", "mac": DEVICE["mac"], "expected_owner": "0", "destination": "1"},
                {"action": "schedule", "owner_id": "1", "period": "weekend", "kind": "time_limit", "minutes": 30},
                {"action": "access", "owner_id": "1", "enabled": False},
            ):
                await handler(hass, connection, {**base, **payload})
            with pytest.raises(HomeAssistantError, match="missing"):
                await handler(hass, connection, {**base, "action": "change_profile"})
            with pytest.raises(HomeAssistantError, match="no longer loaded"):
                await handler(hass, connection, {**base, "entry_id": "removed", "action": "refresh"})
        coord.async_request_refresh.assert_awaited_once()
        coord.change_device_profile.assert_awaited_once_with(DEVICE["mac"], "0", "1")
        coord.set_profile_schedule.assert_awaited_once_with("1", "weekend", "time_limit", minutes=30)
        coord.set_profile_access.assert_awaited_once_with("1", False)
        assert connection.send_result.call_count == 4
    asyncio.run(run())


@pytest.mark.parametrize("handler", [websocket_network, websocket_action])
def test_inactive_admin_websocket_is_rejected_inside_actual_async_handler(handler):
    with pytest.raises(Unauthorized):
        asyncio.run(handler.__wrapped__.__wrapped__(
            Mock(), SimpleNamespace(user=SimpleNamespace(is_active=False)), {},
        ))


def test_websocket_lists_multiple_routers_without_contacting_them():
    hass, coord, _ = network_fixture()
    hass.data[DOMAIN]["entry-2"] = coordinator()
    connection = SimpleNamespace(user=SimpleNamespace(is_active=True), send_result=Mock())
    asyncio.run(websocket_network.__wrapped__.__wrapped__(hass, connection, {"id": 9}))
    response = connection.send_result.call_args.args[1]
    assert [item["entry_id"] for item in response] == ["entry-1", "entry-2"]
    coord.router.request.assert_not_called()
    hass.data[DOMAIN]["entry-2"].router.request.assert_not_called()


def test_native_panel_concurrent_registration_unload_and_reload(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
        with patch("custom_components.tplink_router.network.websocket_api.async_register_command") as register:
            await asyncio.gather(setup_network_panel(hass), setup_network_panel(hass))
            panel = hass.data[frontend.DATA_PANELS][PANEL_PATH]
            assert panel.require_admin and panel.component_name == "custom"
            assert panel.config["_panel_custom"]["module_url"].startswith("/tplink_router_frontend/")
            assert register.call_count == 3
            hass.http.async_register_static_paths.assert_awaited_once()
            unload_network_panel(hass)
            assert PANEL_PATH not in hass.data[frontend.DATA_PANELS]
            await setup_network_panel(hass)
            assert PANEL_PATH in hass.data[frontend.DATA_PANELS]
            assert register.call_count == 3
            hass.http.async_register_static_paths.assert_awaited_once()
        await hass.async_stop(force=True)
    asyncio.run(run())


def batch_firmware():
    existing = {
        **DEVICE, "device_id": "existing", "mac": "AA:BB:CC:DD:EE:03",
        "name": "Stored synthetic name", "prio": "off", "prio_time": "0", "online": 0, "owner_id": 0,
    }
    return firmware([
        {**deepcopy(FULL_RECORD), "client_list": [existing]},
        {**deepcopy(FULL_RECORD), "owner_id": "1", "client_list": []},
    ])


def test_batch_assigns_with_one_native_update_retains_other_devices_and_protected_fields():
    client, state = batch_firmware()
    before = deepcopy(state.records)
    status, result = assign_profile_devices(client, LOGGER, "0", [DEVICE["mac"], SECOND_DEVICE["mac"]])
    assert result == {
        "confirmed": True, "error": None,
        "outcomes": [{"mac": d["mac"].lower(), "status": "assigned"} for d in (DEVICE, SECOND_DEVICE)],
    }
    assert len(state.writes) == 1 and len(status.profiles["0"].clients) == 3
    assert state.records[0]["client_list"][0] == before[0]["client_list"][0]
    assert state.records[1] == before[1]
    for field in ("categories_list", "internet_blocked", "opaque_setting", "workday_daily_time"):
        assert state.records[0][field] == before[0][field]
    from json import loads
    new = loads(state.writes[0]["new"])
    assert all(set(device) == set(DEVICE) for device in new["client_list"])
    assert new["client_list"][0]["name"] == before[0]["client_list"][0]["name"]


@pytest.mark.parametrize("failure", [
    "duplicate", "duplicate_normalized", "empty", "over32", "invalid", "removed", "already_assigned",
    "other_profile", "missing", "ambiguous_mac", "inventory_owner", "identity_collision", "capacity",
    "unknown_capacity", "incomplete", "invalid_filters",
])
def test_batch_preflight_all_or_nothing_without_writes(failure):
    client, state = batch_firmware()
    selected, target = [DEVICE["mac"], SECOND_DEVICE["mac"]], "0"
    if failure == "duplicate":
        selected = [DEVICE["mac"]] * 2
    elif failure == "duplicate_normalized":
        selected = [DEVICE["mac"], DEVICE["mac"].lower().replace(":", "-")]
    elif failure == "empty":
        selected = []
    elif failure == "over32":
        selected = [DEVICE["mac"]] * 33
    elif failure == "invalid":
        selected = ["bad"]
    elif failure == "removed":
        target = "removed"
    elif failure in ("already_assigned", "other_profile"):
        state.records[0 if failure == "already_assigned" else 1]["client_list"].append(DEVICE)
    elif failure == "missing":
        state.devices = [DEVICE]
    elif failure == "ambiguous_mac":
        state.devices[1]["mac"] = DEVICE["mac"]
    elif failure == "inventory_owner":
        state.devices[1]["owner_id"] = "1"
    elif failure == "identity_collision":
        state.records[0]["client_list"][0]["device_id"] = DEVICE["device_id"]
    elif failure == "capacity":
        state.limits = {"devices_len": 2}
    elif failure == "unknown_capacity":
        state.limits = {}
    elif failure == "incomplete":
        state.records[1]["client_list"] = None
    else:
        state.apps = None
    before = deepcopy(state.records)
    with pytest.raises((ParentalEditError, ValueError)):
        assign_profile_devices(client, LOGGER, target, selected)
    assert not state.writes and state.records == before


@pytest.mark.parametrize("failure", ["ignored", "partial", "readback", "ack", "priority", "other_profile"])
def test_batch_reports_per_device_actual_outcomes_without_retry_or_rollback(failure, caplog):
    client, state = batch_firmware()
    transport = client.request.side_effect
    if failure == "ignored":
        state.apply = False
    elif failure == "readback":
        state.fail_readback = True
    elif failure == "ack":
        state.acknowledgement = TimeoutError("sensitive raw data")

    def request(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            if failure == "partial":
                state.records[0]["client_list"] = [
                    c for c in state.records[0]["client_list"] if c["device_id"] != SECOND_DEVICE["device_id"]
                ]
            elif failure == "priority":
                state.records[0]["client_list"][0]["prio"] = "changed"
            elif failure == "other_profile":
                state.records[1]["internet_blocked"] = True
        return transport(path, body)

    client.request.side_effect = request
    status, result = assign_profile_devices(client, LOGGER, "0", [DEVICE["mac"], SECOND_DEVICE["mac"]])
    assert not result["confirmed"] and result["error"]
    outcomes = [item["status"] for item in result["outcomes"]]
    assert outcomes == {
        "ignored": ["not_assigned", "not_assigned"],
        "partial": ["assigned_unconfirmed", "not_assigned"],
        "readback": ["unknown", "unknown"],
        "ack": ["assigned_unconfirmed", "assigned_unconfirmed"],
        "priority": ["assigned_unconfirmed", "assigned_unconfirmed"],
        "other_profile": ["assigned_unconfirmed", "assigned_unconfirmed"],
    }[failure]
    assert len(state.writes) == 1
    if failure in ("ignored", "partial"):
        expected_presence = [False, False] if failure == "ignored" else [True, False]
        assert f"'requested_assignment_presence': {expected_presence}" in caplog.text
    assert (status.profiles is None) is (failure == "readback")
    for private in (DEVICE["mac"], DEVICE["name"], "sensitive raw data", "private.example"):
        assert private not in caplog.text


def test_batch_coordinator_serializes_one_auth_session_with_polling_and_publishes_actual_partial_result():
    client, state = batch_firmware()
    coord = coordinator(client)
    transport = client.request.side_effect

    def serialized(*args):
        assert coord._lock.locked()
        return transport(*args)

    client.request.side_effect = serialized
    result = asyncio.run(coord.assign_profile_devices("0", [DEVICE["mac"], SECOND_DEVICE["mac"]]))
    assert result["confirmed"] and len(state.writes) == 1
    client.authorize.assert_called_once()
    client.logout.assert_called_once()
    coord.async_request_refresh.assert_awaited_once()
    coord.async_update_listeners.assert_called_once()
    assert len(coord.parental_status.profiles["0"].clients) == 3


def test_batch_websocket_schema_and_admin_boundary():
    base = {"id": 1, "type": "tplink_router/network_action", "entry_id": "entry-1",
            "action": "assign_devices", "macs": [DEVICE["mac"]], "destination": "0"}
    assert websocket_action._ws_schema(base) == base
    for macs in ([], ["bad"], [DEVICE["mac"]] * 33, DEVICE["mac"]):
        with pytest.raises(vol.Invalid):
            websocket_action._ws_schema({**base, "macs": macs})
    for user in (None, SimpleNamespace(is_admin=False)):
        with pytest.raises(Unauthorized):
            websocket_action(Mock(), SimpleNamespace(user=user), base)


@pytest.mark.parametrize("failure", [None, "stale", "paused", "unavailable", "memberships", "missing"])
def test_batch_websocket_enforces_freshness_and_returns_outcomes(failure):
    async def run():
        hass, coord, entries = network_fixture()
        connection = SimpleNamespace(user=SimpleNamespace(is_active=True), send_result=Mock())
        result = {
            "confirmed": False, "error": "Not confirmed",
            "outcomes": [{"mac": DEVICE["mac"], "status": "unknown"}],
        }
        coord.assign_profile_devices = AsyncMock(return_value=result)
        current = read_snapshot(hass, coord, entries)
        if failure is not None and failure != "missing":
            current[{"unavailable": "available", "memberships": "memberships_available"}.get(failure, failure)] = (
                False if failure in ("unavailable", "memberships") else True
            )
        msg = {"id": 1, "entry_id": "entry-1", "action": "assign_devices",
               "macs": [DEVICE["mac"]], "destination": "0"}
        if failure == "missing":
            del msg["destination"]
        with patch("custom_components.tplink_router.network.snapshot", return_value=current):
            if failure:
                with pytest.raises(HomeAssistantError):
                    await websocket_action.__wrapped__.__wrapped__(hass, connection, msg)
                coord.assign_profile_devices.assert_not_called()
            else:
                await websocket_action.__wrapped__.__wrapped__(hass, connection, msg)
                coord.assign_profile_devices.assert_awaited_once_with("0", [DEVICE["mac"]])
                assert connection.send_result.call_args.args[1]["assignment_result"] == result
    asyncio.run(run())
