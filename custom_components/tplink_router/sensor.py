from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from homeassistant.components.sensor import (
    SensorStateClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfDataRate, UnitOfInformation, UnitOfFrequency
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from .const import DOMAIN
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from tplinkrouterc6u import Status, LTEStatus, VPNStatus, ServingCell


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


@dataclass
class TPLinkRouterServingCellSensorConfig(TPLinkRouterSensorConfigBase[list[ServingCell]]):
    sensor_type: str = "serving_cells"


# --- Serving cell helpers ---
_NT_NR = 8
_NT_LTE_PLUS = 7
_NT_LTE = 3


def _sc(cells, nt):
    if not cells:
        return None
    return next((c for c in cells if c.network_type == nt), None)


def _scf(cells, nt, field):
    c = _sc(cells, nt)
    if c is None:
        return None
    return getattr(c, field)


def _active_bands(cells):
    if not cells:
        return None
    prefix = {_NT_LTE: 'B', _NT_LTE_PLUS: 'B', _NT_NR: 'N'}
    parts = [f"{prefix[nt]}{_sc(cells, nt).band}"
             for nt in (_NT_LTE, _NT_LTE_PLUS, _NT_NR) if _sc(cells, nt)]
    return '+'.join(parts) if parts else None


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

SERVING_CELL_SENSOR_TYPES = (
    # Overview
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _active_bands(cells),
        description=SensorEntityDescription(
            key="cell_active_bands",
            name="Active Bands",
            icon="mdi:antenna",
        ),
    ),
    # 5G NR cell
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'band'),
        description=SensorEntityDescription(
            key="cell_nr_band",
            name="NR Band",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'arfcn'),
        description=SensorEntityDescription(
            key="cell_nr_arfcn",
            name="NR-ARFCN",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'downlink_bandwidth'),
        description=SensorEntityDescription(
            key="cell_nr_dl_bandwidth",
            name="NR DL Bandwidth",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'downlink_frequency'),
        description=SensorEntityDescription(
            key="cell_nr_dl_freq",
            name="NR DL Frequency",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'downlink_modulation'),
        description=SensorEntityDescription(
            key="cell_nr_dl_mod",
            name="NR DL Modulation",
            icon="mdi:sine-wave",
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'uplink_modulation'),
        description=SensorEntityDescription(
            key="cell_nr_ul_mod",
            name="NR UL Modulation",
            icon="mdi:sine-wave",
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'cqi'),
        description=SensorEntityDescription(
            key="cell_nr_cqi",
            name="NR CQI",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'ri'),
        description=SensorEntityDescription(
            key="cell_nr_ri",
            name="NR RI",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_NR, 'resource_blocks'),
        description=SensorEntityDescription(
            key="cell_nr_num_rbs",
            name="NR Resource Blocks",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    # LTE anchor cell
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE, 'band'),
        description=SensorEntityDescription(
            key="cell_lte_anchor_band",
            name="LTE Anchor Band",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE, 'arfcn'),
        description=SensorEntityDescription(
            key="cell_lte_anchor_arfcn",
            name="LTE Anchor E-ARFCN",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE, 'downlink_bandwidth'),
        description=SensorEntityDescription(
            key="cell_lte_anchor_dl_bandwidth",
            name="LTE Anchor DL Bandwidth",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE, 'downlink_frequency'),
        description=SensorEntityDescription(
            key="cell_lte_anchor_dl_freq",
            name="LTE Anchor DL Frequency",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE, 'rsrp'),
        description=SensorEntityDescription(
            key="cell_lte_anchor_rsrp",
            name="LTE Anchor RSRP",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE, 'rsrq'),
        description=SensorEntityDescription(
            key="cell_lte_anchor_rsrq",
            name="LTE Anchor RSRQ",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ),
    # LTE CA secondary cell (networkType 7, LTE+)
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE_PLUS, 'band'),
        description=SensorEntityDescription(
            key="cell_lte_ca_band",
            name="LTE CA Band",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE_PLUS, 'arfcn'),
        description=SensorEntityDescription(
            key="cell_lte_ca_arfcn",
            name="LTE CA E-ARFCN",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE_PLUS, 'downlink_bandwidth'),
        description=SensorEntityDescription(
            key="cell_lte_ca_dl_bandwidth",
            name="LTE CA DL Bandwidth",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE_PLUS, 'downlink_frequency'),
        description=SensorEntityDescription(
            key="cell_lte_ca_dl_freq",
            name="LTE CA DL Frequency",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE_PLUS, 'rsrp'),
        description=SensorEntityDescription(
            key="cell_lte_ca_rsrp",
            name="LTE CA RSRP",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        ),
    ),
    TPLinkRouterServingCellSensorConfig(
        value=lambda cells: _scf(cells, _NT_LTE_PLUS, 'rsrq'),
        description=SensorEntityDescription(
            key="cell_lte_ca_rsrq",
            name="LTE CA RSRQ",
            icon="mdi:antenna",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
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

    if coordinator.serving_cells is not None:
        for sensor in SERVING_CELL_SENSOR_TYPES:
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
