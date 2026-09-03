import logging
from unittest.mock import Mock

from macaddress import EUI48
from ipaddress import IPv4Address
from tplinkrouterc6u import MeshNode

from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.coordinator import collect_status
from custom_components.tplink_router.mesh import (
    find_mesh_node,
    mesh_device_info,
    update_mesh_items,
)

MASTER_MAC = "F0-09-0D-FA-29-7C"
SLAVE_MAC = "F0-09-0D-FA-29-84"


def _node(macaddr: str, nickname: str, role: str, **kwargs) -> MeshNode:
    return MeshNode(
        _macaddr=EUI48(macaddr),
        nickname=nickname,
        role=role,
        model="X50",
        _ipaddr=IPv4Address(kwargs.pop("ip", "192.168.68.1")),
        hardware_version="1.0",
        firmware_version="1.8.0 Build 25102213 Rel. 43970",
        **kwargs,
    )


def _coordinator(nodes):
    coordinator = Mock()
    coordinator.mesh_nodes = nodes
    coordinator.status.lan_macaddr = MASTER_MAC
    return coordinator


class RouterWithoutMesh:
    def get_status(self):
        return "STATUS_OK"


class RouterWithMesh(RouterWithoutMesh):
    def __init__(self):
        self.calls = 0

    def get_mesh_nodes(self):
        self.calls += 1
        return [_node(MASTER_MAC, "Living Room", "master")]


def test_collect_status_skips_mesh_when_unsupported():
    """Non-mesh routers have no get_mesh_nodes, and must not break."""
    result = collect_status(
        RouterWithoutMesh(), None, None, None, None, None, logging.getLogger("test")
    )
    assert result[7] is None


def test_collect_status_fetches_mesh_when_supported():
    router = RouterWithMesh()
    result = collect_status(
        router, None, None, None, None, None, logging.getLogger("test")
    )
    assert router.calls == 1
    assert len(result[7]) == 1
    assert result[7][0].nickname == "Living Room"


def test_collect_status_survives_mesh_failure():
    """A failing mesh read must not take the whole update down."""
    router = RouterWithoutMesh()
    router.get_mesh_nodes = Mock(side_effect=RuntimeError("router busy"))
    result = collect_status(
        router, None, None, None, None, None, logging.getLogger("test")
    )
    assert result[0] == "STATUS_OK"
    assert result[7] is None


def test_find_mesh_node():
    nodes = [_node(MASTER_MAC, "Living Room", "master")]
    coordinator = _coordinator(nodes)

    assert find_mesh_node(coordinator, MASTER_MAC).nickname == "Living Room"
    assert find_mesh_node(coordinator, SLAVE_MAC) is None
    assert find_mesh_node(_coordinator(None), MASTER_MAC) is None


def test_mesh_device_info_master_has_no_via_device():
    """A device cannot be its own parent."""
    node = _node(MASTER_MAC, "Living Room", "master")
    info = mesh_device_info(_coordinator([node]), node)

    assert info["identifiers"] == {(DOMAIN, MASTER_MAC)}
    assert info["name"] == "Living Room"
    assert "via_device" not in info


def test_mesh_device_info_slave_links_to_master():
    node = _node(SLAVE_MAC, "Kids", "slave", ip="192.168.71.250")
    info = mesh_device_info(_coordinator([node]), node)

    assert info["name"] == "Kids"
    assert info["via_device"] == (DOMAIN, MASTER_MAC)


def test_mesh_device_info_falls_back_to_mac_without_nickname():
    node = _node(SLAVE_MAC, "", "slave")
    assert mesh_device_info(_coordinator([node]), node)["name"] == SLAVE_MAC


def test_update_mesh_items_tracks_node_and_metric_separately():
    """One node yields several entities, so tracking cannot key on node alone."""
    nodes = [
        _node(MASTER_MAC, "Living Room", "master"),
        _node(SLAVE_MAC, "Kids", "slave", ip="192.168.71.250"),
    ]
    coordinator = _coordinator(nodes)
    added = []
    tracked = set()

    def add_entities(entities):
        added.extend(entities)

    for key in ("signal_2g", "signal_5g"):
        update_mesh_items(coordinator, add_entities, tracked, lambda c, m: (m, key), key=key)

    assert len(added) == 4
    assert tracked == {
        (MASTER_MAC, "signal_2g"), (SLAVE_MAC, "signal_2g"),
        (MASTER_MAC, "signal_5g"), (SLAVE_MAC, "signal_5g"),
    }

    # A second pass must not duplicate anything.
    update_mesh_items(coordinator, add_entities, tracked, lambda c, m: m, key="signal_2g")
    assert len(added) == 4


def test_update_mesh_items_noop_without_mesh():
    added = []
    update_mesh_items(_coordinator(None), added.extend, set(), lambda c, m: m, key="signal_2g")
    assert added == []
