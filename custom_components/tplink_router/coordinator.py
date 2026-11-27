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
    RepeaterStatus,
    Connection,
    LTEStatus,
    SMS,
    ServingCell,
    VpnClientStatus,
    VPNStatus,
    PortStatus,
    RouterPortStatus,
    IPv4Reservation,
)

try:
    from tplinkrouterc6u import MeshNode
except ImportError:  # pragma: no cover - older tplinkrouterc6u without mesh
    MeshNode = Any  # type: ignore[misc, assignment]
try:
    from tplinkrouterc6u import AccessControlStatus, BlockedDevice
except ImportError:  # pragma: no cover - older tplinkrouterc6u without Access Control
    AccessControlStatus = Any  # type: ignore[misc, assignment]
    BlockedDevice = Any  # type: ignore[misc, assignment]
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_SCAN_PAUSE,
    DEFAULT_OFFLINE_TIMEOUT,
)
from .utils import safe_call, is_retryable_error


def supports_led_control(router: AbstractRouter) -> bool:
    """Return True when the client exposes LED get/set methods (e.g. TL-SG108E)."""
    return hasattr(router, "led_status") and hasattr(router, "set_led")


# get_access_control() is two HTTP reads; refresh enable/mode less often than the blacklist.
ACCESS_CONTROL_STATUS_POLL_EVERY = 3


def supports_access_control(router: AbstractRouter) -> bool:
    """Return True when the client exposes the full Access Control blacklist API."""
    return all(
        hasattr(router, name)
        for name in (
            "get_blocked_devices",
            "block_device",
            "unblock_device",
            "get_access_control",
            "set_access_control",
        )
    )


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


def collect_repeater_status(router: AbstractRouter, logger: Logger) -> RepeaterStatus | None:
    """Read backhaul data for clients that provide the extender API."""
    getter = getattr(router, "get_repeater_status", None)
    if getter is None:
        return None
    return safe_call(getter, logger, "fetch repeater backhaul", level=logging.DEBUG)


