from __future__ import annotations
import hashlib
import asyncio
import logging
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

try:
    from tplinkrouterc6u import MeshNode
except ImportError:  # pragma: no cover - older tplinkrouterc6u without mesh
    MeshNode = Any  # type: ignore[misc, assignment]
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_SCAN_PAUSE,
    DEFAULT_OFFLINE_TIMEOUT,
)
from homeassistant.exceptions import HomeAssistantError
from .utils import safe_call, is_retryable_error
from .reservations import (
    ReservationError,
    ReservationRow,
    ReservationTable,
    add_reservation,
    delete_reservation,
    fetch_table,
    supports_reservations,
    supports_update,
    update_reservation,
)


def supports_led_control(router: AbstractRouter) -> bool:
    """Return True when the client exposes LED get/set methods (e.g. TL-SG108E)."""
    return hasattr(router, "led_status") and hasattr(router, "set_led")


def collect_mesh_nodes(router: AbstractRouter, logger: Logger) -> list[MeshNode] | None:
    """Return the EasyMesh node list, or None when this client can never provide one.

    None is the "stop asking" signal, matching how the other optional payloads in
    collect_status are gated. It covers both an older tplinkrouterc6u without the
    method and a client that implements the abstract default, so neither case logs
    a warning on every poll. A transient failure returns an empty list instead, so
    polling resumes on the next cycle.
    """
    getter = getattr(router, "get_mesh_nodes", None)
    if getter is None:
        return None
    try:
        return getter()
    except NotImplementedError:
        return None
    except Exception:
        logger.warning("TPLink Router failed to fetch mesh nodes", exc_info=True)
        return []


