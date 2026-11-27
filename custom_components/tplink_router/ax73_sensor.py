"""AX73 diagnostics from the client data already fetched by the coordinator."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import EntityCategory, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfDataRate, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from tplinkrouterc6u import Device

from .coordinator import TPLinkRouterCoordinator


CLIENT_SENSOR_TYPES = (
    SensorEntityDescription(key="band", name="AX73 Wi-Fi band", entity_category=EntityCategory.DIAGNOSTIC),
    *(
        SensorEntityDescription(
            key=f"{direction}_rate",
            name=f"AX73 Wi-Fi {direction.upper()} link rate",
            device_class=SensorDeviceClass.DATA_RATE,
            native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for direction in ("rx", "tx")
    ),
    SensorEntityDescription(
        key="signal",
        name="AX73 Wi-Fi RSSI",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *(
        SensorEntityDescription(
            key=f"packets_{direction}",
            name=f"AX73 Packets {direction}",
            native_unit_of_measurement="packets",
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for direction in ("sent", "received")
    ),
    SensorEntityDescription(
        key="online_time",
        name="AX73 Online time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _wifi_clients(coordinator: TPLinkRouterCoordinator) -> list[Device]:
    return [
        client for client in coordinator.status.devices
        if client.macaddr and client.active is not False and client.type.get_band() is not None
    ]


def _client_value(client: Device, key: str) -> int | float | str | None:
    if key == "band":
        return client.type.get_band()
    value = getattr(client, key)
    if key in ("rx_rate", "tx_rate"):
        # The same conversion as the AX73 web UI: kbit/s to Mbit/s.
        return round(value / 1000, 3) if value is not None and value >= 0 else None
    return value


@callback
def update_ax73_client_sensors(
    coordinator: TPLinkRouterCoordinator,
    async_add_entities: AddEntitiesCallback,
    tracked: set[tuple[str, str]],
) -> None:
    """Register each diagnostic after the router first reports its metric."""
    new_entities = []
    for client in _wifi_clients(coordinator):
        for description in CLIENT_SENSOR_TYPES:
            key = (client.macaddr, description.key)
            if key not in tracked and _client_value(client, description.key) is not None:
                tracked.add(key)
                new_entities.append(AX73WifiClientSensor(coordinator, client, description))
    if new_entities:
        async_add_entities(new_entities)


class AX73WifiClientsSensor(CoordinatorEntity[TPLinkRouterCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "AX73 Wi-Fi clients"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"clients"})

    def __init__(self, coordinator: TPLinkRouterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_ax73_device_clients"

    @property
    def native_value(self) -> int:
        return len(_wifi_clients(self.coordinator))

    @property
    def extra_state_attributes(self) -> dict:
        clients = sorted(_wifi_clients(self.coordinator), key=lambda client: client.macaddr)
        return {
            "source": "AX73",
            "clients": [
                {
                    "mac": client.macaddr,
                    "ip": client.ipaddr if client.ipaddr != "0.0.0.0" else None,
                    "name": client.hostname or client.macaddr,
                    **{description.key: _client_value(client, description.key) for description in CLIENT_SENSOR_TYPES},
                    "ap_name": client.ap_name,
                }
                for client in clients
            ],
            "rate_unit": UnitOfDataRate.MEGABITS_PER_SECOND,
        }


class AX73WifiClientSensor(CoordinatorEntity[TPLinkRouterCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: TPLinkRouterCoordinator, client: Device, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self._mac = client.macaddr
        self.entity_description = description
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, client.macaddr)}, name=client.hostname or client.macaddr
        )
        self._attr_unique_id = f"{coordinator.unique_id}_ax73_{client.macaddr}_{description.key}"

    @property
    def native_value(self) -> int | float | str | None:
        client = next((client for client in _wifi_clients(self.coordinator) if client.macaddr == self._mac), None)
        return _client_value(client, self.entity_description.key) if client is not None else None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None
