from __future__ import annotations
import hashlib
from datetime import timedelta, datetime
from logging import Logger
from collections.abc import Callable
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from tplinkrouterc6u import (
    TplinkRouterProvider,
    AbstractRouter,
    Firmware,
    Status,
    Connection,
    LTEStatus,
    SMS,
)
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
            lte_status: LTEStatus | None,
            logger: Logger,
            unique_id: str
    ) -> None:
        self.router = router
        self.unique_id = unique_id
        self.status = status
        self.tracked = {}
        self.lte_status = lte_status
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
        self._last_update_time: datetime | None = None
        self._sms_hashes: set[str] = set()
        self.new_sms: list[SMS] = []

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
        # Only fetch if router is lte_status compatible
        if self.lte_status is not None:
            self.lte_status = await self.hass.async_add_executor_job(
                TPLinkRouterCoordinator.request,
                self.router,
                self.router.get_lte_status,
            )
        await self._update_new_sms()
        self._last_update_time = datetime.now()

    async def _update_new_sms(self) -> None:
        if not hasattr(self.router, "get_sms") or self.lte_status is None:
            return
        sms_list = await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router,
                                                          self.router.get_sms)
        new_items = []
        for sms in sms_list:
            h = TPLinkRouterCoordinator._hash_item(sms)
            if self._last_update_time is None:
                self._sms_hashes.add(h)
            elif h not in self._sms_hashes:
                self._sms_hashes.add(h)
                new_items.append(sms)

        self.new_sms = new_items

    @staticmethod
    def _hash_item(sms: SMS) -> str:
        key = f"{sms.sender}|{sms.content}|{sms.received_at.isoformat()}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()
