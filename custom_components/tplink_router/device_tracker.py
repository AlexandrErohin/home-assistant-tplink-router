from __future__ import annotations

from typing import TypeAlias
from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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
    """Add entitities from coordinator, otherwise restore."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    registry = entity_registry.async_get(hass)
    tracked: dict[MAC_ADDR, TPLinkTracker] = {}
    to_restore: list[TPLinkTracker] = []
    unique_id_prefix = f"{coordinator.unique_id}_{DOMAIN}_"

    @callback
    def coordinator_updated():
        """Update the status of the device."""
        update_items(coordinator, async_add_entities, tracked)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()
    for reg_entry in entity_registry.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != "device_tracker":
            continue
        mac = reg_entry.unique_id[len(unique_id_prefix):]
        if mac in tracked:
            continue
        tracked[mac] = TPLinkTracker(coordinator, None, mac=mac)
        to_restore.append(tracked[mac])
    if to_restore:
        async_add_entities(to_restore)


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


class TPLinkTracker(CoordinatorEntity, RestoreEntity, ScannerEntity):
    """Representation of network device."""

    def __init__(
            self,
            coordinator: TPLinkRouterCoordinator,
            data: Device | None,
            mac: MAC_ADDR | None = None,
    ) -> None:
        """Initialize the device (tracked by the router or restored from Home Assistant)."""
        self.device = data
        self._mac = mac or (data.macaddr if data else None)
        self.active = data.active if data else False
        self._restored_attributes: dict[str, str] = {}
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
        if self.device is not None:
            return self.device.hostname if self.device.hostname != "" else self._mac
        return self._restored_attributes.get("hostname") or self._mac

    @property
    def hostname(self) -> str:
        """Return the hostname of the client."""
        if self.device is not None:
            return self.device.hostname
        return self._restored_attributes.get("hostname", "")

    @property
    def mac_address(self) -> MAC_ADDR:
        """Return the mac address of the client."""
        return self._mac

    @property
    def ip_address(self) -> str:
        """Return the ip address of the client."""
        if self.device is not None:
            return self.device.ipaddr
        return self._restored_attributes.get("ip_address", "")

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
        if self.device is None:
            return self._restored_attributes
        attributes = {
            'connection': self.device.type.get_type(),
            'band': self.device.type.get_band(),
            'packets_sent': self.device.packets_sent,
            'packets_received': self.device.packets_received
        }
        if self.device.down_speed is not None or self.device.up_speed is not None:
            attributes['up_speed'] = self.device.up_speed
            attributes['down_speed'] = self.device.down_speed
        if self.device.tx_rate is not None or self.device.rx_rate is not None:
            attributes['tx_rate'] = self.device.tx_rate
            attributes['rx_rate'] = self.device.rx_rate
        if self.device.online_time is not None:
            attributes['online_time'] = self.device.online_time
        if self.device.traffic_usage is not None:
            attributes['traffic_usage'] = self.device.traffic_usage
        if self.device.signal is not None:
            attributes['signal'] = self.device.signal
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

    async def async_added_to_hass(self) -> None:
        """Restore entity attributes if not already updated."""
        await super().async_added_to_hass()
        if self.device is not None:
            return
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        self._restored_attributes = dict(last_state.attributes)
