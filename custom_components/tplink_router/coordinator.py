from __future__ import annotations
import hashlib
import asyncio
from datetime import timedelta, datetime
from logging import Logger
from collections.abc import Callable
from typing import Any, Type
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
    VPNStatus,
    PortStatus,
    IPv4Reservation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_SCAN_PAUSE,
    DEFAULT_OFFLINE_TIMEOUT,
)
from .utils import safe_call, is_retryable_error

try:
    from urllib.parse import urlencode
    from tplinkrouterc6u.client.c6u import TplinkRouter
    from tplinkrouterc6u.common.helper import get_mac
    from tplinkrouterc6u.common.exception import ClientException

    if not hasattr(TplinkRouter, "delete_ipv4_reservation"):
        def _delete_ipv4_reservation(self, macaddr: str) -> None:
            raw = self.request(self._url_ipv4_reservations, "operation=load")
            items = self._as_list(raw, "list", "IPv4 reservation")
            normalized_mac = str(get_mac(macaddr))
            target_idx = next(
                (i for i, item in enumerate(items) if str(get_mac(item.get("mac", ""))) == normalized_mac),
                None,
            )
            if target_idx is None:
                raise ClientException(f"Reservation not found for MAC: {macaddr}")

            path = self._url_ipv4_reservations.split("&operation=")[0]
            self.request(path, urlencode({"operation": "remove", "key": normalized_mac, "index": target_idx}))

        TplinkRouter.delete_ipv4_reservation = _delete_ipv4_reservation
except Exception:
    pass


