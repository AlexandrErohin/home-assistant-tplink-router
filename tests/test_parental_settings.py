import asyncio
import base64
from copy import deepcopy
from json import dumps, loads
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs

import pytest
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import load_yaml
import voluptuous as vol
from tplinkrouterc6u.client.c6u import TplinkEncryption, TplinkRequest

from custom_components.tplink_router import async_unload_entry, register_services
from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.parental_control import (
    PERIODS, SCHEDULE_FLAGS, PROFILE_APPS_PATH, PROFILE_DEVICES_PATH, PROFILE_LIMIT_PATH,
    PROFILE_LIST_PATH, ParentalEditError, ParentalStatus, edit_profile, parse_devices,
    parse_profiles, schedule_changes,
)
from custom_components.tplink_router.parental_services import (
    PARENTAL_SERVICES, _resolve_profile, register_parental_services,
)
from custom_components.tplink_router.switch import (
    TPLinkParentalAccessSwitch, TPLinkParentalScheduleSwitch, setup_parental_entities,
)
from test_parental_control import LOGGER, RECORD, coordinator, router


DEVICE = {"device_id": "device &+1", "name": "Example tablet", "mac": "AA:BB:CC:DD:EE:01", "client_type": 1}
SECOND_DEVICE = {**DEVICE, "device_id": "other", "mac": "AA:BB:CC:DD:EE:02"}
FULL_RECORD = {
    **RECORD, "name": "Profile & + name", "filter_level": "child", "client_list": [],
    "website_list": ["private.example", "Application"], "categories_list": ["custom-filter"],
    "opaque_setting": {"retain": ["exactly"]}, "limit": 110,
    "time_limit": {"is_pro": False}, "bedtime": {"is_pro": False},
    **{flag: False for flag in SCHEDULE_FLAGS},
    **{f"{period}_daily_time": "120" for period in PERIODS},
    **{f"{period}_bed_time_begin": 1320 for period in PERIODS},
    **{f"{period}_bed_time_end": 420 for period in PERIODS},
}


def firmware(records=None):
    client = router()
    state = SimpleNamespace(
        records=deepcopy(records if records is not None else [FULL_RECORD]),
        devices=deepcopy([DEVICE, SECOND_DEVICE]), limits={"devices_len": 16},
        apps=[{"name": "Application", "app_id": "app&1"}],
        writes=[], acknowledgement=True, apply=True, fail_readback=False,
    )
    metadata = {
        str(device["device_id"]): deepcopy(device)
        for record in state.records
        if isinstance(record.get("client_list"), list)
        for device in record["client_list"] if isinstance(device, dict)
    }

    def request(path, body):
        assert client._logger is None
        fields = {key: values[0] for key, values in parse_qs(body).items()}
        if path == PROFILE_LIST_PATH:
            if fields["operation"] == "load":
                if state.writes and state.fail_readback:
                    raise TimeoutError("private profile data")
                return deepcopy(state.records)
            assert fields["operation"] == "update"
            assert client._data_block == "success"
            state.writes.append(fields)
            index = int(fields["index"])
            updated = loads(fields["new"])
            assert updated["owner_id"] == state.records[index]["owner_id"]
            if state.apply:
                updated["client_list"] = [
                    {**metadata.get(str(device["device_id"]), {}), **device}
                    for device in updated["client_list"]
                ]
                for device in updated["client_list"]:
                    if "owner_id" in device:
                        device["owner_id"] = (
                            int(updated["owner_id"]) if updated["owner_id"].isdigit() else updated["owner_id"]
                        )
                    metadata[str(device["device_id"])] = deepcopy(device)
                state.records[index] = {**state.records[index], **updated}
            if isinstance(state.acknowledgement, Exception):
                raise state.acknowledgement
            return state.acknowledgement
        if path == PROFILE_APPS_PATH:
            assert fields == {"operation": "read"}
            return deepcopy(state.apps)
        if path == PROFILE_DEVICES_PATH:
            assert fields == {"operation": "load"}
            return deepcopy(state.devices)
        if path == PROFILE_LIMIT_PATH:
            assert fields == {"operation": "read"}
            return deepcopy(state.limits)
        pytest.fail(f"Unexpected endpoint {path}")

    client.request.side_effect = request
    return client, state


def test_optional_settings_and_devices_parse_without_exposing_filters():
    profile = parse_profiles([FULL_RECORD])["0"]
    assert profile.settings["workday_daily_time"] == 120
    assert profile.settings["weekend_bed_time_end"] == 420
    assert profile.clients == ()
    assert not hasattr(profile, "website_list")
    assert not hasattr(profile, "opaque_setting")
    record = {**FULL_RECORD, "client_list": [DEVICE]}
    device = parse_profiles([record])["0"].clients[0]
    assert device.device_id == DEVICE["device_id"]
    assert device.client_type == 1


@pytest.mark.parametrize("value", [None, "true", 1, {}, []])
def test_invalid_optional_flag_does_not_disable_pause(value):
    parsed = parse_profiles([{**FULL_RECORD, "enable_workday_bed_time": value}])["0"]
    assert not parsed.internet_blocked
    assert "enable_workday_bed_time" not in parsed.settings
    assert "enable_workday_time_limit" in parsed.settings


@pytest.mark.parametrize("key,value", [
    ("workday_daily_time", "bad"), ("workday_daily_time", True), ("workday_daily_time", 0),
    ("workday_daily_time", 100), ("workday_bed_time_begin", 1440),
    ("weekend_bed_time_end", -1), ("workday_bed_time_begin", None),
])
def test_invalid_optional_time_is_unavailable_not_defaulted(key, value):
    record = {**FULL_RECORD, key: value}
    if key.endswith("_daily_time"):
        record["enable_workday_time_limit"] = True
    parsed = parse_profiles([record])["0"]
    assert key not in parsed.settings
    assert not parsed.internet_blocked


@pytest.mark.parametrize("key,value", [
    ("time_limit", {"is_pro": True}), ("time_limit", None),
    ("time_limit", {"is_pro": "false"}), ("bedtime", {"is_pro": True}),
])
def test_pro_or_invalid_metadata_hides_only_affected_schedules(key, value):
    parsed = parse_profiles([{**FULL_RECORD, key: value}])["0"]
    kind = "time_limit" if key == "time_limit" else "bed_time"
    assert all(f"enable_{period}_{kind}" not in parsed.settings for period in PERIODS)
    assert len(parsed.settings) > 0


