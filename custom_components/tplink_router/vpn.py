from __future__ import annotations
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator


def setup_vpn_entities(
    coordinator: TPLinkRouterCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    tracked_servers: dict = {}
    tracked_devices: dict = {}

    @callback
    def coordinator_updated() -> None:
        new_entities = []

        for server in coordinator.vpn_status.servers:
            if server.id not in tracked_servers:
                entity = TPLinkVpnServerSwitch(coordinator, server)
                tracked_servers[server.id] = entity
                new_entities.append(entity)
            else:
                tracked_servers[server.id].server = server

        for device in coordinator.vpn_status.devices:
            if device.macaddr not in tracked_devices:
                entity = TPLinkVpnDeviceSwitch(coordinator, device)
                tracked_devices[device.macaddr] = entity
                new_entities.append(entity)
            else:
                tracked_devices[device.macaddr].device = device

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(coordinator_updated))


class TPLinkVpnServerSwitch(CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity):
    """Switch for enabling/disabling a VPN server."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TPLinkRouterCoordinator, server) -> None:
        super().__init__(coordinator)
        self._server_id = server.id
        self.server = server
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_vpn_server_{server.id}"

    @property
    def name(self) -> str:
        return f"VPN Server {self.server.name}"

    @property
    def icon(self) -> str:
        return "mdi:server-network"

    @property
    def is_on(self) -> bool:
        return self.server.active

    @property
    def available(self) -> bool:
        return super().available and any(
            s.id == self._server_id for s in self.coordinator.vpn_status.servers
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "protocol": str(self.server.protocol),
            "status": self.server.status,
            "name": self.server.name,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_vpn_client_server(self._server_id, True)
        self.server.active = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_vpn_client_server(self._server_id, False)
        self.server.active = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        found = next(
            (s for s in self.coordinator.vpn_status.servers if s.id == self._server_id), None
        )
        if found is not None:
            self.server = found
        self.async_write_ha_state()


class TPLinkVpnDeviceSwitch(CoordinatorEntity[TPLinkRouterCoordinator], SwitchEntity):
    """Switch for toggling VPN routing for a specific device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TPLinkRouterCoordinator, device) -> None:
        super().__init__(coordinator)
        self._mac = device.macaddr
        self.device = device
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_vpn_device_{device.macaddr}"

    @property
    def name(self) -> str:
        label = self.device.name if self.device.name else self._mac
        return f"VPN Routing {label}"

    @property
    def icon(self) -> str:
        return "mdi:lan-connect"

    @property
    def is_on(self) -> bool:
        return self.device.enabled

    @property
    def available(self) -> bool:
        return super().available and any(
            d.macaddr == self._mac for d in self.coordinator.vpn_status.devices
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_vpn_client_device(self._mac, True)
        self.device.enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_vpn_client_device(self._mac, False)
        self.device.enabled = False
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        found = next(
            (d for d in self.coordinator.vpn_status.devices if d.macaddr == self._mac), None
        )
        if found is not None:
            self.device = found
        self.async_write_ha_state()
