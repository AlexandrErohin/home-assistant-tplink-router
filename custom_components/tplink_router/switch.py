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
from tplinkrouterc6u import Connection


@dataclass
class TPLinkRouterSwitchEntityDescriptionMixin:
    method: Callable[[TPLinkRouterCoordinator, bool], Any]
    property: str


@dataclass
class TPLinkRouterSwitchEntityDescription(SwitchEntityDescription, TPLinkRouterSwitchEntityDescriptionMixin):
    """A class that describes sensor entities."""


SWITCH_TYPES = (
    TPLinkRouterSwitchEntityDescription(
        key="wifi_guest_24g",
        name="Guest WIFI 2.4G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='guest_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.GUEST_2G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="wifi_guest_5g",
        name="Guest WIFI 5G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='guest_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.GUEST_5G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="wifi_guest_6g",
        name="Guest WIFI 6G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='guest_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.GUEST_6G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="wifi_24g",
        name="WIFI 2.4G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='wifi_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_2G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="wifi_5g",
        name="WIFI 5G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='wifi_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_5G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="wifi_6g",
        name="WIFI 6G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='wifi_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.HOST_6G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="iot_24g",
        name="IoT WIFI 2.4G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='iot_2g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.IOT_2G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="iot_5g",
        name="IoT WIFI 5G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='iot_5g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.IOT_5G, value),
    ),
    TPLinkRouterSwitchEntityDescription(
        key="iot_6g",
        name="IoT WIFI 6G",
        icon="mdi:wifi",
        entity_category=EntityCategory.CONFIG,
        property='iot_6g_enable',
        method=lambda coordinator, value: coordinator.set_wifi(Connection.IOT_6G, value),
    ),
)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    switches = []

    for description in SWITCH_TYPES:
        switches.append(TPLinkRouterSwitchEntity(coordinator, description))

    switches.append(TPLinkRouterScanEntity(coordinator))

    async_add_entities(switches, False)


class TPLinkRouterSwitchEntity(
    CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity
):
    entity_description: TPLinkRouterSwitchEntityDescription

    def __init__(
            self,
            coordinator: TPLinkRouterCoordinator,
            description: TPLinkRouterSwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{description.key}"
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return getattr(self.coordinator.status, self.entity_description.property)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return getattr(self.coordinator.status, self.entity_description.property) is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self.entity_description.method(self.coordinator, True)
        setattr(self.coordinator.status, self.entity_description.property, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self.entity_description.method(self.coordinator, False)
        setattr(self.coordinator.status, self.entity_description.property, False)
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