@pytest.mark.parametrize("data", [
    None, {"unexpected": True}, [None], [DEVICE, DEVICE], [{**DEVICE, "device_id": ""}],
    [{**DEVICE, "mac": "invalid"}], [{**DEVICE, "owner_id": None}],
    [{**DEVICE, "client_type": True}], [{**DEVICE, "device_id": False}],
    [{**DEVICE, "name": None}],
])
def test_device_validation_fails_explicitly_without_breaking_pause(data):
    with pytest.raises(ValueError):
        parse_devices(data)
    profile = parse_profiles([{**FULL_RECORD, "client_list": data}])["0"]
    assert profile.clients is None
    assert profile.internet_blocked is False


def test_device_identifiers_follow_ui_string_conversion():
    parsed = parse_devices([{**DEVICE, "device_id": 7, "owner_id": 0}])[0]
    assert parsed.device_id == "7"
    assert parsed.owner_id == "0"


def observed_record(**changes):
    """Synthetic values with the exact read-only AX50 field representations."""
    record = {
        **FULL_RECORD, "key": "key-0", "client_list": {}, "website_list": {}, "categories_list": {},
        "workday_daily_time": "0", "weekend_daily_time": "0",
        "workday_bed_time_begin": "1260", "workday_bed_time_end": "420",
        "weekend_bed_time_begin": "1320", "weekend_bed_time_end": "420",
    }
    record.pop("time_limit")
    record.pop("bedtime")
    record.update(changes)
    return record


def test_observed_disabled_zero_budget_and_empty_luci_arrays_expose_all_controls():
    record = observed_record()
    parsed = parse_profiles([record])["0"]
    assert parsed.clients == ()
    assert len(parsed.settings) == 10
    assert parsed.settings["workday_daily_time"] == 0
    assert parsed.settings["enable_workday_time_limit"] is False
    assert parsed.settings["workday_bed_time_begin"] == 1260
    assert parse_devices({}) == ()
    coord = coordinator()
    coord.parental_status = ParentalStatus({"0": parsed})
    added = []
    setup_parental_entities(coord, Mock(), lambda entities, update: added.extend(entities))
    assert len(added) == 5
    assert all(entity.available for entity in added)
    assert sum(entity.is_on is False for entity in added) == 4


@pytest.mark.parametrize("enabled", [True, False])
def test_observed_zero_budget_is_only_a_disabled_sentinel(enabled):
    parsed = parse_profiles([observed_record(enable_workday_time_limit=enabled)])["0"]
    assert ("workday_daily_time" in parsed.settings) is not enabled
    assert "weekend_daily_time" in parsed.settings
    coord = coordinator()
    with pytest.raises(HomeAssistantError):
        asyncio.run(coord.set_profile_schedule("0", "workday", "time_limit", minutes=0, enabled=False))
    coord.router.request.assert_not_called()


def test_enabling_observed_unset_budget_needs_explicit_positive_budget():
    client, state = firmware([observed_record()])
    with pytest.raises(ParentalEditError, match="before enabling"):
        edit_profile(client, LOGGER, "0", changes={"enable_workday_time_limit": True})
    assert not state.writes
    _, error = edit_profile(client, LOGGER, "0", changes={
        "enable_workday_time_limit": True, "workday_daily_time": 180,
    })
    assert error is None
    written = loads(state.writes[0]["new"])
    assert written["workday_daily_time"] == "180" and written["enable_workday_time_limit"] is True
    assert "weekend_daily_time" not in written and written["enable_weekend_time_limit"] is False
    assert written["website_list"] == written["categories_list"] == written["client_list"] == []
    assert loads(state.writes[0]["old"]) == observed_record()


def test_observed_empty_profile_can_assign_then_remove_without_guessing_capacity():
    client, state = firmware([observed_record()])
    state.limits = {"profile_len": 16, "devices_len": 32, "category_len": 32}
    state.apps = [{"app_id": 123, "name": "Synthetic application"}]
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None
    assert state.records[0]["client_list"] == [DEVICE]
    assert state.records[0]["workday_daily_time"] == "0"
    _, error = edit_profile(client, LOGGER, "0", remove_device=DEVICE["device_id"])
    assert error is None and state.records[0]["client_list"] == []
    assert not state.records[0]["enable_workday_time_limit"]


def test_bedtime_edit_preserves_observed_disabled_daily_sentinels_and_unknown_device_fields():
    device = {
        **DEVICE, "client_type": "laptop", "owner_id": 0, "prio": "off",
        "prio_time": "0", "time_period": "0", "online": 1,
    }
    client, state = firmware([observed_record(client_list=[device], categories_list=["synthetic-category"])])
    _, error = edit_profile(client, LOGGER, "0", changes={"enable_workday_bed_time": True})
    assert error is None
    written = loads(state.writes[0]["new"])
    assert "workday_daily_time" not in written and "weekend_daily_time" not in written
    assert written["client_list"] == [{key: device[key] for key in DEVICE}]
    assert state.records[0]["client_list"] == [device]
    assert state.records[0]["workday_daily_time"] == state.records[0]["weekend_daily_time"] == "0"
    assert written["categories_list"] == ["synthetic-category"]
    assert written["workday_bed_time_begin"] == 1260
    assert written["weekend_bed_time_begin"] == 1320


def test_native_store_excludes_insights_and_encodes_clocks_without_dropping_protected_data():
    existing = {
        **SECOND_DEVICE, "client_type": "laptop", "owner_id": 0, "prio": "off",
        "prio_time": "0", "time_period": "0", "online": 1,
        "opaque_device_setting": {"keep": True},
    }
    original = observed_record(client_list=[existing], insights="synthetic-read-only-value")
    client, state = firmware([original])
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None
    assert len(state.writes) == 1
    old, new = (loads(state.writes[0][key]) for key in ("old", "new"))
    assert old == {key: value for key, value in original.items() if key != "insights"}
    assert "insights" not in new
    assert new["client_list"] == [{key: existing[key] for key in DEVICE}, DEVICE]
    assert state.records[0]["client_list"] == [existing, DEVICE]
    assert new["opaque_setting"] == original["opaque_setting"]
    for period in PERIODS:
        assert f"{period}_daily_time" not in new
        assert state.records[0][f"{period}_daily_time"] == "0"
        assert new[f"enable_{period}_time_limit"] is False
        assert new[f"enable_{period}_bed_time"] == original[f"enable_{period}_bed_time"]
        for endpoint in ("begin", "end"):
            key = f"{period}_bed_time_{endpoint}"
            assert new[key] == int(original[key])
            assert type(new[key]) is int
    assert original["workday_bed_time_begin"] == "1260"
    assert original["insights"] == "synthetic-read-only-value"


