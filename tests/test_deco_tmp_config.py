import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from tplinkrouterc6u import TPLinkDecoClient

from custom_components.tplink_router import (
    DecoTmpConfigurationError,
    async_setup_entry,
    configure_deco_tmp_wifi,
    validate_deco_tmp_config,
)
from custom_components.tplink_router.config_flow import ConfigFlow, OptionsFlow
from custom_components.tplink_router.const import (
    CONF_DECO_TMP_HOST_KEY_SHA256,
    CONF_DECO_TMP_USERNAME,
)
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator


USERNAME = "a" * 40
PIN = "SHA256:" + base64.b64encode(bytes(range(32))).decode().rstrip("=")
TMP_DATA = {CONF_DECO_TMP_USERNAME: USERNAME, CONF_DECO_TMP_HOST_KEY_SHA256: PIN}


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
        "host": "http://192.168.0.1",
        "password": "unit-test-password",
        "username": "admin",
        "verify_ssl": False,
        "client_class": "TPLinkDecoClient",
        "scan_interval": 30,
        **overrides,
    }
    entry.options = {}
    entry.async_on_unload = Mock()
    entry.add_update_listener = Mock(return_value=Mock())
    return entry


def _client():
    client = TPLinkDecoClient.__new__(TPLinkDecoClient)
    client.host = "http://192.168.0.1"
    client.configure_tmp_wifi = Mock()
    return client


def _options_flow(entry):
    with patch("homeassistant.config_entries.report_usage"):
        flow = OptionsFlow(entry)
    flow.hass = FakeHass()
    flow.handler = entry.entry_id
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    return flow


@pytest.mark.parametrize("data", [{}, {CONF_DECO_TMP_USERNAME: "", CONF_DECO_TMP_HOST_KEY_SHA256: ""}])
def test_absent_app_control_keeps_legacy_configuration(data):
    assert validate_deco_tmp_config(data) is None
    unrelated_router = Mock()
    configure_deco_tmp_wifi(unrelated_router, data)
    unrelated_router.configure_tmp_wifi.assert_not_called()


@pytest.mark.parametrize("data", [
    {CONF_DECO_TMP_USERNAME: USERNAME},
    {CONF_DECO_TMP_HOST_KEY_SHA256: PIN},
    {**TMP_DATA, CONF_DECO_TMP_USERNAME: "invalid-account-value"},
    {**TMP_DATA, CONF_DECO_TMP_USERNAME: False},
    {**TMP_DATA, CONF_DECO_TMP_HOST_KEY_SHA256: "SHA256:invalid"},
    {**TMP_DATA, CONF_DECO_TMP_HOST_KEY_SHA256: PIN[:-1] + "/"},
    {**TMP_DATA, CONF_DECO_TMP_HOST_KEY_SHA256: PIN + "="},
    {**TMP_DATA, CONF_DECO_TMP_HOST_KEY_SHA256: "0" * 64},
])
def test_incomplete_or_invalid_app_configuration_is_rejected_without_private_values(data):
    with pytest.raises(DecoTmpConfigurationError) as raised:
        validate_deco_tmp_config(data)
    assert "invalid-account-value" not in str(raised.value)
    assert PIN not in str(raised.value)


def test_valid_app_control_passes_normalized_hash_and_verified_pin_without_connecting():
    client = _client()
    configure_deco_tmp_wifi(client, {**TMP_DATA, CONF_DECO_TMP_USERNAME: USERNAME.upper()})
    client.configure_tmp_wifi.assert_called_once_with(username_sha1=USERNAME, host_key_sha256=PIN)


@pytest.mark.parametrize("client", [Mock(), None])
def test_app_control_rejects_an_unrelated_client(client):
    with pytest.raises(DecoTmpConfigurationError, match="not supported"):
        configure_deco_tmp_wifi(client, TMP_DATA)


def test_app_control_rejects_a_deco_client_without_configuration_api():
    client = _client()
    client.configure_tmp_wifi = None
    with pytest.raises(DecoTmpConfigurationError, match="not supported"):
        configure_deco_tmp_wifi(client, TMP_DATA)


def test_app_control_rejects_a_deco_with_an_unsupported_transport():
    class UnsupportedDeco(TPLinkDecoClient):
        supports_verified_wifi = False

    client = UnsupportedDeco.__new__(UnsupportedDeco)
    client.configure_tmp_wifi = Mock()
    with pytest.raises(DecoTmpConfigurationError, match="not supported"):
        configure_deco_tmp_wifi(client, TMP_DATA)
    client.configure_tmp_wifi.assert_not_called()


def test_binding_validation_error_does_not_expose_private_error_context():
    client = _client()
    client.configure_tmp_wifi.side_effect = ValueError("private-error-details")
    with pytest.raises(DecoTmpConfigurationError) as raised:
        configure_deco_tmp_wifi(client, TMP_DATA)
    assert "private-error-details" not in str(raised.value)
    assert raised.value.__suppress_context__ is True


