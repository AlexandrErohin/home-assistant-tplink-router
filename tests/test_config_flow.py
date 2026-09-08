import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.data_entry_flow import AbortFlow

from custom_components.tplink_router.config_flow import ConfigFlow
from custom_components.tplink_router.const import (
    CONF_CLIENT_CLASS,
    CONF_SUPPORT_DHCP_RESERVATIONS,
    CONF_SUPPORT_TRACKER,
    CONF_SUPPORT_VPN,
    CONF_TRACKER_AS_DEVICE,
)
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
)


class FakeHass:
    def __init__(self):
        self.data = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _user_input(**overrides):
    data = {
        CONF_HOST: "http://192.168.0.1",
        CONF_PASSWORD: "secret",
        CONF_SCAN_INTERVAL: 30,
        CONF_VERIFY_SSL: False,
    }
    data.update(overrides)
    return data


def _flow():
    flow = ConfigFlow()
    flow.hass = FakeHass()
    return flow


def test_user_step_shows_form_without_input():
    flow = _flow()
    result = asyncio.run(flow.async_step_user())
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert CONF_SUPPORT_VPN not in result["data_schema"].schema


def test_user_step_success_validates_then_shows_custom():
    flow = _flow()
    router = Mock()
    router.__class__.__name__ = "MockRouter"
    status = SimpleNamespace(lan_macaddr="AA:BB:CC:DD:EE:FF")

    with patch.object(
        TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock, return_value=router
    ), patch.object(
        TPLinkRouterCoordinator, "request", return_value=status
    ), patch.object(
        flow, "async_set_unique_id", new_callable=AsyncMock
    ) as set_uid, patch.object(
        flow, "_abort_if_unique_id_configured"
    ) as abort:
        result = asyncio.run(flow.async_step_user(_user_input()))

    set_uid.assert_awaited_once_with("aa:bb:cc:dd:ee:ff")
    abort.assert_called_once()
    assert result["type"] == "form"
    assert result["step_id"] == "custom"
    assert flow.data_initial[CONF_CLIENT_CLASS] == "MockRouter"
    schema_keys = {
        key.schema if hasattr(key, "schema") else key
        for key in result["data_schema"].schema
    }
    assert CONF_SUPPORT_VPN in schema_keys
    assert CONF_TRACKER_AS_DEVICE in schema_keys
    assert CONF_SUPPORT_DHCP_RESERVATIONS in schema_keys


def test_user_step_connection_error_stays_on_user(caplog):
    flow = _flow()
    with patch.object(
        TPLinkRouterCoordinator,
        "get_client",
        new_callable=AsyncMock,
        side_effect=Exception("Cannot authorize!"),
    ):
        with caplog.at_level(logging.ERROR):
            result = asyncio.run(flow.async_step_user(_user_input()))

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "Cannot authorize!"
    assert "TplinkRouter Integration Exception" in caplog.text


def test_user_step_abort_flow_is_not_swallowed():
    flow = _flow()
    router = Mock()
    router.__class__.__name__ = "MockRouter"
    status = SimpleNamespace(lan_macaddr="AA:BB:CC:DD:EE:FF")

    with patch.object(
        TPLinkRouterCoordinator, "get_client", new_callable=AsyncMock, return_value=router
    ), patch.object(
        TPLinkRouterCoordinator, "request", return_value=status
    ), patch.object(
        flow, "async_set_unique_id", new_callable=AsyncMock
    ), patch.object(
        flow,
        "_abort_if_unique_id_configured",
        side_effect=AbortFlow("already_configured"),
    ):
        with pytest.raises(AbortFlow):
            asyncio.run(flow.async_step_user(_user_input()))


def test_custom_step_creates_entry_with_merged_options():
    flow = _flow()
    flow.data_initial = {
        **_user_input(),
        CONF_CLIENT_CLASS: "MockRouter",
    }
    result = asyncio.run(
        flow.async_step_custom(
            {
                CONF_SUPPORT_VPN: False,
                CONF_SUPPORT_TRACKER: False,
                CONF_TRACKER_AS_DEVICE: True,
                CONF_SUPPORT_DHCP_RESERVATIONS: False,
            }
        )
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "http://192.168.0.1"
    assert result["data"][CONF_SUPPORT_VPN] is False
    assert result["data"][CONF_SUPPORT_TRACKER] is False
    assert result["data"][CONF_TRACKER_AS_DEVICE] is True
    assert result["data"][CONF_SUPPORT_DHCP_RESERVATIONS] is False
    assert result["data"][CONF_CLIENT_CLASS] == "MockRouter"
