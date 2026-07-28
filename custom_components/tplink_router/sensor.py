from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from homeassistant.components.sensor import (
    RestoreSensor,
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
from homeassistant.util import dt as dt_util
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
        value=lambda status: round(
            sum(
                int(device.up_speed or 0)
                for device in status.devices
                if getattr(device, "active", False)
            ) * 8 / 1_000_000,
            2,
        ),
        description=SensorEntityDescription(
            key="total_upload_mbps",
            name="Total current upload",
            icon="mdi:upload-network",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="Mbit/s",
            suggested_display_precision=2,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: round(
            sum(
                int(device.down_speed or 0)
                for device in status.devices
                if getattr(device, "active", False)
            ) * 8 / 1_000_000,
            2,
        ),
        description=SensorEntityDescription(
            key="total_download_mbps",
            name="Total current download",
            icon="mdi:download-network",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="Mbit/s",
            suggested_display_precision=2,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: sum(
            1
            for device in status.devices
            if (
                getattr(device, "active", False)
                and device.type.get_band() == "2G"
            )
        ),
        description=SensorEntityDescription(
            key="clients_2g",
            name="Active 2.4 GHz clients",
            icon="mdi:wifi",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ),
    TPLinkRouterSensorConfig(
        value=lambda status: sum(
            1
            for device in status.devices
            if (
                getattr(device, "active", False)
                and device.type.get_band() == "5G"
            )
        ),
        description=SensorEntityDescription(
            key="clients_5g",
            name="Active 5 GHz clients",
            icon="mdi:wifi",
            state_class=SensorStateClass.MEASUREMENT,
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


TRAFFIC_DIRECTIONS = ("download", "upload")

TRAFFIC_PERIODS = ("day", "month", "total")

TRAFFIC_DIRECTION_NAMES = {
    "download": "Downloaded",
    "upload": "Uploaded",
}

TRAFFIC_PERIOD_NAMES = {
    "day": "today",
    "month": "this month",
    "total": "total",
}


def build_traffic_counters(
    coordinator: TPLinkRouterCoordinator,
) -> list["TPLinkRouterTrafficCounter"]:
    """Create traffic counter sensors."""
    return [
        TPLinkRouterTrafficCounter(
            coordinator=coordinator,
            direction=direction,
            period=period,
        )
        for direction in TRAFFIC_DIRECTIONS
        for period in TRAFFIC_PERIODS
    ]


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

    traffic_counters = build_traffic_counters(coordinator)

    coordinator.register_traffic_counters(traffic_counters)

    sensors.extend(traffic_counters)

    async_add_entities(sensors, False)



class TPLinkRouterTrafficCounter(
    CoordinatorEntity[TPLinkRouterCoordinator],
    RestoreSensor,
):
    """Accumulate router client traffic for a day, month, or lifetime."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self,
        coordinator: TPLinkRouterCoordinator,
        direction: str,
        period: str,
    ) -> None:
        super().__init__(coordinator)

        if direction not in TRAFFIC_DIRECTIONS:
            raise ValueError(f"Unsupported traffic direction: {direction}")

        if period not in TRAFFIC_PERIODS:
            raise ValueError(f"Unsupported counter period: {period}")

        self._direction = direction
        self._period = period
        self._value_gb = 0.0
        self._last_update_time = None
        self._current_period_key = None

        direction_name = TRAFFIC_DIRECTION_NAMES[direction]
        period_name = TRAFFIC_PERIOD_NAMES[period]

        self._attr_name = f"{direction_name} {period_name}"

        self._attr_unique_id = (
            f"{coordinator.unique_id}_{DOMAIN}_"
            f"{direction}_{period}_traffic"
        )

        self._attr_icon = (
            "mdi:database-arrow-down"
            if direction == "download"
            else "mdi:database-arrow-up"
        )

        self._attr_device_info = coordinator.device_info
        self._attr_native_value = 0.0

    def _period_key(self, now):
        """Return the current counter period identifier."""
        if self._period == "day":
            return now.date().isoformat()

        if self._period == "month":
            return f"{now.year:04d}-{now.month:02d}"

        return "total"

    def _bytes_per_second(self) -> int:
        """Return total current client traffic in bytes per second."""
        devices = getattr(self.coordinator.status, "devices", None) or []

        field = (
            "down_speed"
            if self._direction == "download"
            else "up_speed"
        )

        return sum(
            int(getattr(device, field, 0) or 0)
            for device in devices
            if getattr(device, "active", False)
        )

    async def async_added_to_hass(self) -> None:
        """Restore the counter and register coordinator updates."""
        await super().async_added_to_hass()

        now = dt_util.now()
        current_period_key = self._period_key(now)

        last_sensor_data = await self.async_get_last_sensor_data()
        last_state = await self.async_get_last_state()

        if last_sensor_data is not None and last_state is not None:
            restored_period_key = self._period_key(
                dt_util.as_local(last_state.last_updated)
            )

            if restored_period_key == current_period_key:
                try:
                    self._value_gb = float(last_sensor_data.native_value)
                except (TypeError, ValueError):
                    self._value_gb = 0.0

        self._current_period_key = current_period_key
        self._last_update_time = now
        self._attr_native_value = round(self._value_gb, 3)

    @callback
    def reset(self) -> None:
        """Reset the accumulated traffic and start counting from now."""
        now = dt_util.now()

        self._value_gb = 0.0
        self._current_period_key = self._period_key(now)
        self._last_update_time = now
        self._attr_native_value = 0.0

        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate the current byte rate over elapsed time."""
        now = dt_util.now()
        period_key = self._period_key(now)

        if self._current_period_key != period_key:
            self._value_gb = 0.0
            self._current_period_key = period_key
            self._last_update_time = now

        elif self._last_update_time is not None:
            elapsed_seconds = (
                now - self._last_update_time
            ).total_seconds()

            # Ignore abnormal intervals caused by clock changes or
            # very long Home Assistant/router outages.
            if 0 < elapsed_seconds <= 3600:
                bytes_transferred = (
                    self._bytes_per_second() * elapsed_seconds
                )

                self._value_gb += bytes_transferred / 1_000_000_000

            self._last_update_time = now

        else:
            self._last_update_time = now

        self._attr_native_value = round(self._value_gb, 3)
        self.async_write_ha_state()



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
