"""Synthetic native-schema tests; no household reports or live router writes."""
import asyncio
import base64
from copy import deepcopy
from json import dumps, loads
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs

from homeassistant.exceptions import HomeAssistantError, Unauthorized
import pytest
import voluptuous as vol
from tplinkrouterc6u.client.c6u import TplinkEncryption, TplinkRequest

from custom_components.tplink_router.network import websocket_action, websocket_profile_read
from custom_components.tplink_router.parental_control import (
    PROFILE_LIST_PATH, ParentalEditError, ParentalStatus, parse_profiles,
)
from custom_components.tplink_router.parental_features import (
    FILTER_PATH, HISTORY_PATH, INSIGHTS_PATH, create_profile, delete_profile, deletion_preview,
    parse_history, parse_insights, profile_creation_options, read_profile_report, rename_profile,
)
from test_network import network_fixture, records
from test_parental_control import LOGGER, coordinator
from test_parental_settings import FULL_RECORD, firmware

INSIGHTS = {"insights": [
    {"spend_online": 42, "website_list": [{"website": "example.test", "spend_online": 12, "block": False}]},
    {"spend_online": "0", "website_list": {}},
]}
HISTORY = {"history": [{"website": "example.test", "access_timestamp": 1700000000, "block": True}]}


def feature_firmware(rows=None):
    client, state = firmware(records() if rows is None else rows)
    state.limits.update({"profile_len": "16", "category_len": 32})
    state.filters = [
        {"filter_level": "teen", "categories_list": ["mandatory"], "prefilter_list": ["preset"]},
        {"filter_level": "adult", "categories_list": {}, "prefilter_list": []},
        {"filter_level": "all", "categories_list": ["mandatory", "preset"]},
    ]
    state.insights, state.history = deepcopy(INSIGHTS), deepcopy(HISTORY)
    state.mutate = lambda: None
    original = client.request.side_effect

    def request(path, body):
        assert client._logger is None
        fields = {key: values[0] for key, values in parse_qs(body).items()}
        if path in (FILTER_PATH, INSIGHTS_PATH, HISTORY_PATH):
            value = {FILTER_PATH: state.filters, INSIGHTS_PATH: state.insights, HISTORY_PATH: state.history}[path]
            assert fields["operation"] == ("load" if path == FILTER_PATH else "read")
            if isinstance(value, Exception):
                raise value
            return deepcopy(value)
        if path == PROFILE_LIST_PATH and fields["operation"] in ("insert", "remove"):
            assert client._data_block == "success"
            state.writes.append(fields)
            if state.apply:
                if fields["operation"] == "insert":
                    state.records.insert(0, {
                        **loads(fields["new"]), "owner_id": "new-17", "internet_blocked": False,
                        "limit": 0, "insights": {},  # Generated response-only metadata.
                    })
                else:
                    state.records.pop(int(fields["index"]))
                state.mutate()
            if isinstance(state.acknowledgement, Exception):
                raise state.acknowledgement
            return state.acknowledgement
        return original(path, body)

    client.request.side_effect = request
    return client, state


def test_creation_options_use_live_capacity_and_union_native_mandatory_and_preset():
    client, state = feature_firmware()
    options = profile_creation_options(client)
    assert options == {
        "maximum": 16, "remaining": 13,
        "presets": [
            {"filter_level": "teen", "categories": ["preset", "mandatory"]},
            {"filter_level": "adult", "categories": []},
        ],
    }
    assert not state.writes


@pytest.mark.parametrize("change", ["limits", "zero", "filter", "duplicate", "categories", "capacity", "nofilters"])
def test_bad_creation_metadata_never_falls_back_to_invented_defaults(change):
    client, state = feature_firmware()
    if change == "limits":
        state.limits.pop("profile_len")
    elif change == "zero":
        state.limits["profile_len"] = 0
    elif change == "filter":
        state.filters = None
    elif change == "duplicate":
        state.filters.append(state.filters[0])
    elif change == "categories":
        state.filters[0]["prefilter_list"] = {"nonempty": True}
    elif change == "capacity":
        state.limits["category_len"] = 1
    else:
        state.filters = []
    with pytest.raises(ParentalEditError, match="metadata"):
        profile_creation_options(client)
    assert not state.writes


