from unittest.mock import Mock

from macaddress import EUI48
from ipaddress import IPv4Address
from tplinkrouterc6u import MeshNode

from custom_components.tplink_router.const import DOMAIN
from custom_components.tplink_router.mesh import (
    find_mesh_node,
    mesh_device_info,
    update_mesh_items,
)

MASTER_MAC = "F0-09-0D-FA-29-7C"
SLAVE_MAC = "F0-09-0D-FA-29-84"


def _node(macaddr: str, name: str, role: str, **kwargs) -> MeshNode:
    return MeshNode(
        _macaddr=EUI48(macaddr),
        name=name,
        role=role,
        model="X50",
        _ipaddr=IPv4Address(kwargs.pop("ip", "192.168.68.1")),
        hardware_version="1.0",
        firmware_version="1.8.0 Build 25102213 Rel. 43970",
        **kwargs,
    )


def _reported(node: MeshNode) -> int:
    return 0


def _coordinator(nodes):
    coordinator = Mock()
    coordinator.mesh_nodes = nodes
    return coordinator


def test_find_mesh_node():
    nodes = [_node(MASTER_MAC, "Living Room", "master")]
    coordinator = _coordinator(nodes)

    assert find_mesh_node(coordinator, MASTER_MAC).name == "Living Room"
    assert find_mesh_node(coordinator, SLAVE_MAC) is None
    assert find_mesh_node(_coordinator(None), MASTER_MAC) is None


def test_mesh_device_info_main_router_joins_coordinator_device():
    """The main router's tracker joins the coordinator device, so its sensors must too."""
    node = _node(MASTER_MAC, "Living Room", "master")
    coordinator = _coordinator([node])

    assert mesh_device_info(coordinator, node) is coordinator.device_info


def test_mesh_device_info_satellite_links_by_identifier_only():
    """The node tracker owns the device's name, model and parent; sensors only link to it."""
    node = _node(SLAVE_MAC, "Kids", "slave", ip="192.168.71.250")

    assert mesh_device_info(_coordinator([node]), node) == {"identifiers": {(DOMAIN, SLAVE_MAC)}}


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
        update_mesh_items(coordinator, add_entities, tracked, lambda c, m: (m, key), key=key, value=_reported)

    assert len(added) == 4
    assert tracked == {
        (MASTER_MAC, "signal_2g"), (SLAVE_MAC, "signal_2g"),
        (MASTER_MAC, "signal_5g"), (SLAVE_MAC, "signal_5g"),
    }

    # A second pass must not duplicate anything.
    update_mesh_items(coordinator, add_entities, tracked, lambda c, m: m, key="signal_2g", value=_reported)
    assert len(added) == 4


def test_update_mesh_items_noop_without_mesh():
    added = []
    update_mesh_items(_coordinator(None), added.extend, set(), lambda c, m: m, key="signal_2g", value=_reported)
    assert added == []


def test_update_mesh_items_waits_until_the_node_reports_the_metric():
    """No always-unknown entity for a metric the node lacks (EasyMesh, or the main router's backhaul)."""
    node = _node(SLAVE_MAC, "Kids", "slave", ip="192.168.71.250")
    coordinator = _coordinator([node])
    added = []
    tracked = set()

    def signal_5g(n):
        return n.signal_5g

    update_mesh_items(coordinator, added.extend, tracked, lambda c, m: m, key="signal_5g", value=signal_5g)
    assert added == []

    node.signal_5g = -49
    update_mesh_items(coordinator, added.extend, tracked, lambda c, m: m, key="signal_5g", value=signal_5g)
    assert added == [SLAVE_MAC]