def collect_status(
        router: AbstractRouter,
        lte_status: LTEStatus | None,
        serving_cells: list[ServingCell] | None,
        vpn_server_status: VPNStatus | None,
        vpn_client_status: VpnClientStatus | None,
        port_status: list[PortStatus] | None,
        reservations: list[IPv4Reservation] | None,
        logger: Logger,
        mesh_nodes: list[MeshNode] | None = None,
        led_status: bool | None = None,
) -> tuple[Status, LTEStatus | None, list[ServingCell] | None, VPNStatus | None,
           VpnClientStatus | None, list[PortStatus] | None, list[SMS] | None,
           list[IPv4Reservation] | None, list[MeshNode] | None, bool | None]:
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
    if mesh_nodes is not None:
        mesh_nodes = collect_mesh_nodes(router, logger)
    if hasattr(router, "get_sms") and lte_status is not None:
        sms_list = safe_call(router.get_sms, logger, "fetch SMS")
    if reservations is not None:
        reservations = safe_call(router.get_ipv4_reservations, logger, "fetch IPv4 reservations")
    if led_status is not None:
        led_status = safe_call(
            router.led_status, logger, "fetch LED status", level=logging.DEBUG
        )
    return (
        status,
        lte_status,
        serving_cells,
        vpn_server_status,
        vpn_client_status,
        port_status,
        sms_list,
        reservations,
        mesh_nodes,
        led_status,
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
            reservations: list[IPv4Reservation] | None = None,
            support_dhcp_reservations: bool = True,
            mesh_nodes: list[MeshNode] | None = None,
            led_status: bool | None = None,
            reservation_table: ReservationTable | None = None,
    ) -> None:
        self.router = router
        # ConfigEntry.entry_id (not the flow unique_id / LAN MAC). Used in entity
        # unique_ids and as config_entry_id for device-registry lookups.
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
        # list (incl. []) means "ask each poll"; None means the client cannot provide
        # a node list. Setup probes once so entities exist before the first interval.
        self.mesh_nodes: list[MeshNode] | None = mesh_nodes
        self.led_status: bool | None = led_status
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
        self.reservations: list[IPv4Reservation] | None = reservations
        self.support_dhcp_reservations = support_dhcp_reservations
        # The reservation table is polled on every update while the client can
        # provide it, so a failed setup probe no longer hides the sensors and
        # services forever: they appear once a poll succeeds.
        self.reservation_table: ReservationTable | None = reservation_table
        self.reservations_supported = bool(support_dhcp_reservations) and supports_reservations(router)
        self._reservation_poll_failed = False

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
        await self._run_router_request(self.router.reboot)

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

    async def set_ewan_connect(self, enable: bool) -> None:
        def callback():
            self.router.set_ewan_connect(enable)

        await self._run_router_request(callback)

    async def set_led(self, enable: bool) -> None:
        def callback():
            self.router.set_led(enable)

        await self._run_router_request(callback)

    @property
    def supports_reservation_update(self) -> bool:
        return self.reservations_supported and supports_update(self.router)

    def poll_reservation_table(self) -> ReservationTable | None:
        """Fetch the reservation table inside an authorized session (blocking).

        Keeps the last known table on a transient failure; stops asking only
        when the client says the feature is not implemented.
        """
        if not self.reservations_supported:
            return self.reservation_table
        try:
            table = fetch_table(self.router)
        except NotImplementedError:
            self.reservations_supported = False
            return self.reservation_table
        except Exception:
            self.logger.log(
                logging.DEBUG if self._reservation_poll_failed else logging.WARNING,
                "TPLink Router failed to fetch IPv4 reservations",
                exc_info=True,
            )
            self._reservation_poll_failed = True
            return self.reservation_table
        self._reservation_poll_failed = False
        return table

    async def _run_reservation_write(self, action: Callable[[], Any]) -> Any:
        """Run a reservation write plus a table reload in one router session.

        Errors surface as HomeAssistantError so a failed service call is
        reported to the caller (UI, script, automation) instead of only logged.
        """
        def callback():
            result = action()
            try:
                table = fetch_table(self.router)
            except Exception:
                table = None
            return result, table

        try:
            result, table = await self._run_router_request(callback)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"TP-Link router DHCP reservation change failed: {err}") from err
        if table is not None:
            self.reservation_table = table
            self.async_update_listeners()
        return result

    async def add_ipv4_reservation(
        self, mac: str, ip: str, comment: str = "", enable: bool = True
    ) -> ReservationRow:
        return await self._run_reservation_write(
            lambda: add_reservation(self.router, mac, ip, comment, enable)
        )

    async def update_ipv4_reservation(
        self,
        old_mac: str,
        mac: str | None = None,
        ip: str | None = None,
        comment: str | None = None,
        enable: bool | None = None,
    ) -> ReservationRow:
        if not self.supports_reservation_update:
            raise ReservationError("This router does not support editing DHCP reservations")
        return await self._run_reservation_write(
            lambda: update_reservation(self.router, old_mac, mac, ip, comment, enable)
        )

    async def delete_ipv4_reservation(self, mac: str) -> None:
        await self._run_reservation_write(lambda: delete_reservation(self.router, mac))

    async def send_sms(self, number: str, text: str) -> None:
        def callback():
            self.router.send_sms(number, text)

        await self._run_router_request(callback)

    async def _async_update_data(self):
        """Asynchronous update of all data."""
        retries = max(1, int(self.retries))
        last_error: Exception | None = None

        def collect():
            result = collect_status(
                self.router,
                self.lte_status,
                self.serving_cells,
                self.vpn_server_status,
                self.vpn_client_status,
                self.port_status,
                # The reservation table below replaces the legacy list fetch.
                None if self.reservations_supported else self.reservations,
                self.logger,
                self.mesh_nodes,
                self.led_status,
            )
            return result, self.poll_reservation_table()

        def update_once():
            return TPLinkRouterCoordinator.request(self.router, collect)

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
                        (
                            self.status,
                            self.lte_status,
                            self.serving_cells,
                            self.vpn_server_status,
                            self.vpn_client_status,
                            self.port_status,
                            sms_list,
                            reservations,
                            self.mesh_nodes,
                            self.led_status,
                        ),
                        self.reservation_table,
                    ) = await self.hass.async_add_executor_job(update_once)
                    if not self.reservations_supported:
                        self.reservations = reservations

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
