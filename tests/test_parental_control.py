import asyncio
import logging
from json import dumps
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs

import pytest
from homeassistant.exceptions import HomeAssistantError
from tplinkrouterc6u import TplinkRouter
from tplinkrouterc6u.client.c6u import TplinkEncryption, TplinkRequest

from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator, collect_status
from custom_components.tplink_router.parental_control import (
    PROFILE_BLOCK_PATH,
    PROFILE_LIST_PATH,
    ParentalProfile,
    ParentalStatus,
    collect_parental_status,
    parse_profiles,
    supports_parental_control,
    write_profile_access,
)
from custom_components.tplink_router.switch import (
    TPLinkParentalAccessSwitch,
    setup_parental_entities,
)


LOGGER = logging.getLogger("test.parental")
RECORD = {"owner_id": "0", "name": "Example", "internet_blocked": False}


def router():
    client = TplinkRouter.__new__(TplinkRouter)
    client._logger = LOGGER
    client._data_block = "data"
    client.authorize = Mock()
    client.logout = Mock()
    client.request = Mock(return_value=[dict(RECORD)])
    client.get_status = Mock(return_value="STATUS")
    return client


def coordinator(client=None):
    coord = TPLinkRouterCoordinator.__new__(TPLinkRouterCoordinator)
    coord.router = client or router()

    async def executor(fn, *args):
        return fn(*args)

    coord.hass = SimpleNamespace(async_add_executor_job=executor)
    coord._lock = asyncio.Lock()
    coord.logger = LOGGER
    coord.unique_id = "entry-1"
    coord.device_info = {"identifiers": {(DOMAIN, "aa:bb")}}
    coord.last_update_success = True
    coord.parental_status = ParentalStatus(parse_profiles([RECORD]))
    coord.async_update_listeners = Mock()
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = Mock()
    coord.status = None
    for key in (
        "lte_status", "serving_cells", "vpn_server_status", "vpn_client_status",
        "port_status", "reservations", "mesh_nodes", "led_status",
    ):
        setattr(coord, key, None)
    coord.retries = 1
    coord.scan_stopped_at = None
    coord.scan_pause_minutes = 0
    coord.backoff_seconds = 0
    return coord


def test_parse_profiles_keeps_only_control_fields_and_handles_empty_profiles():
    records = [
        {**RECORD, "client_list": [], "website_list": ["private.example"]},
        {"owner_id": "1", "name": "", "internet_blocked": True},
    ]
    assert parse_profiles(records) == {
        "0": ParentalProfile("0", "Example", False),
        "1": ParentalProfile("1", "", True),
    }
    assert parse_profiles([]) == {}


@pytest.mark.parametrize("data", [
    None, {}, {"success": False}, "bad", [None], [[]],
    [{"name": "Missing ID", "internet_blocked": False}],
    [{**RECORD, "owner_id": 0}], [{**RECORD, "owner_id": ""}],
    [{**RECORD, "owner_id": " "}], [{**RECORD, "name": None}],
    [{"owner_id": "0", "internet_blocked": False}],
    [{"owner_id": "0", "name": "Missing flag"}],
    [{**RECORD, "internet_blocked": "false"}],
    [{**RECORD, "internet_blocked": 0}],
    [{**RECORD, "internet_blocked": None}],
    [RECORD, RECORD],
])
def test_invalid_profiles_are_not_empty_success(data):
    with pytest.raises(ValueError):
        parse_profiles(data)


def test_supported_models_and_transports():
    client = router()
    assert supports_parental_control(client, "Archer AX50")
    assert supports_parental_control(client, "AX50")
    assert not supports_parental_control(client, "Archer AX55")
    assert not supports_parental_control(object(), "Archer AX50")
    assert collect_parental_status(object(), LOGGER) is None


def test_read_payload_and_empty_success():
    client = router()
    assert collect_parental_status(client, LOGGER).profiles["0"].name == "Example"
    client.request.assert_called_once_with(PROFILE_LIST_PATH, "operation=load")
    client.request.return_value = []
    assert collect_parental_status(client, LOGGER) == ParentalStatus({})