def test_creation_exact_native_store_wire_and_all_existing_profiles_preserved():
    client, state = feature_firmware()
    before = deepcopy(state.records)
    status, result = create_profile(client, "A & + profile", "teen", ["preset", "mandatory"])
    assert result == {"confirmed": True, "owner_id": "new-17", "error": None}
    assert status.profiles["new-17"].clients == ()
    assert len(state.writes) == 1
    wire = state.writes[0]
    assert {key: wire[key] for key in ("operation", "key", "index", "old")} == {
        "operation": "insert", "key": "add", "index": "0", "old": "add",
    }
    new = loads(wire["new"])
    assert "owner_id" not in new and "internet_blocked" not in new
    assert new["name"] == "A & + profile"
    assert new["app_list"] == new["website_list"] == new["client_list"] == []
    assert new["categories_list"] == ["preset", "mandatory"]
    for period in ("workday", "weekend"):
        assert new[f"{period}_daily_time"] == "120"
        assert new[f"{period}_bed_time_begin"] == 1320
        assert new[f"{period}_bed_time_end"] == 420
        assert new[f"enable_{period}_time_limit"] is new[f"enable_{period}_bed_time"] is False
    assert state.records[1:] == before


@pytest.mark.parametrize("name", ["", " ", "a" * 65, "🙂" * 33, "bad\nname", "\x7f"])
def test_creation_invalid_name_rejected_before_transport(name):
    client, state = feature_firmware()
    with pytest.raises(ParentalEditError, match="name"):
        create_profile(client, name, "adult", [])
    client.request.assert_not_called()
    assert not state.writes


@pytest.mark.parametrize("change", ["full", "duplicate", "preset", "shape", "missing_level"])
def test_creation_preflight_no_write_on_stale_preset_capacity_or_membership(change):
    client, state = feature_firmware()
    level, categories, name = "adult", [], "New"
    if change == "full":
        state.limits["profile_len"] = 3
    elif change == "duplicate":
        name = state.records[0]["name"].upper()
    elif change == "preset":
        categories = ["not-current"]
    elif change == "shape":
        state.records[0]["client_list"] = {"bad": True}
    else:
        level = "teen-not-present"
    with pytest.raises(ParentalEditError):
        create_profile(client, name, level, categories)
    assert not state.writes


@pytest.mark.parametrize("failure", ["ignored", "ack", "readback", "other", "budget", "extra", "name"])
def test_creation_failure_actual_state_single_attempt_no_retry_or_deletion(failure):
    client, state = feature_firmware()
    if failure == "ignored":
        state.apply = False
    elif failure == "ack":
        state.acknowledgement = TimeoutError("private.example")
    elif failure == "readback":
        state.fail_readback = True
    else:
        def mutate():
            if failure == "other":
                state.records[1]["opaque_setting"] = "changed"
            elif failure == "budget":
                state.records[0]["workday_daily_time"] = "0"
            elif failure == "extra":
                state.records.append({**deepcopy(FULL_RECORD), "owner_id": "unexpected"})
            else:
                state.records[0]["name"] = "Different"
        state.mutate = mutate
    status, result = create_profile(client, "New", "adult", [])
    assert not result["confirmed"] and result["error"]
    assert "private" not in result["error"]
    assert len(state.writes) == 1
    if failure == "ack":
        assert status.profiles["new-17"].name == "New" and result["owner_id"] == "new-17"
    if failure == "readback":
        assert status.profiles is None


def test_rename_keeps_identity_and_protected_configuration_and_noop_sends_nothing():
    client, state = feature_firmware()
    old = state.records[0]["name"]
    before = deepcopy(state.records)
    status, error = rename_profile(client, LOGGER, "0", old, "Renamed + &")
    assert not error
    assert status.profiles["0"].name == "Renamed + &"
    assert len(state.writes) == 1
    new = state.records[0]
    assert {key: value for key, value in new.items() if key not in ("name", "key", "website_list", "app_list")} == {
        key: value for key, value in before[0].items() if key not in ("name", "key", "website_list", "app_list")
    }
    assert state.records[1:] == before[1:]
    rename_profile(client, LOGGER, "0", "Renamed + &", "Renamed + &")
    assert len(state.writes) == 1


