from __future__ import annotations

from typing import TypeAlias
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .coordinator import TPLinkRouterCoordinator
from .const import (
    DOMAIN,
    EVENT_NEW_DEVICE,
    EVENT_ONLINE,
    EVENT_OFFLINE,
)
from tplinkrouterc6u import Device

MAC_ADDR: TypeAlias = str


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    tracked: dict[MAC_ADDR, TPLinkTracker] = {}

    @callback
    def coordinator_updated():
        """Update the status of the device."""
        update_items(coordinator, async_add_entities, tracked)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()


@callback
def update_items(
        coordinator: TPLinkRouterCoordinator,
        async_add_entities: AddEntitiesCallback,
        tracked: dict[MAC_ADDR, TPLinkTracker],
) -> None:
    """Update tracked device state from the hub."""
    new_tracked: list[TPLinkTracker] = []
    active: list[MAC_ADDR] = []
    fire_event = tracked != {}
    for device in coordinator.status.devices:
        active.append(device.macaddr)
        if device.macaddr not in tracked:
            tracked[device.macaddr] = TPLinkTracker(coordinator, device)
            new_tracked.append(tracked[device.macaddr])
            if fire_event:
                coordinator.hass.bus.fire(EVENT_NEW_DEVICE, tracked[device.macaddr].data)
        else:
            tracked[device.macaddr].device = device
            if fire_event and not tracked[device.macaddr].active and device.active:
                coordinator.hass.bus.fire(EVENT_ONLINE, tracked[device.macaddr].data)
            if fire_event and tracked[device.macaddr].active and not device.active:
                coordinator.hass.bus.fire(EVENT_OFFLINE, tracked[device.macaddr].data)
        tracked[device.macaddr].active = device.active

    if new_tracked:
        async_add_entities(new_tracked)

    for mac in tracked:
        if mac not in active and tracked[mac].active:
            tracked[mac].active = False
            coordinator.hass.bus.fire(EVENT_OFFLINE, tracked[mac].data)


class TPLinkTracker(CoordinatorEntity, ScannerEntity):
    """Representation of network device."""

    def __init__(
            self,
            coordinator: TPLinkRouterCoordinator,
            data: Device,
    ) -> None:
        """Initialize the tracked device."""
        self.device = data
        self.active = True

        super().__init__(coordinator)

    @property
    def is_connected(self) -> bool:
        """Return true if the client is connected to the network."""
        return self.active

    @property
    def source_type(self) -> str:
        """Return the source type of the client."""
        return SourceType.ROUTER

    @property
    def name(self) -> str:
        """Return the name of the client."""
        return self.device.hostname if self.device.hostname != '' else self.device.macaddr

    @property
    def hostname(self) -> str:
        """Return the hostname of the client."""
        return self.device.hostname

    @property
    def mac_address(self) -> MAC_ADDR:
        """Return the mac address of the client."""
        return self.device.macaddr

    @property
    def ip_address(self) -> str:
        """Return the ip address of the client."""
        return self.device.ipaddr

    @property
    def unique_id(self) -> str:
        """Return an unique identifier for this device."""
        return f"{self.coordinator.unique_id}_{DOMAIN}_{self.mac_address}"

    @property
    def icon(self) -> str:
        """Return device icon."""
        return "mdi:lan-connect" if self.is_connected else "mdi:lan-disconnect"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        attributes = {
            'connection': self.device.type.get_type(),
            'band': self.device.type.get_band(),
            'packets_sent': self.device.packets_sent,
            'packets_received': self.device.packets_received
        }
        if self.device.down_speed is not None or self.device.up_speed is not None:
            attributes['up_speed'] = self.device.up_speed
            attributes['down_speed'] = self.device.down_speed
        return attributes

    @property
    def data(self) -> dict[str, str]:
        return dict(self.extra_state_attributes.items() | {
            'hostname': self.hostname,
            'ip_address': self.ip_address,
            'mac_address': self.mac_address,
        }.items())

    @property
    def entity_registry_enabled_default(self) -> bool:
        return True