@pytest.mark.parametrize("failure", [TimeoutError, RuntimeError, ValueError])
def test_read_errors_are_unavailable_retryable_and_redacted(failure, caplog):
    client = router()
    client.request.side_effect = failure("private browsing data")
    assert collect_parental_status(client, LOGGER) == ParentalStatus(None)
    assert "private browsing data" not in caplog.text
    assert "retrying next poll" in caplog.text
    assert client._logger is LOGGER
    client.request.side_effect = None
    assert collect_parental_status(client, LOGGER).profiles is not None


def test_explicit_unsupported_stops_polling():
    client = router()
    client.request.side_effect = NotImplementedError
    assert collect_parental_status(client, LOGGER) is None


@pytest.mark.parametrize("enabled,blocked", [(True, "false"), (False, "true")])
def test_write_encoding_and_polarity(enabled, blocked):
    client = router()
    client.request.return_value = True
    write_profile_access(client, "id &+=/", enabled)
    path, body = client.request.call_args.args
    assert path == PROFILE_BLOCK_PATH
    assert parse_qs(body) == {
        "operation": ["write"], "owner_id": ["id &+=/"], "internet_blocked": [blocked],
    }
    assert client._logger is LOGGER
    assert client._data_block == "data"


@pytest.mark.parametrize("owner_id,enabled", [("", True), (None, True), ("0", "false")])
def test_invalid_writes_are_rejected(owner_id, enabled):
    client = router()
    with pytest.raises(ValueError):
        write_profile_access(client, owner_id, enabled)
    client.request.assert_not_called()


def test_library_response_logging_is_suppressed_only_for_profile_request():
    client = router()

    def request(*args):
        assert client._logger is None
        assert client._data_block == "success"
        raise RuntimeError("private profile data")

    client.request.side_effect = request
    with pytest.raises(RuntimeError):
        write_profile_access(client, "0", False)
    assert client._logger is LOGGER
    assert client._data_block == "data"


def test_pinned_library_transport_form_encoding_and_list_unwrapping():
    client = router()
    client.request = TplinkRequest.request.__get__(client)
    client._logged = True
    client.host = "http://example.invalid"
    client._stok = "mock"
    client._sysauth = "mock"
    client._headers_request = {}
    client._data_block = "data"
    client.timeout = 1
    client._verify_ssl = False
    client._prepare_data = lambda data: data
    client._decrypt_response = TplinkEncryption._decrypt_response.__get__(client)
    client._encryption = Mock()
    decrypted = {"success": True, "data": [RECORD]}
    client._encryption.aes_decrypt.side_effect = lambda value: dumps(decrypted)
    response = Mock()
    response.json.return_value = {"data": "encrypted"}
    with patch("tplinkrouterc6u.client.c6u.post", return_value=response) as post:
        assert collect_parental_status(client, LOGGER).profiles["0"].name == "Example"
        for acknowledgement in (
            {"success": True, "data": {}},
            {"success": True},
            {"success": True, "errorcode": "0"},
        ):
            decrypted = acknowledgement
            write_profile_access(client, "0", False)
            assert client._data_block == "data"
        assert post.call_args.kwargs["data"] == (
            "operation=write&owner_id=0&internet_blocked=true"
        )
        decrypted = {"success": False, "errorcode": "unknown"}
        assert collect_parental_status(client, LOGGER) == ParentalStatus(None)
        with pytest.raises(Exception):
            write_profile_access(client, "0", True)
        assert client._data_block == "data"
        decrypted = {}
        with pytest.raises(Exception):
            write_profile_access(client, "0", True)
    assert client._logger is LOGGER