@pytest.mark.parametrize("change", ["removed", "renamed", "duplicate", "invalid", "members"])
def test_rename_stale_invalid_and_duplicate_preflight(change):
    client, state = feature_firmware()
    name = "New"
    expected = state.records[0]["name"]
    if change == "removed":
        state.records.pop(0)
    elif change == "renamed":
        state.records[0]["name"] = "Changed"
    elif change == "duplicate":
        name = state.records[1]["name"]
    elif change == "invalid":
        name = "\n"
    else:
        state.records[0]["client_list"] = {"bad": True}
    with pytest.raises(ParentalEditError):
        rename_profile(client, LOGGER, "0", expected, name)
    assert not state.writes


def test_delete_fresh_preview_native_single_key_index_and_others_unchanged():
    client, state = feature_firmware()
    before = deepcopy(state.records)
    preview = deletion_preview(client, "0")
    assert preview["members"] and len(preview["revision"]) == 64
    assert "private.example" not in str(preview)
    status, error = delete_profile(client, "0", preview["revision"])
    assert not error and "0" not in status.profiles
    assert state.records == before[1:]
    assert state.writes == [{"operation": "remove", "key": "key-0", "index": "0"}]


@pytest.mark.parametrize("change", ["name", "client_list", "workday_daily_time", "website_list", "opaque_setting"])
def test_delete_rejects_any_protected_change_since_preview_without_write(change):
    client, state = feature_firmware()
    preview = deletion_preview(client, "0")
    state.records[0][change] = [] if change == "client_list" else (
        ["changed.test"] if change == "website_list" else "changed"
    )
    with pytest.raises(ParentalEditError, match="changed"):
        delete_profile(client, "0", preview["revision"])
    assert not state.writes


def test_delete_does_not_confuse_generated_online_and_owner_metadata_with_settings():
    client, state = feature_firmware()
    preview = deletion_preview(client, "0")
    state.records[0]["client_list"][0].update({"online": 1, "owner_id": "0"})
    assert delete_profile(client, "0", preview["revision"])[1] is None


@pytest.mark.parametrize("failure", ["ignored", "ack", "readback", "other"])
def test_delete_ambiguous_failures_preserve_actual_state_no_retry_or_recreation(failure):
    client, state = feature_firmware()
    preview = deletion_preview(client, "0")
    if failure == "ignored":
        state.apply = False
    elif failure == "ack":
        state.acknowledgement = TimeoutError("private.example")
    elif failure == "readback":
        state.fail_readback = True
    else:
        state.mutate = lambda: state.records[0].update({"internet_blocked": True})
    status, error = delete_profile(client, "0", preview["revision"])
    assert error and "private" not in error
    assert len(state.writes) == 1
    if failure == "ack":
        assert "0" not in status.profiles


def test_report_parser_verified_native_minutes_seconds_flags_and_no_extra_fields():
    insights = parse_insights(INSIGHTS)
    assert insights[0] == {
        "minutes": 42, "websites": [{"website": "example.test", "minutes": 12, "blocked": False}],
    }
    assert insights[1]["websites"] == []
    assert parse_history({**HISTORY, "secret_extra": "ignored"}) == [{
        "website": "example.test", "timestamp": 1700000000, "blocked": True,
    }]
    assert parse_insights({"insights": {}}) == parse_history({"history": []}) == []


@pytest.mark.parametrize("value", [
    None, {}, {"insights": None}, {"insights": {"bad": True}},
    {"insights": [{}]}, {"insights": [INSIGHTS["insights"][0]] * 8},
])
def test_invalid_reports_are_not_successful_empty_results(value):
    with pytest.raises(ValueError):
        parse_insights(value)


@pytest.mark.parametrize("key,value", [
    ("website", ""), ("website", 1), ("block", "false"), ("block", 0),
    ("spend_online", True), ("spend_online", "nan"), ("spend_online", -1), ("spend_online", 1441),
])
def test_malformed_site_fields_reject_section(key, value):
    data = deepcopy(INSIGHTS)
    data["insights"][0]["website_list"][0][key] = value
    with pytest.raises(ValueError):
        parse_insights(data)


