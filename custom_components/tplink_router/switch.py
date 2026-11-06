from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from tplinkrouterc6u import VPN, Connection
from . import vpn_client
from .parental_control import ParentalProfile, SCHEDULE_FLAGS
from .permissions import require_admin


@dataclass
class TPLinkRouterSwitchConfigBase:
    description: SwitchEntityDescription
    method: Callable[[TPLinkRouterCoordinator, bool], Any]
    property: str
    coordinator_key: str


@dataclass
class TPLinkRouterStatusSwitchConfig(TPLinkRouterSwitchConfigBase):
    coordinator_key: str = 'status'


@dataclass
class TPLinkRouterVPNServerSwitchConfig(TPLinkRouterSwitchConfigBase):
    coordinator_key: str = 'vpn_server_status'


@dataclass
class TPLinkRouterVPNClientSwitchConfig(TPLinkRouterSwitchConfigBase):
    coordinator_key: str = 'vpn_client_status'


@dataclass
class TPLinkRouterLedSwitchConfig(TPLinkRouterSwitchConfigBase):
    """LED is a scalar bool on the coordinator (like port_status), not a nested object."""

    coordinator_key: str = 'led_status'
    property: str = ''


STATUS_SWITCH_TYPES = (
    TPLinkRouterStatusSwitchConfig(
        property='guest_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.GUEST_2G, value),
        description=SwitchEntityDescription(
            key="wifi_guest_24g",
            name="Guest WIFI 2.4G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='guest_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.GUEST_5G, value),
        description=SwitchEntityDescription(
            key="wifi_guest_5g",
            name="Guest WIFI 5G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='guest_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.GUEST_6G, value),
        description=SwitchEntityDescription(
            key="wifi_guest_6g",
            name="Guest WIFI 6G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='wifi_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_2G, value),
        description=SwitchEntityDescription(
            key="wifi_24g",
            name="WIFI 2.4G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='wifi_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_5G, value),
        description=SwitchEntityDescription(
            key="wifi_5g",
            name="WIFI 5G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='wifi_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_6G, value),
        description=SwitchEntityDescription(
            key="wifi_6g",
            name="WIFI 6G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='wifi_mlo_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_MLO_2G, value),
        description=SwitchEntityDescription(
            key="wifi_mlo_24g",
            name="WIFI MLO 2.4G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='iot_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.IOT_2G, value),
        description=SwitchEntityDescription(
            key="iot_24g",
            name="IoT WIFI 2.4G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='iot_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.IOT_5G, value),
        description=SwitchEntityDescription(
            key="iot_5g",
            name="IoT WIFI 5G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='iot_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.IOT_6G, value),
        description=SwitchEntityDescription(
            key="iot_6g",
            name="IoT WIFI 6G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)

# 5G/6G MLO — only created when get_status reported both fields (multi-band EX).
MLO_SWITCH_TYPES = (
    TPLinkRouterStatusSwitchConfig(
        property='wifi_mlo_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_MLO_5G, value),
        description=SwitchEntityDescription(
            key="wifi_mlo_5g",
            name="WIFI MLO 5G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterStatusSwitchConfig(
        property='wifi_mlo_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_MLO_6G, value),
        description=SwitchEntityDescription(
            key="wifi_mlo_6g",
            name="WIFI MLO 6G",
            icon="mdi:wifi",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)

VPN_SERVER_SWITCH_TYPES = (
    TPLinkRouterVPNServerSwitchConfig(
        property='openvpn_enable',
        method=lambda coordinator, value: coordinator.set_vpn_server(VPN.OPEN_VPN, value),
        description=SwitchEntityDescription(
            key="openvpn",
            name="VPN Server - OpenVPN",
            icon="mdi:vpn",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterVPNServerSwitchConfig(
        property='pptpvpn_enable',
        method=lambda coordinator, value: coordinator.set_vpn_server(VPN.PPTP_VPN, value),
        description=SwitchEntityDescription(
            key="pptpvpn",
            name="VPN Server - PPTP",
            icon="mdi:vpn",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
    TPLinkRouterVPNServerSwitchConfig(
        property='ipsecvpn_enable',
        method=lambda coordinator, value: coordinator.set_vpn_server(VPN.IPSEC, value),
        description=SwitchEntityDescription(
            key="ipsec",
            name="VPN Server - IPSec",
            icon="mdi:vpn",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)

VPN_CLIENT_SWITCH_TYPES = (
    TPLinkRouterVPNClientSwitchConfig(
        property="enabled",
        method=lambda coordinator, value: coordinator.set_vpn_client(value),
        description=SwitchEntityDescription(
            key="vpn_client",
            name="VPN Client",
            icon="mdi:vpn",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)

DHCP_SERVER_SWITCH_TYPES = (
    TPLinkRouterStatusSwitchConfig(
        property='lan_ipv4_dhcp_enable',
        method=lambda coordinator, value: coordinator.set_ipv4_dhcps(value),
        description=SwitchEntityDescription(
            key="lan_ipv4_dhcp_enable",
            name="LAN IPv4 DHCP Server",
            icon="mdi:server-network",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)

WAN_SWITCH_TYPES = (
    TPLinkRouterStatusSwitchConfig(
        property='ewan_connected',
        method=lambda coordinator, value: coordinator.set_ewan_connect(value),
        description=SwitchEntityDescription(
            key="ewan_connect",
            name="E-WAN connect",
            icon="mdi:ethernet",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)

LED_SWITCH_TYPES = (
    TPLinkRouterLedSwitchConfig(
        method=lambda coordinator, value: coordinator.set_led(value),
        description=SwitchEntityDescription(
            key="led",
            name="LED",
            icon="mdi:led-on",
            entity_category=EntityCategory.CONFIG,
        ),
    ),
)


def _status_switch_types(status) -> tuple[TPLinkRouterStatusSwitchConfig, ...]:
    """Return Wi‑Fi/IoT switches whose status property is reported (not None)."""
    return tuple(
        switch
        for switch in STATUS_SWITCH_TYPES
        if getattr(status, switch.property, None) is not None
    )


def _mlo_switch_types(status) -> tuple[TPLinkRouterStatusSwitchConfig, ...]:
    """Return MLO 5G/6G switches whose status property is reported (not None)."""
    return tuple(
        switch
        for switch in MLO_SWITCH_TYPES
        if getattr(status, switch.property, None) is not None
    )


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    switches = []

    for switch in _status_switch_types(coordinator.status):
        switches.append(TPLinkRouterSwitch(coordinator, switch))

    for switch in _mlo_switch_types(coordinator.status):
        switches.append(TPLinkRouterSwitch(coordinator, switch))

    # Scan entity has has different turn_on/off logic from the rest of the switches
    switches.append(TPLinkRouterScanEntity(coordinator))

    if coordinator.vpn_server_status is not None:
        for switch in VPN_SERVER_SWITCH_TYPES:
            switches.append(TPLinkRouterSwitch(coordinator, switch))

    if coordinator.vpn_client_status is not None:
        for switch in VPN_CLIENT_SWITCH_TYPES:
            switches.append(TPLinkRouterSwitch(coordinator, switch))
        # Dynamically register VPN Client devices & servers available on the router
        vpn_client.setup_vpn_entities(coordinator, entry, async_add_entities)

    if hasattr(coordinator.router, "set_ipv4_dhcps"):
        for switch in DHCP_SERVER_SWITCH_TYPES:
            switches.append(TPLinkRouterSwitch(coordinator, switch))

    if (
        hasattr(coordinator.router, "set_ewan_connect")
        and coordinator.status.ewan_connected is not None
    ):
        for switch in WAN_SWITCH_TYPES:
            switches.append(TPLinkRouterSwitch(coordinator, switch))

    if coordinator.led_status is not None:
        for switch in LED_SWITCH_TYPES:
            switches.append(TPLinkRouterSwitch(coordinator, switch))

    async_add_entities(switches, False)
    if coordinator.parental_status is not None:
        setup_parental_entities(coordinator, entry, async_add_entities)


def setup_parental_entities(
    coordinator: TPLinkRouterCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover profiles on every poll, including recovery from a failed first read."""
    known: set[tuple[str, str]] = set()

    @callback
    def coordinator_updated() -> None:
        status = coordinator.parental_status
        if status is None or status.profiles is None:
            return
        entities = []
        for owner_id, profile in status.profiles.items():
            if (owner_id, "access") not in known:
                entities.append(TPLinkParentalAccessSwitch(coordinator, profile))
                known.add((owner_id, "access"))
            for flag in SCHEDULE_FLAGS:
                if flag in profile.settings and (owner_id, flag) not in known:
                    entities.append(TPLinkParentalScheduleSwitch(coordinator, profile, flag))
                    known.add((owner_id, flag))
        if entities:
            async_add_entities(entities, False)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()


class TPLinkParentalAccessSwitch(CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity):
    """Control the manual pause flag, not scheduled or filtered connectivity."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-network"

    def __init__(self, coordinator: TPLinkRouterCoordinator, profile: ParentalProfile) -> None:
        super().__init__(coordinator)
        self._owner_id = profile.owner_id
        self._label = profile.name or profile.owner_id
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = (
            f"{coordinator.unique_id}_{DOMAIN}_parental_access_{profile.owner_id}"
        )

    @property
    def profile(self) -> ParentalProfile | None:
        status = self.coordinator.parental_status
        if status is None or status.profiles is None:
            return None
        return status.profiles.get(self._owner_id)

    @property
    def name(self) -> str:
        if (profile := self.profile) is not None:
            self._label = profile.name or profile.owner_id
        return f"{self._label} internet access"

    @property
    def available(self) -> bool:
        return super().available and self.profile is not None

    @property
    def is_on(self) -> bool | None:
        profile = self.profile
        return not profile.internet_blocked if profile is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profile = self.profile
        if profile is None:
            return {"owner_id": self._owner_id}
        settings: dict[str, Any] = dict(profile.settings)
        for key, value in settings.items():
            if key.endswith(("_bed_time_begin", "_bed_time_end")):
                settings[key] = f"{value // 60:02d}:{value % 60:02d}"
        return {
            "owner_id": self._owner_id,
            "assigned_devices": (
                [client.as_dict() for client in profile.clients]
                if profile.clients is not None else None
            ),
            "schedule": settings,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await require_admin(self.hass, self._context)
        await self.coordinator.set_profile_access(self._owner_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await require_admin(self.hass, self._context)
        await self.coordinator.set_profile_access(self._owner_id, False)


class TPLinkParentalScheduleSwitch(TPLinkParentalAccessSwitch):
    """Enable a validated schedule without changing its configured times."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: TPLinkRouterCoordinator, profile: ParentalProfile, flag: str) -> None:
        super().__init__(coordinator, profile)
        self._flag = flag
        self._period = "workday" if flag.startswith("enable_workday_") else "weekend"
        self._kind = "bed_time" if flag.endswith("_bed_time") else "time_limit"
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_parental_{profile.owner_id}_{flag}"

    @property
    def name(self) -> str:
        if (profile := self.profile) is not None:
            self._label = profile.name or profile.owner_id
        if self._kind == "bed_time":
            label = "School-night bedtime (Sun-Thu)" if self._period == "workday" else "Weekend bedtime (Fri-Sat)"
        else:
            label = "Daily limit (Mon-Fri)" if self._period == "workday" else "Daily limit (Sat-Sun)"
        return f"{self._label} {label}"

    @property
    def available(self) -> bool:
        return super().available and self._flag in self.profile.settings

    @property
    def is_on(self) -> bool | None:
        profile = self.profile
        if profile is None:
            return None
        value = profile.settings.get(self._flag)
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await require_admin(self.hass, self._context)
        await self.coordinator.set_profile_schedule(self._owner_id, self._period, self._kind, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await require_admin(self.hass, self._context)
        await self.coordinator.set_profile_schedule(self._owner_id, self._period, self._kind, enabled=False)


class TPLinkRouterSwitch(
    CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity
):
    _attr_has_entity_name = True

    def __init__(
            self,
            coordinator: TPLinkRouterCoordinator,
            switch: TPLinkRouterSwitchConfigBase
    ) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{switch.description.key}"
        self.entity_description = switch.description
        self.switch = switch

    @property
    def coordinator_attr(self):
        """Получаем актуальный атрибут координатора."""
        return getattr(self.coordinator, self.switch.coordinator_key)

    @property
    def _value(self):
        """Nested field, or the coordinator_key value itself when property is empty (scalar)."""
        if self.switch.property:
            return getattr(self.coordinator_attr, self.switch.property)
        return self.coordinator_attr

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._value

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._value is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self.switch.method(self.coordinator, True)
        if self.switch.property:
            setattr(self.coordinator_attr, self.switch.property, True)
        else:
            setattr(self.coordinator, self.switch.coordinator_key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self.switch.method(self.coordinator, False)
        if self.switch.property:
            setattr(self.coordinator_attr, self.switch.property, False)
        else:
            setattr(self.coordinator, self.switch.coordinator_key, False)
        self.async_write_ha_state()


class TPLinkRouterScanEntity(
    CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity
):
    _attr_has_entity_name = True
    entity_description: SwitchEntityDescription

    def __init__(self, coordinator: TPLinkRouterCoordinator) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self.entity_description = SwitchEntityDescription(
            key="scanning",
            name="Router data fetching",
            icon="mdi:connection",
            entity_category=EntityCategory.CONFIG,
        )
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{self.entity_description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self.coordinator.scan_stopped_at is None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self.coordinator.scan_stopped_at = None
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.coordinator.scan_stopped_at = datetime.now()
        self.async_write_ha_state()