def collect_status(
        router: AbstractRouter,
        lte_status: LTEStatus | None,
        serving_cells: list[ServingCell] | None,
        vpn_server_status: VPNStatus | None,
        vpn_client_status: VpnClientStatus | None,
        port_status: list[PortStatus | RouterPortStatus] | None,
        reservations: list[IPv4Reservation] | None,
        logger: Logger,
        mesh_nodes: list[MeshNode] | None = None,
        led_status: bool | None = None,
        access_control: AccessControlStatus | None = None,
        blocked_devices: list[BlockedDevice] | None = None,
        poll_access_control_status: bool = True,
) -> tuple[Status, LTEStatus | None, list[ServingCell] | None, VPNStatus | None,
           VpnClientStatus | None, list[PortStatus | RouterPortStatus] | None, list[SMS] | None,
           list[IPv4Reservation] | None, list[MeshNode] | None, bool | None,
           AccessControlStatus | None, list[BlockedDevice] | None, RepeaterStatus | None]:
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
    # Keep the last known Access Control state when one poll fails, so the
    # switches stay in place; None (unsupported) is never asked for.
    # Blacklist is polled every cycle (Blocked switches); enable/mode less often
    # because get_access_control() is two HTTP reads on the router.
    if access_control is not None and poll_access_control_status:
        access_control = safe_call(
            router.get_access_control, logger, "fetch Access Control status", default=access_control
        )
    if blocked_devices is not None:
        blocked_devices = safe_call(
            router.get_blocked_devices, logger, "fetch blocked devices", default=blocked_devices
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
        access_control,
        blocked_devices,
        collect_repeater_status(router, logger),
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
            port_status: list[PortStatus | RouterPortStatus] | None = None,
            retries: int = 3,
            backoff_seconds: float = 1.0,
            scan_pause_minutes: int = DEFAULT_SCAN_PAUSE,
            offline_timeout_seconds: int = DEFAULT_OFFLINE_TIMEOUT,
            reservations: list[IPv4Reservation] | None = None,
            support_dhcp_reservations: bool = True,
            mesh_nodes: list[MeshNode] | None = None,
            led_status: bool | None = None,
            access_control: AccessControlStatus | None = None,
            blocked_devices: list[BlockedDevice] | None = None,
            repeater_status: RepeaterStatus | None = None,
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
        self.repeater_status = repeater_status
        self.led_status: bool | None = led_status
        # None means the client has no Access Control support (no entities, no polling).
        self.access_control: AccessControlStatus | None = access_control
        self.blocked_devices: list[BlockedDevice] | None = blocked_devices
        self._access_control_poll_count = 0
        # Plain keyword arguments to register the device at setup: reading a
        # DeviceInfo as a dict is deprecated since it became a dataclass.
        self.device_info_kwargs: dict[str, Any] = {
            "configuration_url": router.host,
            "connections": {(CONNECTION_NETWORK_MAC, self.status.lan_macaddr)},
            "identifiers": {(DOMAIN, self.status.lan_macaddr)},
            "manufacturer": "TPLink",
            "model": firmware.model,
            "name": DEFAULT_NAME,
            "sw_version": firmware.firmware_version,
            "hw_version": firmware.hardware_version,
        }
        self.device_info = DeviceInfo(**self.device_info_kwargs)

        self.vpn_server_status = vpn_server_status
        self.vpn_client_status = vpn_client_status
        self.reservations: list[IPv4Reservation] | None = reservations
        self.support_dhcp_reservations = support_dhcp_reservations

        self.scan_stopped_at: datetime | None = None
        self._last_update_time: datetime | None = None
        self._sms_hashes: set[str] = set()
        self.new_sms: list[SMS] = []
        self._lock = asyncio.Lock()
        # Set by async_stop() on unload/reload so in-flight polls skip new
        # authorize/request cycles and retries instead of blocking shutdown.
        self._shutting_down = False

        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    def _should_stop_polling(self) -> bool:
        return self._shutting_down or bool(getattr(self.hass, "is_stopping", False))

    async def async_stop(self) -> None:
        """Stop scheduled polls and skip further router requests (unload/reload)."""
        self._shutting_down = True
        await self.async_shutdown()

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

    async def set_access_control(self, enable: bool) -> None:
        """Turn Access Control on or off; the router's blacklist/whitelist mode is left as it is."""
        def callback():
            self.router.set_access_control(enable=enable)
            return self.router.get_access_control()

        self.access_control = await self._run_router_request(callback)
        self.async_update_listeners()

    async def block_device(self, mac: str, name: str = "") -> None:
        """Add a device to the blacklist; never turns Access Control on or changes the mode."""
        def callback():
            self.router.block_device(mac, name)
            return self.router.get_blocked_devices()

        self.blocked_devices = await self._run_router_request(callback)
        self.async_update_listeners()

    async def unblock_device(self, mac: str) -> None:
        def callback():
            self.router.unblock_device(mac)
            return self.router.get_blocked_devices()

        self.blocked_devices = await self._run_router_request(callback)
        self.async_update_listeners()

    async def send_sms(self, number: str, text: str) -> None:
        def callback():
            self.router.send_sms(number, text)

        await self._run_router_request(callback)

    async def _async_update_data(self):
        """Asynchronous update of all data."""
        retries = max(1, int(self.retries))
        last_error: Exception | None = None

        def update_once():
            # Blacklist every cycle; enable/mode every Nth (get_access_control is 2 reads).
            self._access_control_poll_count += 1
            poll_ac_status = (
                self._access_control_poll_count % ACCESS_CONTROL_STATUS_POLL_EVERY == 1
            )
            return TPLinkRouterCoordinator.request(
                self.router,
                lambda: collect_status(
                    self.router,
                    self.lte_status,
                    self.serving_cells,
                    self.vpn_server_status,
                    self.vpn_client_status,
                    self.port_status,
                    self.reservations,
                    self.logger,
                    self.mesh_nodes,
                    self.led_status,
                    self.access_control,
                    self.blocked_devices,
                    poll_access_control_status=poll_ac_status,
                ),
            )

        for attempt in range(retries):
            if self._should_stop_polling():
                return
            try:
                # Hold the router lock only for the authorize/request/logout cycle,
                # not for inter-attempt backoff, so switch/reboot/SMS can proceed.
                async with self._lock:
                    if self._should_stop_polling():
                        return
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
                        self.mesh_nodes,
                        self.led_status,
                        self.access_control,
                        self.blocked_devices,
                        self.repeater_status,
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
                    if self._should_stop_polling():
                        return
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
