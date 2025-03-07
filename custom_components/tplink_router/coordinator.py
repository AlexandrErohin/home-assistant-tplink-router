from __future__ import annotations
from datetime import timedelta, datetime
from logging import Logger
from collections.abc import Callable
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from tplinkrouterc6u import TplinkRouterProvider, AbstractRouter, Firmware, Status, Connection
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from .const import (
    DOMAIN,
    DEFAULT_NAME,
)


class TPLinkRouterCoordinator(DataUpdateCoordinator):
    def __init__(
            self,
            hass: HomeAssistant,
            router: AbstractRouter,
            update_interval: int,
            firmware: Firmware,
            status: Status,
            logger: Logger,
            unique_id: str
    ) -> None:
        self.router = router
        self.unique_id = unique_id
        self.status = status
        self.device_info = DeviceInfo(
            configuration_url=router.host,
            connections={(CONNECTION_NETWORK_MAC, self.status.lan_macaddr)},
            identifiers={(DOMAIN, self.status.lan_macaddr)},
            manufacturer="TPLink",
            model=firmware.model,
            name=DEFAULT_NAME,
            sw_version=firmware.firmware_version,
            hw_version=firmware.hardware_version,
        )

        self.scan_stopped_at: datetime | None = None

        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    @staticmethod
    async def get_client(hass: HomeAssistant, host: str, password: str, username: str, logger: Logger,
                         verify_ssl: bool) -> AbstractRouter:
        return await hass.async_add_executor_job(TplinkRouterProvider.get_client, host, password, username,
                                                 logger, verify_ssl)

    @staticmethod
    def request(router: AbstractRouter, callback: Callable):
        router.authorize()
        data = callback()
        router.logout()

        return data

    async def reboot(self) -> None:
        await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, self.router.reboot)

    async def set_wifi(self, wifi: Connection, enable: bool) -> None:
        def callback():
            self.router.set_wifi(wifi, enable)

        await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, callback)

    async def _async_update_data(self):
        """Asynchronous update of all data."""
        if self.scan_stopped_at is not None and self.scan_stopped_at > (datetime.now() - timedelta(minutes=20)):
            return
        self.scan_stopped_at = None
        self.status = await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router,
                                                             self.router.get_status)
