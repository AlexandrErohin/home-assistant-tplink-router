from __future__ import annotations
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator


def setup_blocked_device_entities(
    hass,
    coordinator: TPLinkRouterCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a "Blocked" switch for each client device the router reports or has blocked."""
    tracked: dict[str, TPLinkBlockedDeviceSwitch] = {}
    unique_id_prefix = f"{coordinator.unique_id}_{DOMAIN}_blocked_"

    @callback
    def coordinator_updated() -> None:
        macs = [device.macaddr for device in coordinator.status.devices]
        # A blocked device is often offline, so it can be missing from the client list.
        macs += [device.macaddr for device in coordinator.blocked_devices or []]
        new_entities = []
        for mac in macs:
            key = format_mac(mac)
            if key not in tracked:
                entity = TPLinkBlockedDeviceSwitch(coordinator, mac)
                tracked[key] = entity
                new_entities.append(entity)
            else:
                # Prefer the library/tracker MAC string once it appears.
                tracked[key].prefer_library_mac(mac)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()

    # Restore switches of clients that are offline now, so they can still be blocked.
    to_restore = []
    for reg_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if reg_entry.domain != "switch" or not reg_entry.unique_id.startswith(unique_id_prefix):
            continue
        mac = reg_entry.unique_id[len(unique_id_prefix):]
        key = format_mac(mac)
        if key in tracked:
            continue
        tracked[key] = TPLinkBlockedDeviceSwitch(coordinator, mac)
        to_restore.append(tracked[key])
    if to_restore:
        async_add_entities(to_restore)


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
        # Prefer the router/library MAC string (same as the tracker) so device
        # registry connections merge. unique_id always uses format_mac().
        self._mac = self._resolve_library_mac(mac) or mac
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_blocked_{format_mac(mac)}"

    def prefer_library_mac(self, mac: str) -> None:
        """Update the stored MAC when the router reports the tracker form."""
        if format_mac(mac) == format_mac(self._mac):
            self._mac = mac

    def _resolve_library_mac(self, mac: str) -> str | None:
        """Return the MAC string used by status/blocked lists when known."""
        key = format_mac(mac)
        for device in self.coordinator.status.devices:
            if format_mac(device.macaddr) == key:
                return device.macaddr
        for device in self.coordinator.blocked_devices or []:
            if format_mac(device.macaddr) == key:
                return device.macaddr
        return None

    @property
    def device_info(self) -> DeviceInfo:
        """The client's device (same MAC connection as its tracker), with a name.

        Without a name Home Assistant names a new device after the config entry,
        so a blocked device the tracker never saw would show up as the router.
        """
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self._mac)},
            name=self._device_name(),
        )

    def _device_name(self) -> str:
        """Client hostname, else the existing device name, else the blacklist name, else the MAC."""
        if hostname := self._hostname():
            return hostname
        if self.hass is not None:
            existing = dr.async_get(self.hass).async_get_devices(
                connections={(CONNECTION_NETWORK_MAC, self._mac)},
                config_entry_id=self.coordinator.unique_id,
            )
            if existing and existing[0].name:
                return existing[0].name
        blocked = self._blocked_entry()
        if blocked is not None and blocked.hostname:
            return blocked.hostname
        return self._mac

    def _hostname(self) -> str:
        for device in self.coordinator.status.devices:
            if format_mac(device.macaddr) == format_mac(self._mac):
                return device.hostname or ""
        return ""

    def _block_name(self) -> str:
        """Name to store on the blacklist: live hostname, else existing blacklist name."""
        if hostname := self._hostname():
            return hostname
        blocked = self._blocked_entry()
        if blocked is not None and blocked.hostname:
            return blocked.hostname
        return ""

    def _blocked_entry(self):
        return next(
            (
                device
                for device in self.coordinator.blocked_devices or []
                if format_mac(device.macaddr) == format_mac(self._mac)
            ),
            None,
        )

    @property
    def is_on(self) -> bool:
        return self._blocked_entry() is not None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.blocked_devices is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.block_device(self._mac, self._block_name())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.unblock_device(self._mac)