@pytest.mark.parametrize("value", [-1, True, "inf", None, 253402300800])
def test_invalid_history_timestamps_reject_section(value):
    data = deepcopy(HISTORY)
    data["history"][0]["access_timestamp"] = value
    with pytest.raises(ValueError):
        parse_history(data)


@pytest.mark.parametrize("failure", ["unsupported", "transport", "schema"])
def test_report_sections_fail_independently_without_private_exception_text(failure):
    client, state = feature_firmware()
    state.insights = {
        "unsupported": NotImplementedError("private.example"),
        "transport": TimeoutError("private.example"), "schema": {"unexpected": True},
    }[failure]
    result = read_profile_report(client, "0")
    assert result["history"]["status"] == "ok"
    assert result["insights"]["status"] == ("unsupported" if failure == "unsupported" else "unavailable")
    assert "private" not in str(result) and not state.writes
    with pytest.raises(ParentalEditError, match="no longer"):
        read_profile_report(client, "removed")


def test_coordinator_feature_reads_and_writes_share_lock_and_never_retain_browsing_data():
    async def run():
        client, state = feature_firmware()
        coord = coordinator(client)
        coord.parental_status = ParentalStatus(parse_profiles(state.records))
        coord.async_update_listeners = Mock()
        coord._request_lock = asyncio.Lock()
        callbacks = []

        async def run_locked(callback):
            async with coord._request_lock:
                callbacks.append(callback)
                return callback()

        coord._run_router_request = run_locked
        coord.async_request_refresh = AsyncMock()
        original = deepcopy(coord.parental_status)
        result = await coord.get_profile_feature("report", "0")
        assert result["insights"]["status"] == "ok"
        assert coord.parental_status == original
        assert "example.test" not in str(coord.__dict__)
        result = await coord.create_parental_profile("New", "adult", [])
        assert result["confirmed"]
        await coord.manage_parental_profile("rename_profile", "new-17", expected_name="New", name="Newer")
        preview = await coord.get_profile_feature("delete_preview", "new-17")
        await coord.manage_parental_profile("delete_profile", "new-17", revision=preview["revision"])
        assert len(callbacks) == 5
        assert coord.async_request_refresh.await_count == 3
    asyncio.run(run())


@pytest.mark.parametrize("handler", [websocket_profile_read, websocket_action])
@pytest.mark.parametrize("user", [None, SimpleNamespace(is_admin=False)])
def test_new_websocket_authorization_precedes_scheduling(handler, user):
    hass = Mock()
    with pytest.raises(Unauthorized):
        handler(hass, SimpleNamespace(user=user), {"id": 1})
    hass.async_create_background_task.assert_not_called()


def test_new_websocket_exact_schemas_and_dispatch_no_report_in_network_snapshot():
    async def run():
        hass, coord, _ = network_fixture()
        coord.get_profile_feature = AsyncMock(return_value={"private": "example.test"})
        coord.create_parental_profile = AsyncMock(return_value={"confirmed": True})
        coord.manage_parental_profile = AsyncMock()
        connection = SimpleNamespace(user=SimpleNamespace(is_admin=True, is_active=True), send_result=Mock())
        current = {"available": True, "paused": False, "stale": False, "profiles_available": True}
        with patch("custom_components.tplink_router.network.snapshot", return_value=current):
            reader = websocket_profile_read.__wrapped__.__wrapped__
            for kind in ("report", "creation_options", "delete_preview"):
                await reader(hass, connection, {"id": 1, "entry_id": "entry-1", "kind": kind, "owner_id": "0"})
            for payload in (
                {"action": "create_profile", "name": "New", "filter_level": "adult", "categories": []},
                {"action": "rename_profile", "name": "Newer", "expected_name": "New", "owner_id": "0"},
                {"action": "delete_profile", "revision": "a" * 64, "owner_id": "0"},
            ):
                await websocket_action.__wrapped__.__wrapped__(hass, connection, {
                    "id": 2, "entry_id": "entry-1", **payload,
                })
                assert "example.test" not in str(connection.send_result.call_args)
            with pytest.raises(HomeAssistantError, match="Choose"):
                await reader(hass, connection, {"id": 1, "entry_id": "entry-1", "kind": "report"})
            current["paused"] = True
            with pytest.raises(HomeAssistantError, match="unavailable"):
                await reader(hass, connection, {"id": 1, "entry_id": "entry-1", "kind": "report", "owner_id": "0"})
        assert coord.get_profile_feature.await_count == 3
        coord.create_parental_profile.assert_awaited_once_with("New", "adult", [])
        assert coord.manage_parental_profile.await_count == 2
    asyncio.run(run())
    base = {"id": 1, "type": "tplink_router/profile_read", "entry_id": "entry-1", "kind": "report", "owner_id": "0"}
    assert websocket_profile_read._ws_schema(base) == base
    for fields in ({"kind": "raw"}, {"token": "secret"}, {"owner_id": ""}):
        with pytest.raises(vol.Invalid):
            websocket_profile_read._ws_schema({**base, **fields})


