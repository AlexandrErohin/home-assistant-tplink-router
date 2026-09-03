from __future__ import annotations

from collections.abc import Callable
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from tplinkrouterc6u import MeshNode
from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator


def find_mesh_node(
    coordinator: TPLinkRouterCoordinator, macaddr: str
) -> MeshNode | None:
    if not coordinator.mesh_nodes:
        return None
    return next(
        (item for item in coordinator.mesh_nodes if item.macaddr == macaddr),
        None,
    )


def mesh_device_info(
    coordinator: TPLinkRouterCoordinator, node: MeshNode
) -> DeviceInfo:
    """Describe one mesh unit as its own device.

    The master is the device the coordinator already publishes, so only slaves
    get a via_device link — pointing a device at itself would be rejected.
    """
    info = DeviceInfo(
        connections={(CONNECTION_NETWORK_MAC, node.macaddr)},
        identifiers={(DOMAIN, node.macaddr)},
        manufacturer="TPLink",
        model=node.model,
        name=node.nickname or node.macaddr,
        sw_version=node.firmware_version,
        hw_version=node.hardware_version,
    )
    if not node.is_master:
        info["via_device"] = (DOMAIN, coordinator.status.lan_macaddr)
    return info


@callback
def update_mesh_items(
    coordinator: TPLinkRouterCoordinator,
    async_add_entities: AddEntitiesCallback,
    tracked: set[tuple[str, str]],
    factory: Callable[[TPLinkRouterCoordinator, str], object],
    key: str,
) -> None:
    """Add one entity per mesh unit for the given metric.

    Nodes appear and disappear as units join or leave the mesh, so entities are
    created on coordinator updates rather than at setup. Tracking is keyed by
    (node, metric): one node yields several entities, and a shared set keyed by
    node alone would let the first metric suppress the rest.
    """
    if coordinator.mesh_nodes is None:
        return
    new_entities = []
    for node in coordinator.mesh_nodes:
        marker = (node.macaddr, key)
        if marker in tracked:
            continue
        tracked.add(marker)
        new_entities.append(factory(coordinator, node.macaddr))
    if new_entities:
        async_add_entities(new_entities)