def collect_status(
        router: AbstractRouter,
        lte_status: LTEStatus | None,
        serving_cells: list[ServingCell] | None,
        vpn_server_status: VPNStatus | None,
        vpn_client_status: VpnClientStatus | None,
        port_status: list[PortStatus] | None,
        logger: Logger,
) -> tuple[Status, LTEStatus | None, list[ServingCell] | None, VPNStatus | None,
           VpnClientStatus | None, list[PortStatus] | None, list[SMS] | None, list[IPv4Reservation] | None]:
    """Gather all status data from the router; a failing SMS fetch must not break the update."""
    status = router.get_status()
    sms_list = None
    if lte_status is not None:
        lte_status = router.get_lte_status()
    if serving_cells is not None:
        serving_cells = router.get_lte_serving_cells()
    if vpn_server_status is not None:
        vpn_server_status = router.get_vpn_status()
    if vpn_client_status is not None:
        vpn_client_status = router.get_vpn_client_status()
    if port_status is not None:
        port_status = router.get_port_status()
    if hasattr(router, "get_sms") and lte_status is not None:
        sms_list = safe_call(router.get_sms, logger, "fetch SMS")
    reservations = None
    if hasattr(router, "get_ipv4_reservations"):
        reservations = safe_call(router.get_ipv4_reservations, logger, "fetch IPv4 reservations")
    return (
        status,
        lte_status,
        serving_cells,
        vpn_server_status,
        vpn_client_status,
        port_status,
        sms_list,
        reservations,
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
            port_status: list[PortStatus] | None = None,
            retries: int = 3,
            backoff_seconds: float = 1.0,
            scan_pause_minutes: int = DEFAULT_SCAN_PAUSE,
            offline_timeout_seconds: int = DEFAULT_OFFLINE_TIMEOUT,
    ) -> None:
        self.router = router
        self.unique_id = unique_id
        self.status = status
        self.tracked = {}
        self.lte_status = lte_status
        self.serving_cells = serving_cells
        self.port_status = port_status
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.scan_pause_minutes = scan_pause_minutes
        self.offline_timeout_seconds = offline_timeout_seconds
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
        self.reservations: list[IPv4Reservation] | None = None

        self.scan_stopped_at: datetime | None = None
        self._last_update_time: datetime | None = None
        self._sms_hashes: set[str] = set()
        self.new_sms: list[SMS] = []
        self._lock = asyncio.Lock()

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

    async def _run_router_request(self, callback: Callable) -> Any:
        async with self._lock:
            return await self.hass.async_add_executor_job(
                TPLinkRouterCoordinator.request, self.router, callback
            )

    async def reboot(self) -> None:
        def callback():
            self.router.reboot()

        await self._run_router_request(callback)

    async def set_wifi(self, wifi: Connection, enable: bool) -> None:
        def callback():
            self.router.set_wifi(wifi, enable)

        await self._run_router_request(callback)

    async def set_vpn_server(self, kind: VPN, enable: bool) -> None:
        def callback():
            self.router.set_vpn(kind, enable)

        await self._run_router_request(callback)

    async def set_vpn_client(self, enable: bool) -> None:
        def callback():
            self.router.set_vpn_client(enable)

        await self._run_router_request(callback)

    async def set_vpn_client_server(self, server_id, enable: bool) -> None:
        def callback():
            self.router.set_vpn_client_server(server_id, enable)

        await self._run_router_request(callback)

    async def set_vpn_client_device(self, mac: str, enable: bool) -> None:
        def callback():
            self.router.set_vpn_client_device(mac, enable)

        await self._run_router_request(callback)

    async def set_ipv4_dhcps(self, enable: bool) -> None:
        def callback():
            self.router.set_ipv4_dhcps(enable)

        await self._run_router_request(callback)

    async def add_ipv4_reservation(
        self, mac: str, ip: str, comment: str = "", enable: bool = True
    ) -> None:
        def callback():
            self.router.add_ipv4_reservation(mac, ip, comment, enable)

        await self._run_router_request(callback)
        await self.async_request_refresh()

    async def delete_ipv4_reservation(self, mac: str) -> None:
        def callback():
            self.router.delete_ipv4_reservation(mac)

        await self._run_router_request(callback)
        await self.async_request_refresh()

    async def send_sms(self, number: str, text: str) -> None:
        def callback():
            self.router.send_sms(number, text)

        await self._run_router_request(callback)

    async def _async_update_data(self):
        """Asynchronous update of all data."""
        retries = max(1, int(self.retries))
        last_error: Exception | None = None

        def update_once():
            return TPLinkRouterCoordinator.request(
                self.router,
                lambda: collect_status(
                    self.router,
                    self.lte_status,
                    self.serving_cells,
                    self.vpn_server_status,
                    self.vpn_client_status,
                    self.port_status,
                    self.logger,
                ),
            )

        for attempt in range(retries):
            try:
                # Hold the router lock only for the authorize/request/logout cycle,
                # not for inter-attempt backoff, so switch/reboot/SMS can proceed.
                async with self._lock:
                    if self.scan_stopped_at is not None:
                        # scan_pause_minutes == 0 keeps fetching paused until turned
                        # back on manually (no automatic re-enable).
                        if (
                            self.scan_pause_minutes <= 0
                            or self.scan_stopped_at > (
                                datetime.now()
                                - timedelta(minutes=self.scan_pause_minutes)
                            )
                        ):
                            return
                        self.scan_stopped_at = None

                    (
                        self.status,
                        self.lte_status,
                        self.serving_cells,
                        self.vpn_server_status,
                        self.vpn_client_status,
                        self.port_status,
                        sms_list,
                        self.reservations,
                    ) = await self.hass.async_add_executor_job(update_once)

                if sms_list is not None:
                    self._process_sms_list(sms_list)
                self._last_update_time = datetime.now()
                return
            except Exception as error:
                if not is_retryable_error(error):
                    raise
                last_error = error
                self.logger.warning(
                    "TPLink Router request attempt %s/%s failed: %s",
                    attempt + 1,
                    retries,
                    error,
                )
                if attempt < retries - 1:
                    await asyncio.sleep(self.backoff_seconds * (attempt + 1))

        if last_error is not None:
            raise last_error

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
