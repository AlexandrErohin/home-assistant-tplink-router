from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from homeassistant.components.sensor import (
    SensorStateClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, BYTES_PER_SECOND, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from .const import DOMAIN
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from tplinkrouterc6u import Status, IPv4Status, LTEStatus


@dataclass
class TPLinkRouterSensorRequiredKeysMixin:
    value: Callable[[Status,IPv4Status, LTEStatus], Any]

@dataclass
class TPLinkRouterSensorEntityDescription(
    SensorEntityDescription, TPLinkRouterSensorRequiredKeysMixin
):
    """A class that describes sensor entities."""

    sensor_type: str = "status"


SENSOR_TYPES: tuple[TPLinkRouterSensorEntityDescription, ...] = (
    TPLinkRouterSensorEntityDescription(
        key="guest_wifi_clients_total",
        name="Total guest wifi clients",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.guest_clients_total,
    ),
    TPLinkRouterSensorEntityDescription(
        key="wifi_clients_total",
        name="Total main wifi clients",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.wifi_clients_total,
    ),
    TPLinkRouterSensorEntityDescription(
        key="wired_clients_total",
        name="Total wired clients",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.wired_total,
    ),
    TPLinkRouterSensorEntityDescription(
        key="iot_clients_total",
        name="Total IoT clients",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.iot_clients_total,
    ),
    TPLinkRouterSensorEntityDescription(
        key="clients_total",
        name="Total clients",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.clients_total,
    ),
    TPLinkRouterSensorEntityDescription(
        key="cpu_used",
        name="CPU used",
        icon="mdi:cpu-64-bit",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value=lambda status: (status.cpu_usage * 100) if status.cpu_usage is not None else None,
    ),
    TPLinkRouterSensorEntityDescription(
        key="memory_used",
        name="Memory used",
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value=lambda status: (status.mem_usage * 100) if status.mem_usage is not None else None,
    ),
    TPLinkRouterSensorEntityDescription(
        key="conn_type",
        name="Connection Type",
        icon="mdi:wan",
        value=lambda status: status.conn_type,
    ),
    TPLinkRouterSensorEntityDescription(
        key="enable",
        name="LTE Enabled",
        icon="mdi:sim-outline",
        value=lambda status: status.enable,
    ),
    TPLinkRouterSensorEntityDescription(
        key="connect_status",
        name="LTE Connection Status",
        icon="mdi:sim-outline",
        value=lambda status: status.connect_status,
    ),
    TPLinkRouterSensorEntityDescription(
        key="network_type",
        name="LTE Network Type",
        icon="mdi:sim-outline",
        value=lambda status: status.network_type,
    ),
    TPLinkRouterSensorEntityDescription(
        key="sim_status",
        name="LTE SIM Status",
        icon="mdi:sim-outline",
        value=lambda status: status.sim_status,
    ),
    TPLinkRouterSensorEntityDescription(
        key="total_statistics",
        name="LTE Total Statistics",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.total_statistics,
    ),
    TPLinkRouterSensorEntityDescription(
        key="cur_rx_speed",
        name="LTE Current RX Speed",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=BYTES_PER_SECOND,
        value=lambda status: status.cur_rx_speed,
    ),
    TPLinkRouterSensorEntityDescription(
        key="cur_tx_speed",
        name="LTE Current TX Speed",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=BYTES_PER_SECOND,
        value=lambda status: status.cur_tx_speed,
    ),
    TPLinkRouterSensorEntityDescription(
        key="sms_unread_count",
        name="Unread SMS",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.TOTAL,
        value=lambda status: status.sms_unread_count,
    ),
    TPLinkRouterSensorEntityDescription(
        key="sig_level",
        name="LTE Signal Level",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda status: status.sig_level,
    ),
    TPLinkRouterSensorEntityDescription(
        key="rsrp",
        name="LTE RSRP",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        value=lambda status: status.rsrp,
    ),
    TPLinkRouterSensorEntityDescription(
        key="rsrq",
        name="LTE RSRQ",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        value=lambda status: status.rsrq,
    ),
    TPLinkRouterSensorEntityDescription(
        key="snr",
        name="LTE SNR",
        icon="mdi:sim-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        value=lambda status: status.snr,
    ),
    TPLinkRouterSensorEntityDescription(
        key="isp_name",
        name="LTE ISP Name",
        icon="mdi:sim-outline",
        value=lambda status: status.isp_name,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []

    for description in SENSOR_TYPES:
        sensors.append(TPLinkRouterSensor(coordinator, description))

    async_add_entities(sensors, False)


class TPLinkRouterSensor(
    CoordinatorEntity[TPLinkRouterCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    entity_description: TPLinkRouterSensorEntityDescription

    def __init__(
            self,
            coordinator: TPLinkRouterCoordinator,
            description: TPLinkRouterSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{description.key}"
        self.entity_description = description

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.entity_description.value(self.coordinator.status)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.entity_description.value(self.coordinator.status) is not None