def test_native_serialization_never_treats_an_ignored_assignment_as_success(caplog):
    client, state = firmware([observed_record(insights="synthetic-read-only-value")])
    state.apply = False
    with caplog.at_level("WARNING"):
        status, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert status.profiles["0"].clients == ()
    assert "assignment is absent" in error
    assert len(state.writes) == 1
    assert "synthetic-read-only-value" not in caplog.text
    assert "'requested_assignment_present': False" in caplog.text


@pytest.mark.parametrize("enabled,budget,omitted", [
    (False, "0", True), (False, "120", False), (True, "120", False), (False, 0, False),
])
def test_native_budget_omission_is_restricted_to_observed_disabled_string_zero(enabled, budget, omitted):
    client, state = firmware([observed_record(
        enable_workday_time_limit=enabled, workday_daily_time=budget,
    )])
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None
    written = loads(state.writes[0]["new"])
    assert ("workday_daily_time" not in written) is omitted
    assert state.records[0]["workday_daily_time"] == budget


def test_observed_native_write_boundary_projects_only_new_clients_and_retains_old_metadata():
    existing = {
        **SECOND_DEVICE, "name": "Stored name retained", "owner_id": 0, "online": 0,
        "prio": "off", "prio_time": "0", "time_period": "0",
    }
    client, state = firmware([observed_record(client_list=[existing], insights="not writable")])
    state.devices[1]["name"] = "New inventory name not copied"
    transport = client.request.side_effect

    def native_boundary(path, body):
        if path == PROFILE_LIST_PATH and "operation=update" in body:
            data = {k: v[0] for k, v in parse_qs(body).items()}
            old, new = loads(data["old"]), loads(data["new"])
            assert old["client_list"] == [existing]
            assert all(set(c) == set(DEVICE) for c in new["client_list"])
            assert "insights" not in old and "insights" not in new
            assert new["client_list"][0]["name"] == existing["name"]
            assert "workday_daily_time" not in new
        return transport(path, body)

    client.request.side_effect = native_boundary
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None and len(state.writes) == 1
    assert state.records[0]["client_list"][0] == existing


