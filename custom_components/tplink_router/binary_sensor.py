from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from .const import DOMAIN
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    tracked: set[int] = set()

    @callback
    def coordinator_updated():
        update_items(coordinator, async_add_entities, tracked)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()


@callback
def update_items(
        coordinator: TPLinkRouterCoordinator,
        async_add_entities: AddEntitiesCallback,
        tracked: set[int],
) -> None:
    if coordinator.port_status is None:
        return
    new_sensors = []
    for port in coordinator.port_status:
        if port.port in tracked:
            continue
        tracked.add(port.port)
        new_sensors.append(TPLinkRouterPortConnectivitySensor(coordinator, port.port))
    if new_sensors:
        async_add_entities(new_sensors)


class TPLinkRouterPortConnectivitySensor(CoordinatorEntity[TPLinkRouterCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TPLinkRouterCoordinator,
        port: int
    ) -> None:
        super().__init__(coordinator)

        self._port = port
        self._attr_device_info = coordinator.device_info
        self.entity_description = BinarySensorEntityDescription(
            key=f"port_{port}_connectivity",
            name=f"Port {port} connectivity",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        )
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{self.entity_description.key}"

    @property
    def _current_port_status(self):
        if not self.coordinator.port_status:
            return None
        return next((item for item in self.coordinator.port_status if item.port == self._port), None)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        port_status = self._current_port_status
        if port_status is None:
            return None
        return port_status.link_up

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self._current_port_status is not None
