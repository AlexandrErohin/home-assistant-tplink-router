from __future__ import annotations

from collections.abc import Callable
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from tplinkrouterc6u import PortStatus
from .coordinator import TPLinkRouterCoordinator


def find_port_status(
    coordinator: TPLinkRouterCoordinator, port: int
) -> PortStatus | None:
    if not coordinator.port_status:
        return None
    return next(
        (item for item in coordinator.port_status if item.port == port),
        None,
    )


@callback
def update_port_items(
    coordinator: TPLinkRouterCoordinator,
    async_add_entities: AddEntitiesCallback,
    tracked: set[int],
    factory: Callable[[TPLinkRouterCoordinator, int], object],
) -> None:
    if coordinator.port_status is None:
        return
    new_entities = []
    for port in coordinator.port_status:
        if port.port in tracked:
            continue
        tracked.add(port.port)
        new_entities.append(factory(coordinator, port.port))
    if new_entities:
        async_add_entities(new_entities)