@pytest.mark.parametrize("operation", ["create", "rename", "delete", "report"])
def test_native_features_through_exact_pinned_request_and_encryption_envelope(operation):
    client, state = feature_firmware()
    native = client.request.side_effect
    client.request = TplinkRequest.request.__get__(client)
    client._logged, client.host = True, "http://example.invalid"
    client._stok = client._sysauth = "synthetic"
    client._headers_request, client.timeout, client._verify_ssl = {}, 1, False
    client._prepare_data = TplinkEncryption._prepare_data.__get__(client)
    client._decrypt_response = TplinkEncryption._decrypt_response.__get__(client)
    client._encryption = Mock()
    client.username = client.password = "synthetic"
    client._seq, client.nn, client.ee = 1, "synthetic", "synthetic"
    client._encryption.aes_encrypt.side_effect = lambda value: base64.b64encode(value.encode()).decode()
    client._encryption.get_signature.return_value = "synthetic-signature"
    decrypted = {}
    client._encryption.aes_decrypt.side_effect = lambda value: dumps(decrypted)

    def post(url, **kwargs):
        nonlocal decrypted
        assert kwargs["data"]["sign"] == "synthetic-signature"
        result = native(url.split(";stok=synthetic/")[1], base64.b64decode(kwargs["data"]["data"]).decode())
        decrypted = {"success": True} if result is True else {"success": True, "data": result}
        response = Mock()
        response.json.return_value = {"data": "synthetic-ciphertext"}
        return response

    with patch("tplinkrouterc6u.client.c6u.post", side_effect=post) as transport:
        if operation == "create":
            assert create_profile(client, "New + &", "teen", ["preset", "mandatory"])[1]["confirmed"]
        elif operation == "rename":
            assert rename_profile(client, LOGGER, "0", state.records[0]["name"], "New + &")[1] is None
        elif operation == "delete":
            preview = deletion_preview(client, "0")
            assert delete_profile(client, "0", preview["revision"])[1] is None
        else:
            assert read_profile_report(client, "0")["history"]["status"] == "ok"
    assert len(state.writes) == (0 if operation == "report" else 1)
    assert transport.call_count == client._encryption.aes_encrypt.call_count
    assert client._logger is LOGGER and client._data_block == "data"


@pytest.mark.parametrize("kind", ["report", "creation_options", "delete_preview"])
def test_inactive_admin_cannot_read_private_features(kind):
    with pytest.raises(Unauthorized):
        asyncio.run(websocket_profile_read.__wrapped__.__wrapped__(
            Mock(), SimpleNamespace(user=SimpleNamespace(is_active=False)), {"kind": kind},
        ))


@pytest.mark.parametrize("feature", ["create", "rename", "delete", "report"])
def test_unsupported_coordinator_never_contacts_router(feature):
    coord = coordinator()
    coord.parental_status = None
    coroutine = (
        coord.create_parental_profile("New", "adult", []) if feature == "create"
        else coord.get_profile_feature("report", "0") if feature == "report"
        else coord.manage_parental_profile(feature + "_profile", "0")
    )
    with pytest.raises(HomeAssistantError, match="unsupported"):
        asyncio.run(coroutine)
    coord.router.request.assert_not_called()