def test_partial_app_configuration_fails_setup_before_router_discovery(caplog):
    hass = FakeHass()
    entry = _entry(**{CONF_DECO_TMP_USERNAME: USERNAME})
    with patch.object(TPLinkRouterCoordinator, "get_client_by_class") as factory:
        assert asyncio.run(async_setup_entry(hass, entry)) is False
    factory.assert_not_called()
    assert "Deco app control requires" in caplog.text
    assert USERNAME not in caplog.text


def test_setup_binds_app_control_to_the_same_client_before_normal_status_reads():
    hass = FakeHass()
    entry = _entry(**TMP_DATA)
    client = _client()
    firmware = SimpleNamespace(model="BE65", firmware_version="test", hardware_version="2.0")
    status = SimpleNamespace(lan_macaddr="00:11:22:33:44:55")
    values = (firmware, status, None, None, None, None, None, None, None, None, None, None, None)

    def status_request(router, callback):
        assert router is client
        client.configure_tmp_wifi.assert_called_once_with(username_sha1=USERNAME, host_key_sha256=PIN)
        return values

    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch.object(
        TPLinkRouterCoordinator, "request", side_effect=status_request
    ), patch(
        "custom_components.tplink_router._async_add_listeners"
    ), patch(
        "custom_components.tplink_router.register_services"
    ), patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__", return_value=None
    ), patch(
        "custom_components.tplink_router.device_registry.async_get", return_value=Mock()
    ):
        assert asyncio.run(async_setup_entry(hass, entry)) is True
    assert hass.data["tplink_router"][entry.entry_id].router is client


def test_user_flow_rejects_partial_configuration_before_network_access():
    flow = ConfigFlow()
    flow.hass = FakeHass()
    data = _entry(**{CONF_DECO_TMP_USERNAME: USERNAME}).data
    with patch.object(TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock) as factory:
        result = asyncio.run(flow.async_step_user(data))
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_deco_tmp_config"
    factory.assert_not_called()


def test_user_flow_preserves_app_control_settings_for_the_created_entry():
    flow = ConfigFlow()
    flow.hass = FakeHass()
    client = _client()
    with patch.object(
        TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock, return_value=client
    ), patch.object(
        TPLinkRouterCoordinator, "request", return_value=SimpleNamespace(lan_macaddr="00:11:22:33:44:55")
    ), patch.object(
        flow, "async_set_unique_id", new_callable=AsyncMock
    ), patch.object(flow, "_abort_if_unique_id_configured"):
        result = asyncio.run(flow.async_step_user(_entry(**TMP_DATA).data))
    assert result["type"] == "form"
    assert result["step_id"] == "custom"
    assert flow.data_initial[CONF_DECO_TMP_USERNAME] == USERNAME
    assert flow.data_initial[CONF_DECO_TMP_HOST_KEY_SHA256] == PIN
    client.configure_tmp_wifi.assert_called_once_with(username_sha1=USERNAME, host_key_sha256=PIN)


def test_options_edit_preserves_existing_app_control_and_unrelated_settings():
    entry = _entry(**TMP_DATA, future_option="keep")
    flow = _options_flow(entry)
    client = _client()
    with patch.object(
        TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock, return_value=client
    ), patch.object(TPLinkRouterCoordinator, "request", return_value=Mock()):
        result = asyncio.run(flow.async_step_init({"scan_interval": 60}))
    assert result["type"] == "create_entry"
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_DECO_TMP_USERNAME] == USERNAME
    assert saved[CONF_DECO_TMP_HOST_KEY_SHA256] == PIN
    assert saved["future_option"] == "keep"
    assert saved["scan_interval"] == 60
    client.configure_tmp_wifi.assert_called_once_with(username_sha1=USERNAME, host_key_sha256=PIN)


def test_options_edit_can_explicitly_clear_both_app_control_fields():
    entry = _entry(**TMP_DATA)
    flow = _options_flow(entry)
    client = Mock()
    with patch.object(
        TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock, return_value=client
    ), patch.object(TPLinkRouterCoordinator, "request", return_value=Mock()):
        result = asyncio.run(flow.async_step_init({
            CONF_DECO_TMP_USERNAME: "", CONF_DECO_TMP_HOST_KEY_SHA256: "",
        }))
    assert result["type"] == "create_entry"
    saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_DECO_TMP_USERNAME] == ""
    assert saved[CONF_DECO_TMP_HOST_KEY_SHA256] == ""
    client.configure_tmp_wifi.assert_not_called()


def test_options_edit_rejects_clearing_only_the_pin_without_router_access():
    flow = _options_flow(_entry(**TMP_DATA))
    with patch.object(TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock) as factory:
        result = asyncio.run(flow.async_step_init({CONF_DECO_TMP_HOST_KEY_SHA256: ""}))
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_deco_tmp_config"
    factory.assert_not_called()
