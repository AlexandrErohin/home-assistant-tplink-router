from __future__ import annotations

from collections.abc import Callable
from typing import Any
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
try:
    from tplinkrouterc6u import MeshNode
except ImportError:  # pragma: no cover - older tplinkrouterc6u without mesh
    MeshNode = object  # type: ignore[misc, assignment]
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
    """Link to the node's device, which the mesh node tracker owns and describes."""
    if node.is_main_router:
        return coordinator.device_info
    return DeviceInfo(identifiers={(DOMAIN, node.macaddr)})


@callback
def update_mesh_items(
    coordinator: TPLinkRouterCoordinator,
    async_add_entities: AddEntitiesCallback,
    tracked: set[tuple[str, str]],
    factory: Callable[[TPLinkRouterCoordinator, str], object],
    *,
    key: str,
    value: Callable[[MeshNode], Any],
) -> None:
    """Add one entity per mesh node for this metric, once the node reports a value for it."""
    if coordinator.mesh_nodes is None:
        return
    new_entities = []
    for node in coordinator.mesh_nodes:
        # Keyed by (node, metric): one node yields several entities.
        marker = (node.macaddr, key)
        if marker in tracked or value(node) is None:
            continue
        tracked.add(marker)
        new_entities.append(factory(coordinator, node.macaddr))
    if new_entities:
        async_add_entities(new_entities)
