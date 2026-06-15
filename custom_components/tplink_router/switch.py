from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from tplinkrouterc6u import VPN, Connection
from . import vpn_client


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


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    switches = []

    for switch in STATUS_SWITCH_TYPES:
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

    async_add_entities(switches, False)


class TPLinkRouterSwitch(
    CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity
):
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
        self.coordinator_attr = getattr(self.coordinator, switch.coordinator_key)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return getattr(self.coordinator_attr, self.switch.property)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self.coordinator_attr, self.switch.property) is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self.switch.method(self.coordinator, True)
        setattr(self.coordinator_attr, self.switch.property, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self.switch.method(self.coordinator, False)
        setattr(self.coordinator_attr, self.switch.property, False)
        self.async_write_ha_state()


class TPLinkRouterScanEntity(
    CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity
):
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

