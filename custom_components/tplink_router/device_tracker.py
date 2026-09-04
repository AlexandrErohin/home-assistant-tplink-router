from __future__ import annotations

from datetime import datetime, timedelta
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
from .utils import prefer
from .const import (
    DOMAIN,
    CONF_SUPPORT_TRACKER,
    EVENT_NEW_DEVICE,
    EVENT_ONLINE,
    EVENT_OFFLINE,
)
from tplinkrouterc6u import Device

MAC_ADDR: TypeAlias = str

# Keeps mesh node unique_ids from colliding with client ones, which are the bare MAC.
MESH_ID_MARKER = "mesh_"


def mark_offline_if_expired(tracker: "TPLinkTracker", now: datetime, timeout_seconds: int) -> bool:
    """Return True when a missing device should be marked offline after the grace period."""
    if timeout_seconds == 0:
        return True
    return now - tracker.last_seen >= timedelta(seconds=timeout_seconds)


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Add entities from coordinator, otherwise restore."""
    if not entry.data.get(CONF_SUPPORT_TRACKER, True):
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    registry = entity_registry.async_get(hass)
    tracked: dict[MAC_ADDR, TPLinkTracker] = {}
    tracked_nodes: dict[MAC_ADDR, TPLinkMeshTracker] = {}
    to_restore: list[TPLinkTracker] = []
    unique_id_prefix = f"{coordinator.unique_id}_{DOMAIN}_"
    mesh_unique_id_prefix = f"{coordinator.unique_id}_{DOMAIN}_{MESH_ID_MARKER}"

    @callback
    def coordinator_updated():
        """Update the status of the device."""
        update_items(coordinator, async_add_entities, tracked)
        update_mesh_items(coordinator, async_add_entities, tracked_nodes)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))
    coordinator_updated()
    for reg_entry in entity_registry.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != "device_tracker":
            continue
        # Mesh nodes share the client prefix; without this a node entity would be
        # restored as a client tracker whose MAC is the marker plus the address.
        if reg_entry.unique_id.startswith(mesh_unique_id_prefix):
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
    now = datetime.now()
    timeout = coordinator.offline_timeout_seconds
    for device in coordinator.status.devices:
        active.append(device.macaddr)
        if device.macaddr not in tracked:
            tracked[device.macaddr] = TPLinkTracker(coordinator, device)
            new_tracked.append(tracked[device.macaddr])
            if fire_event:
                coordinator.hass.bus.fire(EVENT_NEW_DEVICE, tracked[device.macaddr].data)
        else:
            tracked[device.macaddr].device = device
            tracked[device.macaddr]._remember(device)
            if fire_event and not tracked[device.macaddr].active and device.active:
                coordinator.hass.bus.fire(EVENT_ONLINE, tracked[device.macaddr].data)
            if fire_event and tracked[device.macaddr].active and not device.active:
                coordinator.hass.bus.fire(EVENT_OFFLINE, tracked[device.macaddr].data)
        tracked[device.macaddr].active = device.active
        tracked[device.macaddr].last_seen = now

    if new_tracked:
        async_add_entities(new_tracked)

    for mac in tracked:
        if mac not in active and tracked[mac].active and mark_offline_if_expired(tracked[mac], now, timeout):
            tracked[mac].active = False
            coordinator.hass.bus.fire(EVENT_OFFLINE, tracked[mac].data)


@callback
def update_mesh_items(
        coordinator: TPLinkRouterCoordinator,
        async_add_entities: AddEntitiesCallback,
        tracked: dict[MAC_ADDR, "TPLinkMeshTracker"],
) -> None:
    """Create or refresh one tracker per EasyMesh node reported by the main router."""
    new_tracked: list[TPLinkMeshTracker] = []
    seen: set[MAC_ADDR] = set()
    for node in coordinator.mesh_nodes or []:
        mac = node.macaddr
        if not mac:
            continue
        seen.add(mac)
        if mac not in tracked:
            tracked[mac] = TPLinkMeshTracker(coordinator, node)
            new_tracked.append(tracked[mac])
        else:
            tracked[mac].node = node

    if new_tracked:
        async_add_entities(new_tracked)

    # A node that drops out of the list is offline rather than gone, so the entity
    # stays and only its connected state changes.
    for mac, tracker in tracked.items():
        if mac not in seen:
            tracker.node = None


class TPLinkMeshTracker(CoordinatorEntity, ScannerEntity):
    """Representation of an EasyMesh node, the main router included."""

    def __init__(self, coordinator: TPLinkRouterCoordinator, node) -> None:
        """Initialize from a tplinkrouterc6u MeshNode."""
        self.node = node
        self._mac = node.macaddr
        self._name = node.name or node.model or node.macaddr
        self._last_ip_address = node.ipaddr or ""
        super().__init__(coordinator)

    @property
    def is_connected(self) -> bool:
        """Return true while the main router still reports the node as connected."""
        return self.node is not None and self.node.status == "connected"

    @property
    def source_type(self) -> str:
        return SourceType.ROUTER

    @property
    def name(self) -> str:
        return self._name

    @property
    def hostname(self) -> str:
        return self._name

    @property
    def mac_address(self) -> MAC_ADDR:
        return self._mac

    @property
    def ip_address(self) -> str:
        if self.node is not None:
            self._last_ip_address = prefer(self.node.ipaddr, self._last_ip_address, "")
        return self._last_ip_address

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.unique_id}_{DOMAIN}_{MESH_ID_MARKER}{self._mac}"

    @property
    def icon(self) -> str:
        if not self.is_connected:
            return "mdi:router-network-wireless"
        return "mdi:router-wireless" if self.node.is_main_router else "mdi:access-point-network"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self.node is None:
            return {}
        node = self.node
        attributes = {
            # device_type/device_model/connection_type follow the attribute names
            # ha-tplink-deco already uses, so dashboards written for one work for both.
            'device_type': node.device_type,
            'device_model': node.model,
            'connection_type': node.connect_type,
            'status': node.status,
            'role': node.role,
            'is_main_router': node.is_main_router,
        }
        if node.parent_macaddr is not None:
            attributes['parent_mac'] = node.parent_macaddr
        if node.client_num is not None:
            attributes['client_num'] = node.client_num
        if node.signal_level is not None:
            # Deliberately not exposed as 'signal': clients report dBm there, while a
            # node reports a 1 to 3 bar level. Sharing the key would put values with
            # different units in the same column.
            attributes['signal_level'] = node.signal_level
        if node.support_reboot is not None:
            attributes['support_reboot'] = node.support_reboot
        if node.location is not None:
            attributes['location'] = node.location
        if node.mesh_type is not None:
            attributes['mesh_type'] = node.mesh_type
        if node.vendor is not None:
            attributes['vendor'] = node.vendor
        return attributes

    @property
    def entity_registry_enabled_default(self) -> bool:
        return True


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
        self._last_hostname = ""
        self._last_ip_address = ""
        self.last_seen = datetime.now()
        if data:
            self._remember(data)
        super().__init__(coordinator)

    def _remember(self, data: Device) -> None:
        """Remember the last meaningful hostname/IP so events never fire blank."""
        if data.hostname:
            self._last_hostname = data.hostname
        if data.ipaddr and str(data.ipaddr) != "0.0.0.0":
            self._last_ip_address = str(data.ipaddr)

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
            return (
                self.device.hostname
                or self._last_hostname
                or self._restored_attributes.get("hostname")
                or self._mac
            )
        return self._restored_attributes.get("hostname") or self._last_hostname or self._mac

    @property
    def hostname(self) -> str:
        """Return the hostname of the client."""
        if self.device is not None:
            return (
                self.device.hostname
                or self._last_hostname
                or self._restored_attributes.get("hostname")
                or ""
            )
        return self._restored_attributes.get("hostname") or self._last_hostname or ""

    @property
    def mac_address(self) -> MAC_ADDR:
        """Return the mac address of the client."""
        return self._mac

    @property
    def ip_address(self) -> str:
        """Return the ip address of the client."""
        restored_ip = self._restored_attributes.get("ip_address") or ""
        if self.device is not None:
            return prefer(
                self.device.ipaddr,
                self._last_ip_address or restored_ip,
                "",
            )
        return restored_ip or self._last_ip_address or ""

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
        if self.device.ap_name is not None:
            attributes['ap_name'] = self.device.ap_name
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
        hostname = self._restored_attributes.get("hostname")
        if hostname:
            self._last_hostname = hostname
        ip_address = self._restored_attributes.get("ip_address")
        if ip_address and str(ip_address) != "0.0.0.0":
            self._last_ip_address = str(ip_address)