@pytest.mark.parametrize("change", ["prio", "prio_time", "time_period", "opaque", "budget", "online", "owner"])
def test_native_regenerated_metadata_only_relaxes_observed_runtime_fields(change, caplog):
    existing = {**SECOND_DEVICE, "prio": "off", "prio_time": "0", "time_period": "0",
                "online": 0, "owner_id": 0, "opaque": {"retained": True}}
    client, state = firmware([observed_record(client_list=[existing])])
    transport = client.request.side_effect

    def readback(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            if change == "budget":
                state.records[0]["workday_daily_time"] = "120"
            else:
                field = "owner_id" if change == "owner" else change
                state.records[0]["client_list"][0][field] = 1 if change in ("online", "owner") else "changed"
        return transport(path, body)

    client.request.side_effect = readback
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert (error is None) is (change in ("online", "owner"))
    assert len(state.writes) == 1
    assert "retained" not in caplog.text


@pytest.mark.parametrize("field", ["website_list", "categories_list", "client_list"])
def test_nonempty_objects_are_not_treated_as_empty_arrays(field):
    client, state = firmware([observed_record(**{field: {"unexpected": "opaque"}})])
    with pytest.raises(ParentalEditError):
        edit_profile(client, LOGGER, "0", changes={"enable_workday_bed_time": True})
    assert not state.writes


@pytest.mark.parametrize("period", PERIODS)
def test_clock_conversion_and_daily_units(period):
    assert schedule_changes(period, "bed_time", enabled=True, begin="22:00:00", end="07:00") == {
        f"enable_{period}_bed_time": True,
        f"{period}_bed_time_begin": 1320, f"{period}_bed_time_end": 420,
    }
    assert schedule_changes(period, "time_limit", minutes=960.0) == {f"{period}_daily_time": 960}
    assert schedule_changes(period, "time_limit", enabled=False) == {f"enable_{period}_time_limit": False}
    assert schedule_changes(period, "bed_time", begin="00:00") == {f"{period}_bed_time_begin": 0}
    assert schedule_changes(period, "bed_time", end="23:59") == {f"{period}_bed_time_end": 1439}


@pytest.mark.parametrize("period,kind,values", [
    ("other", "time_limit", {"minutes": 60}), ("workday", "other", {"enabled": True}),
    ("workday", "time_limit", {}), ("workday", "bed_time", {"enabled": "true"}),
    ("workday", "time_limit", {"minutes": 14}), ("workday", "time_limit", {"minutes": 961}),
    ("workday", "time_limit", {"minutes": 16}), ("workday", "time_limit", {"minutes": 120.5}),
    ("workday", "time_limit", {"minutes": True}), ("workday", "time_limit", {"begin": "22:00"}),
    ("workday", "bed_time", {"minutes": 60}), ("workday", "bed_time", {"begin": "24:00"}),
    ("workday", "bed_time", {"begin": "9:30"}), ("workday", "bed_time", {"end": "07:00:01"}),
    ("workday", "bed_time", {"begin": "22:00Z"}), ("workday", "bed_time", {"begin": 1320}),
])
def test_invalid_schedule_input_rejected_before_io(period, kind, values):
    coord = coordinator()
    with pytest.raises(HomeAssistantError):
        asyncio.run(coord.set_profile_schedule("0", period, kind, **values))
    coord.router.request.assert_not_called()


def test_full_profile_update_matches_store_protocol_and_preserves_every_other_field():
    second = {**FULL_RECORD, "owner_id": "other", "internet_blocked": True}
    client, state = firmware([second, FULL_RECORD])
    before = deepcopy(state.records)
    status, error = edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
    assert error is None
    assert status.profiles["0"].settings["workday_daily_time"] == 180
    assert len(state.writes) == 1
    payload = state.writes[0]
    assert payload["operation"] == "update" and payload["index"] == "1"
    assert payload["key"] == "key-1"
    assert loads(payload["old"]) == {**before[1], "key": "key-1"}
    expected = {
        **before[1], "workday_daily_time": "180", "key": "key-1",
        "website_list": ["private.example"], "app_list": ["app&1"],
    }
    assert loads(payload["new"]) == expected
    assert state.records[0] == before[0]
    assert client._logger is LOGGER and client._data_block == "data"


def test_existing_app_ids_and_custom_row_key_are_preserved():
    client, state = firmware([{**FULL_RECORD, "key": "custom & key", "app_list": ["retained-app"]}])
    _, error = edit_profile(client, LOGGER, "0", changes={"enable_weekend_time_limit": True})
    assert error is None
    updated = loads(state.writes[0]["new"])
    assert updated["app_list"] == ["retained-app", "app&1"]
    assert state.writes[0]["key"] == "custom & key"


@pytest.mark.parametrize("metadata", [None, {}, [{"name": "Application"}], [
    {"name": "Application", "app_id": "one"}, {"name": "Application", "app_id": "two"},
]])
def test_missing_or_invalid_app_metadata_never_sends_edit(metadata):
    client, state = firmware()
    state.apps = metadata
    with pytest.raises(ParentalEditError, match="metadata"):
        edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
    assert not state.writes


@pytest.mark.parametrize("field,value", [("website_list", None), ("categories_list", None), ("app_list", {})])
def test_incomplete_filter_data_is_not_overwritten(field, value):
    client, state = firmware([{**FULL_RECORD, field: value}])
    with pytest.raises(ParentalEditError):
        edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
    assert not state.writes


@pytest.mark.parametrize("changes", [
    {"name": "renamed"}, {}, {"workday_daily_time": 16}, {"enable_workday_time_limit": "false"},
])
def test_edit_guard_rejects_unscoped_or_invalid_fields(changes):
    client, state = firmware()
    with pytest.raises(ValueError):
        edit_profile(client, LOGGER, "0", changes=changes)
    assert not state.writes


def test_pro_schedule_edits_blocked_but_assignment_preserves_pro_data():
    pro = {**FULL_RECORD, "time_limit": {"is_pro": True, "custom": {"days": [1, 4]}}}
    client, state = firmware([pro])
    with pytest.raises(ParentalEditError, match="Pro"):
        edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
    assert not state.writes
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None
    assert state.records[0]["time_limit"] == pro["time_limit"]


@pytest.mark.parametrize("changes", [
    {"workday_bed_time_begin": 420}, {"workday_bed_time_begin": 0, "workday_bed_time_end": 0},
])
def test_equal_bedtimes_rejected_without_guessing_router_semantics(changes):
    client, state = firmware()
    with pytest.raises(ParentalEditError, match="must differ"):
        edit_profile(client, LOGGER, "0", changes=changes)
    assert not state.writes


def test_enabling_equal_bedtime_rejected_but_disabling_permitted():
    client, state = firmware([{
        **FULL_RECORD, "workday_bed_time_begin": 0, "workday_bed_time_end": 0,
        "enable_workday_bed_time": True,
    }])
    with pytest.raises(ParentalEditError):
        edit_profile(client, LOGGER, "0", changes={"enable_workday_bed_time": True})
    _, error = edit_profile(client, LOGGER, "0", changes={"enable_workday_bed_time": False})
    assert error is None


def test_assignment_removal_and_noops_preserve_all_other_devices_and_settings():
    existing = {**SECOND_DEVICE, "opaque_device_setting": {"keep": True}}
    client, state = firmware([{**FULL_RECORD, "client_list": [existing]}])
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None
    assert state.records[0]["client_list"] == [existing, DEVICE]
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None and len(state.writes) == 1
    _, error = edit_profile(client, LOGGER, "0", remove_device=DEVICE["device_id"])
    assert error is None and state.records[0]["client_list"] == [existing]
    edit_profile(client, LOGGER, "0", remove_device="not-assigned")
    assert len(state.writes) == 2
    assert state.records[0]["workday_daily_time"] == "120"
    assert state.records[0]["internet_blocked"] is False


def test_offline_already_assigned_device_is_a_noop_without_inventory_or_metadata():
    client, state = firmware([{**FULL_RECORD, "client_list": [DEVICE]}])
    state.devices = None
    state.apps = None
    status, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert error is None and status.profiles["0"].clients[0].device_id == DEVICE["device_id"]
    assert not state.writes
    client.request.assert_called_once_with(PROFILE_LIST_PATH, "operation=load")


@pytest.mark.parametrize("conflict", ["inventory", "profiles", "malformed"])
def test_cross_profile_assignments_are_rejected_without_touching_either_profile(conflict):
    other = {**FULL_RECORD, "owner_id": "other"}
    if conflict == "profiles":
        other["client_list"] = [DEVICE]
    elif conflict == "malformed":
        other["client_list"] = None
    client, state = firmware([FULL_RECORD, other])
    if conflict == "inventory":
        state.devices[0]["owner_id"] = "other"
    before = deepcopy(state.records)
    with pytest.raises(ParentalEditError, match="another profile"):
        edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert not state.writes and state.records == before


@pytest.mark.parametrize("limits", [None, {}, {"devices_len": None}, {"devices_len": True}, {"devices_len": 0}])
def test_unknown_capacity_never_defaults_or_writes(limits):
    client, state = firmware()
    state.limits = limits
    with pytest.raises(ParentalEditError, match="limit is unavailable"):
        edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert not state.writes


def test_router_capacity_enforced_but_does_not_block_removal():
    client, state = firmware([{**FULL_RECORD, "client_list": [SECOND_DEVICE]}])
    state.limits = {"devices_len": "1"}
    with pytest.raises(ParentalEditError, match="reached"):
        edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    _, error = edit_profile(client, LOGGER, "0", remove_device=SECOND_DEVICE["device_id"])
    assert error is None


@pytest.mark.parametrize("operation", [{"add_device": "missing"}, {"remove_device": ""}, {
    "changes": {"workday_daily_time": 180}, "add_device": "x",
}])
def test_missing_device_and_ambiguous_edits_do_not_write(operation):
    client, state = firmware()
    with pytest.raises(ParentalEditError):
        edit_profile(client, LOGGER, "0", **operation)
    assert not state.writes


def test_failed_ack_still_reads_applied_state_and_restores_transport_fields(caplog):
    client, state = firmware()
    state.acknowledgement = RuntimeError("private filters")
    status, error = edit_profile(client, LOGGER, "0", changes={"enable_workday_bed_time": True})
    assert "acknowledgement failed" in error
    assert status.profiles["0"].settings["enable_workday_bed_time"] is True
    assert "private filters" not in caplog.text
    assert client._data_block == "data" and client._logger is LOGGER


@pytest.mark.parametrize("key,value", [
    ("categories_list", ["changed-filter"]), ("client_list", [SECOND_DEVICE]),
    ("internet_blocked", True), ("website_list", None),
])
def test_unrelated_readback_changes_are_errors_but_actual_access_state_is_retained(key, value):
    client, state = firmware()
    request = client.request.side_effect

    def unexpected_change(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            state.records[0][key] = deepcopy(value)
        return request(path, body)

    client.request.side_effect = unexpected_change
    status, error = edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
    assert "mismatch" in error
    assert status.profiles["0"].internet_blocked is (value if key == "internet_blocked" else False)


def test_malformed_assigned_device_data_blocks_schedule_writes_too():
    client, state = firmware([{**FULL_RECORD, "client_list": None}])
    with pytest.raises(ParentalEditError, match="Assigned device list is invalid"):
        edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
    assert not state.writes


@pytest.mark.parametrize("failure", ["mismatch", "readback", "missing-profile"])
def test_unconfirmed_writes_surface_errors_not_success(failure):
    client, state = firmware()
    if failure == "mismatch":
        state.apply = False
    elif failure == "readback":
        state.fail_readback = True
    else:
        state.records = []
    if failure == "missing-profile":
        with pytest.raises(ParentalEditError, match="no longer exists"):
            edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
        assert not state.writes
    else:
        status, error = edit_profile(client, LOGGER, "0", changes={"workday_daily_time": 180})
        assert error is not None
        assert (status.profiles is None) is (failure == "readback")


def assert_private_values_absent(caplog, error):
    output = caplog.text + (error or "")
    for value in (DEVICE["device_id"], DEVICE["name"], DEVICE["mac"], FULL_RECORD["name"], "private.example",
                  "custom-filter", "opaque_setting"):
        assert value not in output


def test_ignored_assignment_reports_actual_unassigned_not_success_and_no_retry(caplog):
    client, state = firmware()
    state.apply = False
    status, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert status.profiles["0"].clients == ()
    assert "assignment is absent" in error and "device is unassigned" in error
    assert "No automatic retry" in error
    assert len(state.writes) == 1
    assert "'requested_assignment_present': False" in caplog.text
    assert "'expected_client_count': 1" in caplog.text
    assert "'actual_client_count': 0" in caplog.text
    assert "client_list:list->list" in caplog.text
    assert_private_values_absent(caplog, error)


@pytest.mark.parametrize("change", ["name", "client_type", "schedule", "filters"])
def test_applied_assignment_with_other_mismatch_remains_failure_but_reports_present(change, caplog):
    client, state = firmware()
    transport = client.request.side_effect

    def request(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            if change in ("name", "client_type"):
                state.records[0]["client_list"][0][change] = "changed"
            elif change == "schedule":
                state.records[0]["workday_daily_time"] = "180"
            else:
                state.records[0]["categories_list"] = ["changed-filter"]
        return transport(path, body)

    client.request.side_effect = request
    status, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert len(status.profiles["0"].clients) == 1
    assert "device is assigned to the destination" in error and "Do not retry" in error
    assert "'requested_assignment_present': True" in caplog.text
    assert len(state.writes) == 1
    assert_private_values_absent(caplog, error)
    assert "changed-filter" not in caplog.text


@pytest.mark.parametrize("field,value", [("device_id", "normalized-id"), ("mac", SECOND_DEVICE["mac"])])
def test_identity_mismatch_is_not_assumed_firmware_normalization(field, value, caplog):
    client, state = firmware()
    transport = client.request.side_effect

    def request(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            state.records[0]["client_list"][0][field] = value
        return transport(path, body)

    client.request.side_effect = request
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert "assignment is absent" in error
    assert "'requested_assignment_present': False" in caplog.text
    assert len(state.writes) == 1
    assert_private_values_absent(caplog, error)


def test_ignored_removal_reports_still_assigned_without_retry(caplog):
    client, state = firmware([{**FULL_RECORD, "client_list": [DEVICE]}])
    state.apply = False
    status, error = edit_profile(client, LOGGER, "0", remove_device=DEVICE["device_id"])
    assert len(status.profiles["0"].clients) == 1
    assert "still assigned to the original profile" in error
    assert "'removed_assignment_still_present': True" in caplog.text
    assert len(state.writes) == 1
    assert_private_values_absent(caplog, error)


def test_invalid_readback_diagnostics_never_claim_success_or_unassigned(caplog):
    client, state = firmware()
    transport = client.request.side_effect

    def request(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            state.records[0]["client_list"] = {"private.example": DEVICE["mac"]}
        return transport(path, body)

    client.request.side_effect = request
    status, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert status.profiles["0"].clients is None
    assert "mismatch" in error and "device is unassigned" not in error
    assert "'membership_readback_valid': False" in caplog.text
    assert "profile_shape" in caplog.text
    assert_private_values_absent(caplog, error)


def test_disabled_zero_representation_mismatch_remains_strict_with_type_diagnostics(caplog):
    client, state = firmware([observed_record()])
    transport = client.request.side_effect

    def request(path, body):
        if path == PROFILE_LIST_PATH and body == "operation=load" and state.writes:
            state.records[0]["workday_daily_time"] = 0
        return transport(path, body)

    client.request.side_effect = request
    _, error = edit_profile(client, LOGGER, "0", add_device=DEVICE["device_id"])
    assert "mismatch" in error
    assert "workday_daily_time:str->int" in caplog.text
    assert "'requested_assignment_present': True" in caplog.text
    assert_private_values_absent(caplog, error)


def test_coordinator_uses_fresh_read_one_authenticated_session_and_lock_when_polling_paused():
    client, state = firmware()
    coord = coordinator(client)
    coord.scan_stopped_at = object()
    coord.parental_status = ParentalStatus(parse_profiles([FULL_RECORD]))
    state.records[0]["name"] = "Fresh external rename"
    state.records[0]["client_list"] = [SECOND_DEVICE]
    request = client.request.side_effect

    def serialized(*args):
        assert coord._lock.locked()
        return request(*args)

    client.request.side_effect = serialized
    asyncio.run(coord.set_profile_schedule("0", "weekend", "bed_time", enabled=True, begin="23:00", end="08:00"))
    assert loads(state.writes[0]["new"])["name"] == "Fresh external rename"
    assert loads(state.writes[0]["new"])["client_list"] == [SECOND_DEVICE]
    assert coord.parental_status.profiles["0"].settings["weekend_bed_time_begin"] == 1380
    client.authorize.assert_called_once()
    client.logout.assert_called_once()
    coord.async_update_listeners.assert_called_once()
    coord.async_request_refresh.assert_awaited_once()


def test_concurrent_profile_edits_and_poll_share_existing_lock():
    client, state = firmware()
    coord = coordinator(client)

    async def run():
        await asyncio.gather(
            coord.set_profile_schedule("0", "workday", "time_limit", minutes=180),
            coord.set_profile_device("0", DEVICE["device_id"], True),
            coord._async_update_data(),
        )

    asyncio.run(run())
    assert state.records[0]["workday_daily_time"] == "180"
    assert state.records[0]["client_list"] == [DEVICE]
    assert client.authorize.call_count == client.logout.call_count == 3


def test_coordinator_failed_ack_publishes_actual_state_and_raises_redacted_error():
    client, state = firmware()
    coord = coordinator(client)
    state.acknowledgement = RuntimeError("private data")
    with pytest.raises(HomeAssistantError, match="acknowledgement failed"):
        asyncio.run(coord.set_profile_schedule("0", "workday", "time_limit", enabled=True))
    assert coord.parental_status.profiles["0"].settings["enable_workday_time_limit"]
    coord.async_request_refresh.assert_awaited_once()


def test_inventory_read_uses_same_lock_and_exposes_only_selection_fields():
    client, state = firmware()
    state.devices[0]["private_extra"] = "not exposed"
    coord = coordinator(client)
    result = asyncio.run(coord.get_parental_devices("0", "inventory"))
    assert result[0] == {**DEVICE, "owner_id": ""}
    client.authorize.assert_called_once()
    client.logout.assert_called_once()
    assert not state.writes
    state.devices = None
    with pytest.raises(HomeAssistantError, match="Unable to read"):
        asyncio.run(coord.get_parental_devices("0", "inventory"))


@pytest.mark.parametrize("method,args", [
    ("get_parental_devices", ("0",)), ("set_profile_device", ("0", "x", True)),
    ("set_profile_schedule", ("0", "workday", "time_limit")),
])
def test_unsupported_models_do_not_gain_profile_actions(method, args):
    coord = coordinator()
    coord.parental_status = None
    with pytest.raises(HomeAssistantError):
        asyncio.run(getattr(coord, method)(*args))
    coord.router.request.assert_not_called()


def test_dynamic_schedule_entities_follow_flags_and_remain_stable_on_rename():
    coord = coordinator()
    coord.parental_status = ParentalStatus(parse_profiles([FULL_RECORD]))
    added = []
    setup_parental_entities(coord, Mock(), lambda entities, update: added.extend(entities))
    assert len(added) == 5
    assert len({entity.unique_id for entity in added}) == 5
    schedule = next(entity for entity in added if entity.unique_id.endswith("enable_workday_bed_time"))
    original_id = schedule.unique_id
    assert schedule.available and schedule.is_on is False
    assert "Sun-Thu" in schedule.name
    assert "Mon-Fri" in next(entity for entity in added if entity.unique_id.endswith("workday_time_limit")).name
    assert schedule.extra_state_attributes["schedule"]["workday_bed_time_begin"] == "22:00"
    assert schedule.extra_state_attributes["owner_id"] == "0"
    coord.set_profile_schedule = AsyncMock()
    schedule.hass = SimpleNamespace(auth=SimpleNamespace(
        async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True, is_active=True)),
    ))
    schedule.async_set_context(Context(user_id="admin"))
    asyncio.run(schedule.async_turn_on())
    coord.set_profile_schedule.assert_awaited_with("0", "workday", "bed_time", enabled=True)
    asyncio.run(schedule.async_turn_off())
    coord.set_profile_schedule.assert_awaited_with("0", "workday", "bed_time", enabled=False)
    coord.parental_status = ParentalStatus(parse_profiles([{**FULL_RECORD, "name": "Renamed"}]))
    assert schedule.unique_id == original_id and schedule.name.startswith("Renamed")
    coord.async_add_listener.call_args.args[0]()
    assert len(added) == 5
    coord.parental_status = ParentalStatus(parse_profiles([{
        **FULL_RECORD, "bedtime": {"is_pro": True},
    }]))
    assert not schedule.available and schedule.is_on is None
    coord.parental_status = ParentalStatus(None)
    assert not schedule.available


def test_later_schedule_metadata_recovery_discovers_missing_entities():
    coord = coordinator()
    added = []
    setup_parental_entities(coord, Mock(), lambda entities, update: added.extend(entities))
    assert len(added) == 1
    coord.parental_status = ParentalStatus(parse_profiles([FULL_RECORD]))
    coord.async_add_listener.call_args.args[0]()
    assert len(added) == 5
    assert all(isinstance(entity, TPLinkParentalScheduleSwitch) for entity in added[1:])
    assert isinstance(added[0], TPLinkParentalAccessSwitch)


def service_hass():
    hass = SimpleNamespace(data={DOMAIN: {}}, services=Mock())
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(
        return_value=SimpleNamespace(is_admin=True, is_active=True),
    ))
    registrations = {}
    hass.services.has_service.side_effect = lambda domain, name: name in registrations

    def register(domain, name, handler, **kwargs):
        registrations[name] = (handler, kwargs)

    hass.services.async_register.side_effect = register
    return hass, registrations


def registry_entry(entry_id="entry-1", owner_id="0"):
    return SimpleNamespace(
        platform=DOMAIN, domain="switch", config_entry_id=entry_id,
        unique_id=f"{entry_id}_{DOMAIN}_parental_access_{owner_id}",
    )


def test_action_registration_idempotence_and_optional_defaults_are_not_injected():
    hass, registrations = service_hass()
    register_parental_services(hass)
    register_parental_services(hass)
    assert set(registrations) == set(PARENTAL_SERVICES)
    assert hass.services.async_register.call_count == 5
    assert registrations["get_parental_devices"][1]["supports_response"] is SupportsResponse.ONLY
    _, metadata = registrations["set_parental_bedtime"]
    assert metadata["schema"]({"profile": "switch.example", "period": "workday"}) == {
        "profile": "switch.example", "period": "workday",
    }
    with pytest.raises(vol.Invalid):
        metadata["schema"]({"profile": "switch.example", "period": "other"})


def test_registry_resolver_is_entry_scoped_and_rejects_nonprofile_switches():
    hass, _ = service_hass()
    first, second = coordinator(), coordinator()
    second.unique_id = "entry-2"
    hass.data[DOMAIN] = {"entry-1": first, "entry-2": second}
    registry = Mock()
    with patch("custom_components.tplink_router.parental_services.entity_registry.async_get", return_value=registry):
        registry.async_get.return_value = registry_entry("entry-2", "id_with_underscores")
        assert _resolve_profile(hass, "switch.profile") == (second, "id_with_underscores")
        for invalid in (
            None, SimpleNamespace(platform="other", domain="switch"),
            SimpleNamespace(platform=DOMAIN, domain="sensor"),
            registry_entry("not-loaded"),
            SimpleNamespace(platform=DOMAIN, domain="switch", config_entry_id="entry-1", unique_id="led"),
        ):
            registry.async_get.return_value = invalid
            with pytest.raises(HomeAssistantError):
                _resolve_profile(hass, "switch.profile")
        registry.async_get.return_value = registry_entry()
        first.parental_status = None
        with pytest.raises(HomeAssistantError):
            _resolve_profile(hass, "switch.profile")


@pytest.mark.parametrize("name,data,method,args,kwargs", [
    ("assign_parental_device", {"device_id": "router-id"}, "set_profile_device", ("0", "router-id", True), {}),
    ("remove_parental_device", {"device_id": "router-id"}, "set_profile_device", ("0", "router-id", False), {}),
    ("set_parental_bedtime", {"period": "workday", "begin": "22:00", "end": "07:00"},
     "set_profile_schedule", ("0", "workday", "bed_time"), {"begin": "22:00", "end": "07:00"}),
    ("set_parental_daily_limit", {"period": "weekend", "minutes": 120, "enabled": False},
     "set_profile_schedule", ("0", "weekend", "time_limit"), {"minutes": 120, "enabled": False}),
])
@pytest.mark.parametrize("context", [
    Context(user_id="admin"), Context(), Context(parent_id="automation-run"),
])
def test_action_handlers_delegate_only_explicit_fields(name, data, method, args, kwargs, context):
    hass, registrations = service_hass()
    register_parental_services(hass)
    coord = coordinator()
    setattr(coord, method, AsyncMock())
    handler, options = registrations[name]
    call = ServiceCall(
        hass, DOMAIN, name, options["schema"]({"profile": "switch.profile", **data}),
        context=context,
    )
    with patch("custom_components.tplink_router.parental_services._resolve_profile", return_value=(coord, "0")):
        asyncio.run(handler(call))
    getattr(coord, method).assert_awaited_once_with(*args, **kwargs)
    if context.user_id is None:
        hass.auth.async_get_user.assert_not_called()


@pytest.mark.parametrize("scope", [None, "profile", "inventory"])
@pytest.mark.parametrize("context", [
    Context(user_id="admin"), Context(), Context(parent_id="automation-run"),
])
def test_device_response_action_passes_selected_owner_and_explicit_scope_without_edit(scope, context):
    hass, registrations = service_hass()
    register_parental_services(hass)
    coord = coordinator()
    coord.get_parental_devices = AsyncMock(return_value=[DEVICE])
    handler, _ = registrations["get_parental_devices"]
    data = {"profile": "switch.profile"}
    if scope is not None:
        data["scope"] = scope
    with patch("custom_components.tplink_router.parental_services._resolve_profile", return_value=(coord, "0")):
        result = asyncio.run(handler(ServiceCall(
            hass, DOMAIN, "get_parental_devices", data, context=context,
        )))
    assert result == {"devices": [DEVICE]}
    coord.get_parental_devices.assert_awaited_once_with("0", scope or "profile")
    coord.router.request.assert_not_called()
    if context.user_id is None:
        hass.auth.async_get_user.assert_not_called()


def test_profile_devices_use_fresh_membership_not_inventory_owner_labels_or_cached_data():
    client, state = firmware([
        {**FULL_RECORD, "client_list": [{**DEVICE, "owner_id": 99}]},
        {**FULL_RECORD, "owner_id": "1", "client_list": [SECOND_DEVICE]},
        {**FULL_RECORD, "owner_id": "2", "client_list": {}},
    ])
    state.devices = [SECOND_DEVICE, {**DEVICE, "owner_id": "1"}, {
        **DEVICE, "device_id": "unassigned", "owner_id": "",
    }]
    coord = coordinator(client)
    coord.parental_status = ParentalStatus(parse_profiles([RECORD]))
    request = client.request.side_effect

    def serialized(*args):
        assert coord._lock.locked()
        return request(*args)

    client.request.side_effect = serialized
    assert asyncio.run(coord.get_parental_devices("0")) == [{**DEVICE, "owner_id": "0"}]
    assert asyncio.run(coord.get_parental_devices("1")) == [{**SECOND_DEVICE, "owner_id": "1"}]
    assert asyncio.run(coord.get_parental_devices("2")) == []
    assert all(call.args == (PROFILE_LIST_PATH, "operation=load") for call in client.request.call_args_list)
    assert client.authorize.call_count == client.logout.call_count == 3
    assert not state.writes


@pytest.mark.parametrize("scope", ["profile", "inventory"])
def test_stale_profile_target_rejected_even_for_inventory(scope):
    client, state = firmware([])
    coord = coordinator(client)
    with pytest.raises(HomeAssistantError, match="no longer exists"):
        asyncio.run(coord.get_parental_devices("0", scope))
    client.request.assert_called_once_with(PROFILE_LIST_PATH, "operation=load")
    assert not state.writes


@pytest.mark.parametrize("owner_id,scope", [("", "profile"), (None, "profile"), ("0", "unknown")])
def test_invalid_profile_device_target_or_scope_never_reads(owner_id, scope):
    coord = coordinator()
    with pytest.raises(HomeAssistantError, match="Invalid parental"):
        asyncio.run(coord.get_parental_devices(owner_id, scope))
    coord.router.request.assert_not_called()


@pytest.mark.parametrize("clients", [None, {"not": "empty"}, [DEVICE, DEVICE]])
def test_invalid_profile_assignments_are_not_empty_success(clients):
    client, _ = firmware([{**FULL_RECORD, "client_list": clients}])
    coord = coordinator(client)
    with pytest.raises(HomeAssistantError, match="Assigned device list is invalid"):
        asyncio.run(coord.get_parental_devices("0"))


def test_explicit_inventory_includes_other_profiles_and_unassigned_devices():
    client, state = firmware([{**FULL_RECORD, "client_list": [DEVICE]}])
    state.devices = [
        {**DEVICE, "owner_id": "0"}, {**SECOND_DEVICE, "owner_id": 1},
        {**DEVICE, "device_id": "unassigned", "owner_id": ""},
    ]
    coord = coordinator(client)
    result = asyncio.run(coord.get_parental_devices("0", "inventory"))
    assert [device["owner_id"] for device in result] == ["0", "1", ""]
    assert len(result) == 3
    assert not state.writes


def test_device_scope_schema_defaults_to_profile_and_rejects_unknown_scope():
    hass, registrations = service_hass()
    register_parental_services(hass)
    schema = registrations["get_parental_devices"][1]["schema"]
    assert schema({"profile": "switch.profile"})["scope"] == "profile"
    assert schema({"profile": "switch.profile", "scope": "inventory"})["scope"] == "inventory"
    with pytest.raises(vol.Invalid):
        schema({"profile": "switch.profile", "scope": "all"})


def test_services_only_registered_when_supported_and_removed_after_last_entry():
    hass, registrations = service_hass()
    first = coordinator()
    first.support_dhcp_reservations = False
    hass.data[DOMAIN] = {"entry-1": first, "entry-2": coordinator()}
    first.parental_status = None
    register_services(hass, first)
    assert not registrations
    first.parental_status = ParentalStatus(None)
    register_services(hass, first)
    assert len(registrations) == 5
    hass.config_entries = SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True))
    assert asyncio.run(async_unload_entry(hass, SimpleNamespace(entry_id="entry-1", data={})))
    hass.services.async_remove.assert_not_called()
    assert asyncio.run(async_unload_entry(hass, SimpleNamespace(entry_id="entry-2", data={})))
    assert {call.args[1] for call in hass.services.async_remove.call_args_list} == set(PARENTAL_SERVICES)


