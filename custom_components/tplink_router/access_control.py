from __future__ import annotations
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator


def setup_blocked_device_entities(
    coordinator: TPLinkRouterCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a "Blocked" switch for each client device the router reports or has blocked."""
    tracked: dict[str, TPLinkBlockedDeviceSwitch] = {}

    @callback
    def coordinator_updated() -> None:
        macs = [device.macaddr for device in coordinator.status.devices]
        # A blocked device is often offline, so it can be missing from the client list.
        macs += [device.macaddr for device in coordinator.blocked_devices or []]
        new_entities = []
        for mac in macs:
            if format_mac(mac) not in tracked:
                entity = TPLinkBlockedDeviceSwitch(coordinator, mac)
                tracked[format_mac(mac)] = entity
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()


class TPLinkBlockedDeviceSwitch(CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity):
    """On while the device is on the router's Access Control blacklist.

    Blocking only edits the blacklist: the router enforces it while Access
    Control is on and in blacklist mode (the "Access Control" switch).
    """

    _attr_has_entity_name = True
    _attr_name = "Blocked"
    _attr_icon = "mdi:lan-disconnect"
    _attr_entity_category = EntityCategory.CONFIG
    # One switch per client would flood the entity list; users enable the ones they need.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: TPLinkRouterCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_blocked_{format_mac(mac)}"
        # Same MAC connection as the client's device tracker, so both land on one device.
        self._attr_device_info = DeviceInfo(connections={(CONNECTION_NETWORK_MAC, mac)})

    @property
    def is_on(self) -> bool:
        return any(
            format_mac(device.macaddr) == format_mac(self._mac)
            for device in self.coordinator.blocked_devices or []
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.blocked_devices is not None

    def _hostname(self) -> str:
        for device in self.coordinator.status.devices:
            if format_mac(device.macaddr) == format_mac(self._mac):
                return device.hostname or ""
        return ""

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.block_device(self._mac, self._hostname())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.unblock_device(self._mac)