def test_polling_reuses_login_and_recovers_after_failure():
    coord = coordinator()
    coord.router.request.side_effect = TimeoutError
    asyncio.run(coord._async_update_data())
    assert coord.status == "STATUS"
    assert coord.parental_status == ParentalStatus(None)
    coord.router.request.side_effect = None
    asyncio.run(coord._async_update_data())
    assert coord.parental_status.profiles["0"].internet_blocked is False
    assert coord.router.authorize.call_count == 2
    assert coord.router.logout.call_count == 2


def test_unsupported_polling_does_not_request_profiles():
    client = router()
    result = collect_status(client, None, None, None, None, None, None, LOGGER)
    assert result[-1] is None
    client.request.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False])
def test_action_writes_and_reads_under_existing_lock_even_when_paused(enabled):
    coord = coordinator()
    coord.scan_stopped_at = datetime.now()

    def request(path, body):
        assert coord._lock.locked()
        if path == PROFILE_LIST_PATH:
            return [{**RECORD, "internet_blocked": not enabled}]
        return True

    coord.router.request.side_effect = request
    asyncio.run(coord.set_profile_access("0", enabled))
    assert [call.args[0] for call in coord.router.request.call_args_list] == [
        PROFILE_BLOCK_PATH, PROFILE_LIST_PATH,
    ]
    coord.router.authorize.assert_called_once()
    coord.router.logout.assert_called_once()
    coord.async_request_refresh.assert_awaited_once()
    assert coord.scan_stopped_at is not None
    assert coord.parental_status.profiles["0"].internet_blocked is not enabled


def test_write_error_surfaces_without_optimistic_state(caplog):
    coord = coordinator()
    coord.router.request.side_effect = RuntimeError("private profile data")
    with pytest.raises(HomeAssistantError, match="Unable to set"):
        asyncio.run(coord.set_profile_access("0", False))
    assert coord.parental_status == ParentalStatus(None)
    coord.router.logout.assert_called_once()
    coord.async_request_refresh.assert_awaited_once()
    assert "private profile data" not in caplog.text


@pytest.mark.parametrize("response", [None, [], [RECORD]])
def test_failed_or_mismatched_confirmation_surfaces(response):
    coord = coordinator()
    coord.router.request.side_effect = [True, response]
    with pytest.raises(HomeAssistantError, match="could not be confirmed"):
        asyncio.run(coord.set_profile_access("0", False))
    coord.async_request_refresh.assert_awaited_once()


def test_failed_acknowledgement_still_reads_applied_state_for_recovery():
    coord = coordinator()
    coord.router.request.side_effect = [
        RuntimeError("invalid acknowledgement"),
        [{**RECORD, "internet_blocked": True}],
    ]
    with pytest.raises(HomeAssistantError, match="Unable to set"):
        asyncio.run(coord.set_profile_access("0", False))
    assert coord.parental_status.profiles["0"].internet_blocked is True
    assert coord.router.request.call_args.args[0] == PROFILE_LIST_PATH


def test_acknowledgement_is_strictly_boolean():
    client = router()
    for result in (None, {}, "true", 1, False):
        client.request.return_value = result
        with pytest.raises(ValueError, match="acknowledgement"):
            write_profile_access(client, "0", False)
        assert client._data_block == "data"


def test_missing_profile_cannot_be_written():
    coord = coordinator()
    with pytest.raises(HomeAssistantError, match="unavailable"):
        asyncio.run(coord.set_profile_access("missing", True))
    coord.router.request.assert_not_called()


def test_switch_polarity_identity_rename_removal_and_failed_poll():
    coord = coordinator()
    entity = TPLinkParentalAccessSwitch(coord, coord.parental_status.profiles["0"])
    assert entity.unique_id == f"entry-1_{DOMAIN}_parental_access_0"
    assert entity.name == "Example internet access"
    assert entity.is_on is True
    assert entity.available
    coord.parental_status = ParentalStatus({"0": ParentalProfile("0", "Renamed", True)})
    assert entity.name == "Renamed internet access"
    assert entity.is_on is False
    for status in (ParentalStatus({}), ParentalStatus(None), None):
        coord.parental_status = status
        assert not entity.available
        assert entity.is_on is None
        assert entity.name == "Renamed internet access"
    coord.parental_status = ParentalStatus(parse_profiles([RECORD]))
    coord.last_update_success = False
    assert not entity.available