def test_service_metadata_describes_every_registered_action():
    metadata = load_yaml(Path("custom_components") / DOMAIN / "services.yaml")
    for service in PARENTAL_SERVICES:
        assert service in metadata
        assert metadata[service]["fields"]["profile"]["required"] is True
    assert "Sunday-Thursday" in str(metadata["set_parental_bedtime"])
    assert metadata["set_parental_daily_limit"]["fields"]["minutes"]["selector"]["number"]["step"] == 15


@pytest.mark.parametrize("native_assignment", [False, True])
def test_full_profile_update_through_exact_pinned_transport(native_assignment):
    existing = {**SECOND_DEVICE, "prio": "off", "prio_time": "0", "online": 1, "owner_id": 0}
    client, state = firmware(
        [observed_record(client_list=[existing], insights="readonly")] if native_assignment else None,
    )
    firmware_request = client.request.side_effect
    client.request = TplinkRequest.request.__get__(client)
    client._logged = True
    client.host = "http://example.invalid"
    client._stok = "mock"
    client._sysauth = "mock"
    client._headers_request = {}
    client.timeout = 1
    client._verify_ssl = False
    client._prepare_data = TplinkEncryption._prepare_data.__get__(client)
    client._decrypt_response = TplinkEncryption._decrypt_response.__get__(client)
    client._encryption = Mock()
    client.username, client.password = "synthetic", "synthetic"
    client._seq, client.nn, client.ee = 1, "synthetic", "synthetic"
    client._encryption.aes_encrypt.side_effect = lambda value: base64.b64encode(value.encode()).decode()
    client._encryption.get_signature.return_value = "synthetic-signature"
    decrypted = {}
    client._encryption.aes_decrypt.side_effect = lambda value: dumps(decrypted)

    def post(url, **kwargs):
        nonlocal decrypted
        path = url.split(";stok=mock/")[1]
        assert kwargs["data"]["sign"] == "synthetic-signature"
        result = firmware_request(path, base64.b64decode(kwargs["data"]["data"]).decode())
        decrypted = {"success": True} if result is True else {"success": True, "data": result}
        response = Mock()
        response.json.return_value = {"data": "encrypted"}
        return response

    with patch("tplinkrouterc6u.client.c6u.post", side_effect=post) as transport:
        status, error = edit_profile(
            client, LOGGER, "0", **(
                {"add_device": DEVICE["device_id"]} if native_assignment else {"changes": {"workday_daily_time": 180}}
            ),
        )
    assert error is None
    assert len(state.writes) == 1
    if native_assignment:
        assert transport.call_count == 6  # fresh profile, inventory, capacity, app metadata, update, read-back
        new = loads(state.writes[0]["new"])
        assert "insights" not in new and "workday_daily_time" not in new
        assert new["client_list"] == [{key: existing[key] for key in DEVICE}, DEVICE]
        assert len(status.profiles["0"].clients) == 2
        assert state.records[0]["workday_daily_time"] == "0"
        assert state.records[0]["client_list"][0]["prio"] == "off"
    else:
        assert transport.call_count == 4
        assert status.profiles["0"].settings["workday_daily_time"] == 180
        assert loads(state.writes[0]["new"])["workday_daily_time"] == "180"
    assert (
        client._encryption.aes_encrypt.call_count == client._encryption.get_signature.call_count == transport.call_count
    )
    assert client._logger is LOGGER and client._data_block == "data"


