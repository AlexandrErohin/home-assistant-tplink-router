import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from custom_components.tplink_router.const import DEFAULT_SCAN_PAUSE
from custom_components.tplink_router.coordinator import (
    TPLinkRouterCoordinator,
    collect_mesh_devices,
    collect_status,
)


class FakeHass:
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class FakeRouter:
    def __init__(self):
        self.status = "STATUS_OK"
        self.lte = "LTE_OK"
        self.ports = ["PORT_OK"]
        self.port_calls = 0

    def get_status(self):
        return self.status

    def get_lte_status(self):
        return self.lte

    def get_port_status(self):
        self.port_calls += 1
        return self.ports

    def get_sms(self):
        raise RuntimeError("inbox too big")


def _bare_coordinator(**overrides):
    router = Mock()
    router.authorize.side_effect = Exception(
        "TplinkRouter - Cannot authorize! Error - 'data'"
    )
    router.logout.side_effect = None

    coord = TPLinkRouterCoordinator.__new__(TPLinkRouterCoordinator)
    coord.hass = FakeHass()
    coord.router = router
    coord.retries = 3
    coord.backoff_seconds = 0
    coord.scan_pause_minutes = DEFAULT_SCAN_PAUSE
    coord._lock = asyncio.Lock()
    coord.scan_stopped_at = None
    coord.status = Mock()
    coord.lte_status = None
    coord.serving_cells = None
    coord.vpn_server_status = None
    coord.vpn_client_status = None
    coord.port_status = None
    coord.logger = logging.getLogger("test")
    for key, value in overrides.items():
        setattr(coord, key, value)
    return coord, router


def test_collect_status_ignores_sms_failure():
    router = FakeRouter()
    result = collect_status(
        router, object(), None, None, None, None, None, logging.getLogger("test")
    )
    assert result[0] == "STATUS_OK"
    assert result[5] is None
    assert result[7] is None


def test_collect_status_does_not_call_get_sms_without_lte():
    router = FakeRouter()
    result = collect_status(
        router, None, None, None, None, None, None, logging.getLogger("test")
    )
    assert result[0] == "STATUS_OK"
    assert result[1] is None
    assert result[7] is None


def test_collect_status_refreshes_port_status_when_enabled():
    router = FakeRouter()
    result = collect_status(
        router, None, None, None, None, [], None, logging.getLogger("test")
    )
    assert result[5] == ["PORT_OK"]
    assert router.port_calls == 1


def test_collect_status_skips_port_status_when_disabled():
    router = FakeRouter()
    result = collect_status(
        router, None, None, None, None, None, None, logging.getLogger("test")
    )
    assert result[5] is None
    assert router.port_calls == 0


def test_scan_pause_default_is_twenty_minutes():
    assert DEFAULT_SCAN_PAUSE == 20


def test_coordinator_retries_but_does_not_retry_auth_errors():
    """The retry loop must not retry permanent auth failures."""
    coord, router = _bare_coordinator()
    with pytest.raises(Exception, match="Cannot authorize"):
        asyncio.run(coord._async_update_data())
    assert router.authorize.call_count == 1


def test_scan_pause_zero_keeps_fetching_disabled():
    """scan_pause=0 must not auto-clear scan_stopped_at."""
    coord, router = _bare_coordinator(
        scan_pause_minutes=0,
        scan_stopped_at=datetime.now() - timedelta(days=1),
    )
    assert asyncio.run(coord._async_update_data()) is None
    assert router.authorize.call_count == 0
    assert coord.scan_stopped_at is not None


def test_scan_pause_expires_and_resumes_fetching():
    coord, router = _bare_coordinator(
        scan_pause_minutes=20,
        scan_stopped_at=datetime.now() - timedelta(minutes=21),
    )
    with pytest.raises(Exception, match="Cannot authorize"):
        asyncio.run(coord._async_update_data())
    assert router.authorize.call_count == 1
    assert coord.scan_stopped_at is None


def test_collect_mesh_devices_returns_none_when_the_client_lacks_the_method():
    """An older tplinkrouterc6u has no get_mesh_devices; asking again is pointless."""
    class OldRouter:
        pass

    assert collect_mesh_devices(OldRouter(), logging.getLogger("test")) is None


def test_collect_mesh_devices_returns_none_on_not_implemented():
    """Clients using the AbstractRouter default must not be polled every cycle."""
    class Unsupported:
        def get_mesh_devices(self):
            raise NotImplementedError("nope")

    assert collect_mesh_devices(Unsupported(), logging.getLogger("test")) is None


def test_collect_mesh_devices_returns_empty_list_on_transient_failure():
    """A transient error must not permanently disable the node list."""
    class Flaky:
        def get_mesh_devices(self):
            raise TimeoutError("boom")

    assert collect_mesh_devices(Flaky(), logging.getLogger("test")) == []


def test_collect_mesh_devices_passes_the_node_list_through():
    class MeshRouter:
        def get_mesh_devices(self):
            return ["NODE"]

    assert collect_mesh_devices(MeshRouter(), logging.getLogger("test")) == ["NODE"]


def test_collect_status_skips_mesh_when_disabled():
    router = FakeRouter()
    router.get_mesh_devices = lambda: ["NODE"]

    result = collect_status(
        router, None, None, None, None, None, None, logging.getLogger("test")
    )

    assert result[6] is None


def test_collect_status_fetches_mesh_when_enabled():
    router = FakeRouter()
    router.get_mesh_devices = lambda: ["NODE"]

    result = collect_status(
        router, None, None, None, None, None, [], logging.getLogger("test")
    )

    assert result[6] == ["NODE"]
