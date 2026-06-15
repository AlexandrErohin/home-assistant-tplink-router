from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from homeassistant.components.sensor import (
    SensorStateClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfDataRate, UnitOfInformation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from .const import DOMAIN
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from tplinkrouterc6u import Status, LTEStatus, VPNStatus


@dataclass
class TPLinkRouterSensorConfigBase[T]:
    description: SensorEntityDescription
    value: Callable[[T], Any]
    sensor_type: str


@dataclass
class TPLinkRouterSensorConfig(TPLinkRouterSensorConfigBase[Status]):
    sensor_type: str = "status"


@dataclass
class TPLinkRouterLTESensorConfig(TPLinkRouterSensorConfigBase[LTEStatus]):
    sensor_type: str = "lte_status"


@dataclass
class TPLinkRouterVPNServerSensorConfig(TPLinkRouterSensorConfigBase[VPNStatus]):
    sensor_type: str = "vpn_server_status"


SENSOR_TYPES = (
    TPLinkRouterSensorConfig(
        value=lambda status: status.guest_clients_total,
        description=SensorEntityDescription(
            key="guest_wifi_clients_total",
            name="Total guest wifi clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.wifi_clients_total,
        description=SensorEntityDescription(
            key="wifi_clients_total",
            name="Total main wifi clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.wired_total,
        description=SensorEntityDescription(
            key="wired_clients_total",
            name="Total wired clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.iot_clients_total,
        description=SensorEntityDescription(
            key="iot_clients_total",
            name="Total IoT clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.clients_total,
        description=SensorEntityDescription(
            key="clients_total",
            name="Total clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: (
            (status.cpu_usage * 100) if status.cpu_usage is not None else None
        ),
        description=SensorEntityDescription(
            key="cpu_used",
            name="CPU used",
            icon="mdi:cpu-64-bit",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=1,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: (
            (status.mem_usage * 100) if status.mem_usage is not None else None
        ),
        description=SensorEntityDescription(
            key="memory_used",
            name="Memory used",
            icon="mdi:memory",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=1,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.conn_type,
        description=SensorEntityDescription(
            key="conn_type",
            name="Connection Type",
            icon="mdi:wan",
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.wan_ipv4_addr,
        description=SensorEntityDescription(
            key="wan_ipv4_addr",
            name="WAN IPv4 Address",
            icon="mdi:wan",
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: status.lan_ipv4_addr,
        description=SensorEntityDescription(
            key="lan_ipv4_addr",
            name="LAN IPv4 Address",
            icon="mdi:lan",
        ),
    ),
)

LTE_SENSOR_TYPES = (
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.enable,
        description=SensorEntityDescription(
            key="lte_enabled",
            name="LTE Enabled",
            icon="mdi:sim-outline",
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.connect_status,
        description=SensorEntityDescription(
            key="lte_connect_status",
            name="LTE Connection Status",
            icon="mdi:sim-outline",
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.network_type,
        description=SensorEntityDescription(
            key="lte_network_type",
            name="LTE Network Type",
            icon="mdi:sim-outline",
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.network_type_info,
        description=SensorEntityDescription(
            key="lte_network_type_info",
            name="LTE Network Type Info",
            icon="mdi:sim-outline",
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.sim_status,
        description=SensorEntityDescription(
            key="lte_sim_status",
            name="LTE SIM Status",
            icon="mdi:sim-outline",
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.sim_status_info,
        description=SensorEntityDescription(
            key="lte_sim_status_info",
            name="LTE SIM Status Info",
            icon="mdi:sim-outline",
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.total_statistics,
        description=SensorEntityDescription(
            key="lte_total_statistics",
            name="LTE Total Statistics",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.TOTAL,
            native_unit_of_measurement=UnitOfInformation.BYTES,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.cur_rx_speed,
        description=SensorEntityDescription(
            key="lte_cur_rx_speed",
            name="LTE Current RX Speed",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.cur_tx_speed,
        description=SensorEntityDescription(
            key="lte_cur_tx_speed",
            name="LTE Current TX Speed",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.sms_unread_count,
        description=SensorEntityDescription(
            key="lte_sms_unread_count",
            name="Unread SMS",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: (
            status.sig_level * 25 if status.sig_level is not None else None
        ),
        description=SensorEntityDescription(
            key="lte_sig_level",
            name="LTE Signal Level",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.rsrp,
        description=SensorEntityDescription(
            key="lte_rsrp",
            name="LTE RSRP",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.rsrq,
        description=SensorEntityDescription(
            key="lte_rsrq",
            name="LTE RSRQ",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: 0.1 * status.snr if status.snr is not None else None,
        description=SensorEntityDescription(
            key="lte_snr",
            name="LTE SNR",
            icon="mdi:sim-outline",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ),
    TPLinkRouterLTESensorConfig(
        value=lambda status: status.isp_name,
        description=SensorEntityDescription(
            key="lte_isp_name",
            name="LTE ISP Name",
            icon="mdi:sim-outline",
        ),
    ),
)

VPN_SERVER_SENSOR_TYPES = (
    TPLinkRouterVPNServerSensorConfig(
        value=lambda status: status.openvpn_clients_total,
        description=SensorEntityDescription(
            key="openvpn_clients_total",
            name="Total OpenVPN clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
    TPLinkRouterVPNServerSensorConfig(
        value=lambda status: status.pptpvpn_clients_total,
        description=SensorEntityDescription(
            key="pptpvpn_clients_total",
            name="Total PPTP clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []

    for sensor in SENSOR_TYPES:
        sensors.append(TPLinkRouterSensor(coordinator, sensor))

    if coordinator.lte_status is not None:
        for sensor in LTE_SENSOR_TYPES:
            sensors.append(TPLinkRouterSensor(coordinator, sensor))

    if coordinator.vpn_server_status is not None:
        for sensor in VPN_SERVER_SENSOR_TYPES:
            sensors.append(TPLinkRouterSensor(coordinator, sensor))

    async_add_entities(sensors, False)


class TPLinkRouterSensor(CoordinatorEntity[TPLinkRouterCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TPLinkRouterCoordinator,
        sensor: TPLinkRouterSensorConfigBase
    ) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{sensor.description.key}"
        self.entity_description = sensor.description
        self.sensor = sensor

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        coordinator_data = getattr(
            self.coordinator, self.sensor.sensor_type
        )
        self._attr_native_value = self.sensor.value(coordinator_data)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        coordinator_data = getattr(
            self.coordinator, self.sensor.sensor_type
        )
        return self.sensor.value(coordinator_data) is not None