@pytest.mark.parametrize("context", [
    Context(user_id="admin"), Context(), Context(parent_id="automation-run"),
])
def test_actions_through_real_homeassistant_service_registry(tmp_path, context):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        hass.auth = SimpleNamespace(async_get_user=AsyncMock(
            return_value=SimpleNamespace(is_admin=True, is_active=True),
        ))
        coord = coordinator()
        coord.get_parental_devices = AsyncMock(return_value=[DEVICE])
        coord.set_profile_schedule = AsyncMock()
        register_parental_services(hass)
        with patch("custom_components.tplink_router.parental_services._resolve_profile", return_value=(coord, "0")):
            response = await hass.services.async_call(
                DOMAIN, "get_parental_devices", {"profile": "switch.profile"},
                blocking=True, return_response=True,
                context=context,
            )
            assert response == {"devices": [DEVICE]}
            await hass.services.async_call(
                DOMAIN, "set_parental_daily_limit",
                {"profile": "switch.profile", "period": "weekend", "minutes": 180.0},
                blocking=True,
                context=context,
            )
        coord.set_profile_schedule.assert_awaited_once_with("0", "weekend", "time_limit", minutes=180.0)
        if context.user_id is None:
            hass.auth.async_get_user.assert_not_called()
        await hass.async_stop(force=True)

    asyncio.run(run())
