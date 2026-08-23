from __future__ import annotations
import hashlib
import asyncio
from datetime import timedelta, datetime
from logging import Logger
from collections.abc import Callable
from typing import Type
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from tplinkrouterc6u import (
    VPN,
    TplinkRouterProvider,
    AbstractRouter,
    Firmware,
    Status,
    Connection,
    LTEStatus,
    SMS,
    ServingCell,
    VpnClientStatus,
    VPNStatus
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
            unique_id: str,
            vpn_server_status: VPNStatus | None = None,
            vpn_client_status: VpnClientStatus | None = None,
            serving_cells: list[ServingCell] | None = None,
    ) -> None:
        self.router = router
        self.unique_id = unique_id
        self.status = status
        self.tracked = {}
        self.lte_status = lte_status
        self.serving_cells = serving_cells
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

        self.vpn_server_status = vpn_server_status
        self.vpn_client_status = vpn_client_status

        self.scan_stopped_at: datetime | None = None
        self._last_update_time: datetime | None = None
        self._sms_hashes: set[str] = set()
        self.new_sms: list[SMS] = []
        self.lock = asyncio.Lock()

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
    def get_client_by_class(client_class: str) -> Type[AbstractRouter]:
        return TplinkRouterProvider.get_clients()[client_class]

    @staticmethod
    def request(router: AbstractRouter, callback: Callable):
        router.authorize()
        try:
            return callback()
        finally:
            try:
                router.logout()
            except Exception:
                # Do not block updates if logout fails.
                pass

    async def reboot(self) -> None:
        async with self.lock:
            await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, self.router.reboot)

    async def set_wifi(self, wifi: Connection, enable: bool) -> None:
        async with self.lock:
            def callback():
                self.router.set_wifi(wifi, enable)
            await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, callback)

    async def set_vpn_server(self, kind: VPN, enable: bool) -> None:
        async with self.lock:
            def callback():
                self.router.set_vpn(kind, enable)
            await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, callback)

    async def set_vpn_client(self, enable: bool) -> None:
        async with self.lock:
            def callback():
                self.router.set_vpn_client(enable)
            await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, callback)

    async def set_vpn_client_server(self, server_id, enable: bool) -> None:
        async with self.lock:
            def callback():
                self.router.set_vpn_client_server(server_id, enable)
            await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, callback)

    async def set_vpn_client_device(self, mac: str, enable: bool) -> None:
        async with self.lock:
            def callback():
                self.router.set_vpn_client_device(mac, enable)
            await self.hass.async_add_executor_job(TPLinkRouterCoordinator.request, self.router, callback)

    async def _async_update_data(self):
        async with self.lock:
            """Asynchronous update of all data."""
            if self.scan_stopped_at is not None and self.scan_stopped_at > (datetime.now() - timedelta(minutes=20)):
                return
            self.scan_stopped_at = None

            def callback():
                status = self.router.get_status()
                lte_status = self.lte_status
                serving_cells = self.serving_cells
                vpn_server_status = self.vpn_server_status
                vpn_client_status = self.vpn_client_status
                sms_list = None

                if self.lte_status is not None:
                    lte_status = self.router.get_lte_status()
                if self.serving_cells is not None:
                    serving_cells = self.router.get_lte_serving_cells()
                if self.vpn_server_status is not None:
                    vpn_server_status = self.router.get_vpn_status()
                if self.vpn_client_status is not None:
                    vpn_client_status = self.router.get_vpn_client_status()
                if hasattr(self.router, "get_sms") and self.lte_status is not None:
                    sms_list = self.router.get_sms()

                return (
                    status,
                    lte_status,
                    serving_cells,
                    vpn_server_status,
                    vpn_client_status,
                    sms_list,
                )

            (
                self.status,
                self.lte_status,
                self.serving_cells,
                self.vpn_server_status,
                self.vpn_client_status,
                sms_list,
            ) = await self.hass.async_add_executor_job(
                TPLinkRouterCoordinator.request, self.router, callback
            )

            if sms_list is not None:
                self._process_sms_list(sms_list)
            self._last_update_time = datetime.now()

    def _process_sms_list(self, sms_list: list[SMS]) -> None:
        current_hashes: set[str] = set()
        new_items: list[SMS] = []
        for sms in sms_list:
            h = TPLinkRouterCoordinator._hash_item(sms)
            current_hashes.add(h)
            if self._last_update_time is not None and h not in self._sms_hashes:
                new_items.append(sms)
        # Keep only hashes present in the current mailbox to avoid unbounded growth.
        self._sms_hashes = current_hashes
        self.new_sms = new_items

    @staticmethod
    def _hash_item(sms: SMS) -> str:
        key = f"{sms.sender}|{sms.content}|{sms.received_at.isoformat()}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()