def test_switch_actions_delegate_without_optimistic_mutation():
    from homeassistant.core import Context

    coord = coordinator()
    coord.hass.auth = SimpleNamespace(async_get_user=AsyncMock(
        return_value=SimpleNamespace(is_admin=True, is_active=True),
    ))
    coord.set_profile_access = AsyncMock()
    entity = TPLinkParentalAccessSwitch(coord, coord.parental_status.profiles["0"])
    entity.hass = coord.hass
    entity.async_set_context(Context(user_id="admin"))
    asyncio.run(entity.async_turn_off())
    coord.set_profile_access.assert_awaited_with("0", False)
    assert entity.is_on is True
    asyncio.run(entity.async_turn_on())
    coord.set_profile_access.assert_awaited_with("0", True)


def test_dynamic_discovery_recovery_and_no_duplicates():
    coord = coordinator()
    coord.parental_status = ParentalStatus(None)
    entry = Mock()
    added = []
    setup_parental_entities(coord, entry, lambda entities, update: added.extend(entities))
    listener = coord.async_add_listener.call_args.args[0]
    assert not added
    coord.parental_status = ParentalStatus(parse_profiles([RECORD]))
    listener()
    assert len(added) == 1
    listener()
    assert len(added) == 1
    coord.parental_status = ParentalStatus({})
    listener()
    assert not added[0].available
    coord.parental_status = ParentalStatus(parse_profiles([
        RECORD, {**RECORD, "owner_id": "1"},
    ]))
    listener()
    assert len(added) == 2
    entry.async_on_unload.assert_called_once()


@pytest.mark.parametrize("initial_failure", [False, True])
def test_setup_probes_within_existing_authenticated_callback(initial_failure):
    from custom_components.tplink_router import async_setup_entry
    from test_setup_isolation import FakeHass, _entry, _firmware_status

    client = router()
    if initial_failure:
        client.request.side_effect = TimeoutError
    firmware, status = _firmware_status()
    firmware.model = "Archer AX50"
    client.host = "http://example.invalid"
    client.get_firmware = Mock(return_value=firmware)
    client.get_status = Mock(return_value=status)
    hass = FakeHass()
    entry = _entry(support_vpn=False, support_dhcp_reservations=False,
                   support_serving_cells=False)
    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch(
        "custom_components.tplink_router.collect_mesh_nodes", return_value=None
    ), patch(
        "custom_components.tplink_router.register_services"
    ), patch(
        "custom_components.tplink_router.setup_network_panel", new_callable=AsyncMock,
    ), patch(
        "custom_components.tplink_router._async_add_listeners"
    ), patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ), patch(
        "custom_components.tplink_router.device_registry.async_get", return_value=Mock(),
    ):
        assert asyncio.run(async_setup_entry(hass, entry))
    coord = hass.data[DOMAIN][entry.entry_id]
    if initial_failure:
        assert coord.parental_status == ParentalStatus(None)
    else:
        assert coord.parental_status.profiles["0"].internet_blocked is False
    client.authorize.assert_called_once()
    client.logout.assert_called_once()


@pytest.mark.parametrize("profiles", [None, {}, parse_profiles([RECORD])])
def test_switch_platform_wires_discovery_for_supported_profile_status(profiles):
    from custom_components.tplink_router.switch import async_setup_entry
    from test_switch import _led_coordinator

    coord = _led_coordinator()
    coord.parental_status = ParentalStatus(profiles)
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coord}})
    entry = Mock(entry_id="entry-1")
    added = []
    asyncio.run(async_setup_entry(
        hass, entry, lambda entities, update: added.extend(entities),
    ))
    coord.async_add_listener.assert_called_once()
    assert sum(isinstance(entity, TPLinkParentalAccessSwitch) for entity in added) == (
        1 if profiles else 0
    )
