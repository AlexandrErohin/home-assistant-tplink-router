from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from .const import DOMAIN, CONF_RESERVATIONS_THRESHOLD, DEFAULT_RESERVATIONS_THRESHOLD
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from .port import find_port_status, update_port_items


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    tracked: set[int] = set()

    @callback
    def coordinator_updated():
        update_port_items(
            coordinator,
            async_add_entities,
            tracked,
            TPLinkRouterPortConnectivitySensor,
        )

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()

    reservation_sensor_added = False

    @callback
    def add_reservation_sensor() -> None:
        nonlocal reservation_sensor_added
        if reservation_sensor_added or coordinator.reservation_table is None:
            return
        reservation_sensor_added = True
        async_add_entities([
            TPLinkRouterReservationsNearFullSensor(
                coordinator,
                entry.data.get(CONF_RESERVATIONS_THRESHOLD, DEFAULT_RESERVATIONS_THRESHOLD),
            )
        ])

    entry.async_on_unload(coordinator.async_add_listener(add_reservation_sensor))
    add_reservation_sensor()


class TPLinkRouterReservationsNearFullSensor(CoordinatorEntity[TPLinkRouterCoordinator], BinarySensorEntity):
    """DHCP reservation table is near its capacity (default threshold: 60)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TPLinkRouterCoordinator, threshold: int) -> None:
        super().__init__(coordinator)
        self._threshold = threshold
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_dhcp_reservations_near_full"
        self.entity_description = BinarySensorEntityDescription(
            key="dhcp_reservations_near_full",
            name="DHCP Reservations near full",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @property
    def is_on(self) -> bool | None:
        table = self.coordinator.reservation_table
        if table is None:
            return None
        threshold = min(self._threshold, table.max_rules) if table.max_rules is not None else self._threshold
        return table.used >= threshold

    @property
    def extra_state_attributes(self) -> dict:
        table = self.coordinator.reservation_table
        return {
            "warning_threshold": self._threshold,
            "used": table.used if table else None,
            "max_reservations": table.max_rules if table else None,
            "free": table.free if table else None,
        }


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
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{self.entity_description.key}"

    @property
    def _current_port_status(self):
        return find_port_status(self.coordinator, self._port)

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
