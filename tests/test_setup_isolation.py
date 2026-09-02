import asyncio
import logging
from unittest.mock import Mock, patch

import pytest

from custom_components.tplink_router import async_setup_entry
from custom_components.tplink_router.coordinator import TPLinkRouterCoordinator


class FakeHass:
    data = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def test_coordinator_retries_but_does_not_retry_auth_errors():
    """The retry loop must not retry AuthorizeError (bad credentials)."""
    router = Mock()
    router.authorize.side_effect = Exception("TplinkRouter - Cannot authorize! Error - 'data'")
    router.logout.side_effect = None

    coord = TPLinkRouterCoordinator.__new__(TPLinkRouterCoordinator)
    coord.hass = FakeHass()
    coord.router = router
    coord.retries = 3
    coord.backoff_seconds = 0
    coord._lock = asyncio.Lock()
    coord.scan_stopped_at = None
    coord.status = Mock()
    coord.lte_status = None
    coord.serving_cells = None
    coord.vpn_server_status = None
    coord.vpn_client_status = None
    coord.port_status = None
    coord.logger = logging.getLogger("test")

    with pytest.raises(Exception, match="Cannot authorize"):
        asyncio.run(coord._async_update_data())
    assert router.authorize.call_count == 1


def test_async_setup_entry_returns_false_when_initial_request_fails():
    """A failing initial request must fail this entry gracefully, not raise."""
    hass = FakeHass()
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
    client = Mock()
    with patch.object(
        TPLinkRouterCoordinator, "get_client_by_class", return_value=Mock(return_value=client)
    ), patch.object(
        TPLinkRouterCoordinator, "request", side_effect=Exception("Cannot authorize!")
    ):
        assert asyncio.run(async_setup_entry(hass, entry)) is False
