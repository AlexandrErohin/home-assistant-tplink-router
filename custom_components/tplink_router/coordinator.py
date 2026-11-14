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
    RouterPortStatus,
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
from .utils import safe_call, is_retryable_error
from .parental_control import (
    ParentalStatus, ParentalEditError, collect_parental_status, write_profile_access,
    edit_profile, read_profile_devices, schedule_changes, change_device_profile, assign_profile_devices,
)
from .parental_features import (
    create_profile, delete_profile, deletion_preview, profile_creation_options, read_profile_report, rename_profile,
)
from homeassistant.exceptions import HomeAssistantError


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
        port_status: list[PortStatus | RouterPortStatus] | None,
        reservations: list[IPv4Reservation] | None,
        logger: Logger,
        mesh_nodes: list[MeshNode] | None = None,
        led_status: bool | None = None,
        parental_status: ParentalStatus | None = None,
) -> tuple[Status, LTEStatus | None, list[ServingCell] | None, VPNStatus | None,
           VpnClientStatus | None, list[PortStatus | RouterPortStatus] | None, list[SMS] | None,
           list[IPv4Reservation] | None, list[MeshNode] | None, bool | None,
           ParentalStatus | None]:
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
    if parental_status is not None:
        parental_status = collect_parental_status(router, logger)
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
        parental_status,
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
            parental_status: ParentalStatus | None = None,
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
        self.parental_status = parental_status
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

        self.scan_stopped_at: datetime | None = None
        self._last_update_time: datetime | None = None
        self.network_updated_at = datetime.now().astimezone()
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

    async def add_ipv4_reservation(
        self, mac: str, ip: str, comment: str = "", enable: bool = True
    ) -> None:
        def callback():
            self.router.add_ipv4_reservation(mac, ip, comment, enable)

        await self._run_router_request(callback)
        await self.async_request_refresh()

    async def set_profile_access(self, owner_id: str, enabled: bool) -> None:
        """Write and read back under the same lock, even when scanning is paused."""
        status = self.parental_status
        if status is None or status.profiles is None or owner_id not in status.profiles:
            raise HomeAssistantError("Parental profile is unavailable")

        def callback():
            write_failed = False
            try:
                write_profile_access(self.router, owner_id, enabled)
            except Exception:
                write_failed = True
            # A rejected acknowledgement can follow an applied write. Read back
            # even on failure so a subsequent restoration action remains possible.
            return collect_parental_status(self.router, self.logger), write_failed

        try:
            self.parental_status, write_failed = await self._run_router_request(callback)
        except Exception:
            self.parental_status = ParentalStatus(None)
            self.async_update_listeners()
            raise HomeAssistantError("Unable to set parental profile internet access") from None
        self.async_update_listeners()
        await self.async_request_refresh()
        if write_failed:
            raise HomeAssistantError("Unable to set parental profile internet access")
        status = self.parental_status
        if (
            status is None
            or status.profiles is None
            or owner_id not in status.profiles
            or status.profiles[owner_id].internet_blocked != (not enabled)
        ):
            raise HomeAssistantError("Parental profile write could not be confirmed")

    async def delete_ipv4_reservation(self, mac: str) -> None:
        def callback():
            self.router.delete_ipv4_reservation(mac)

        await self._run_router_request(callback)
        await self.async_request_refresh()

    async def get_parental_devices(self, owner_id: str, scope: str = "profile") -> list[dict[str, str | int]]:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            return await self._run_router_request(lambda: read_profile_devices(self.router, owner_id, scope))
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            raise HomeAssistantError("Unable to read parental devices") from None

    async def set_profile_schedule(self, owner_id: str, period: str, kind: str, **values: Any) -> None:
        try:
            changes = schedule_changes(period, kind, **values)
        except ValueError as error:
            raise HomeAssistantError(str(error)) from None
        await self._edit_parental_profile(owner_id, changes=changes)

    async def set_profile_device(self, owner_id: str, device_id: str, assigned: bool) -> None:
        if not isinstance(assigned, bool):
            raise HomeAssistantError("Assigned must be a boolean")
        await self._edit_parental_profile(
            owner_id, **{"add_device" if assigned else "remove_device": device_id},
        )

    async def change_device_profile(self, mac: str, expected_owner: str, destination: str) -> None:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            status, error = await self._run_router_request(lambda: change_device_profile(
                self.router, self.logger, mac, expected_owner, destination,
            ))
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            raise HomeAssistantError("Profile change failed; refresh to inspect current assignments") from None
        self.parental_status = status
        self.async_update_listeners()
        await self.async_request_refresh()
        if error:
            raise HomeAssistantError(error)

    async def assign_profile_devices(self, owner_id: str, macs: list[str]) -> dict[str, Any]:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            status, result = await self._run_router_request(lambda: assign_profile_devices(
                self.router, self.logger, owner_id, macs,
            ))
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            self.parental_status = ParentalStatus(None)
            self.async_update_listeners()
            raise HomeAssistantError(
                "Batch outcome is unknown; refresh and inspect every selected device. No retry was made"
            ) from None
        self.parental_status = status
        self.async_update_listeners()
        await self.async_request_refresh()
        return result

    async def get_profile_feature(self, kind: str, owner_id: str = "") -> dict[str, Any]:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            if kind == "creation_options":
                return await self._run_router_request(lambda: profile_creation_options(self.router))
            if kind == "report":
                return await self._run_router_request(lambda: read_profile_report(self.router, owner_id))
            if kind == "delete_preview":
                return await self._run_router_request(lambda: deletion_preview(self.router, owner_id))
            raise ParentalEditError("Unknown profile read")
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            raise HomeAssistantError("Profile read failed; no private report data was retained") from None

    async def create_parental_profile(
        self, name: str, filter_level: str, categories: list[str],
    ) -> dict[str, Any]:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            status, result = await self._run_router_request(
                lambda: create_profile(self.router, name, filter_level, categories),
            )
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            self.parental_status = ParentalStatus(None)
            self.async_update_listeners()
            raise HomeAssistantError(
                "Creation outcome is unknown; inspect profiles before retrying. No automatic retry was made"
            ) from None
        self.parental_status = status
        self.async_update_listeners()
        await self.async_request_refresh()
        return result

    async def manage_parental_profile(self, action: str, owner_id: str, **values: str) -> None:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            if action == "rename_profile":
                status, error = await self._run_router_request(
                    lambda: rename_profile(
                        self.router, self.logger, owner_id, values["expected_name"], values["name"],
                    ),
                )
            elif action == "delete_profile":
                status, error = await self._run_router_request(
                    lambda: delete_profile(self.router, owner_id, values["revision"]),
                )
            else:
                raise ParentalEditError("Unknown profile management action")
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            self.parental_status = ParentalStatus(None)
            self.async_update_listeners()
            raise HomeAssistantError("Profile change is unconfirmed; inspect actual profiles before retrying") from None
        self.parental_status = status
        self.async_update_listeners()
        await self.async_request_refresh()
        if error:
            raise HomeAssistantError(error)

    async def _edit_parental_profile(
        self, owner_id: str, *, changes: dict[str, bool | int] | None = None,
        add_device: str | None = None, remove_device: str | None = None,
    ) -> None:
        if self.parental_status is None:
            raise HomeAssistantError("Parental controls are unsupported")
        try:
            status, error = await self._run_router_request(lambda: edit_profile(
                self.router, self.logger, owner_id,
                changes=changes, add_device=add_device, remove_device=remove_device,
            ))
        except ParentalEditError as error:
            raise HomeAssistantError(str(error)) from None
        except Exception:
            self.parental_status = ParentalStatus(None)
            self.async_update_listeners()
            raise HomeAssistantError("Unable to edit parental profile; read or transport failed") from None
        self.parental_status = status
        self.async_update_listeners()
        await self.async_request_refresh()
        if error is not None:
            raise HomeAssistantError(error)

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
                    self.reservations,
                    self.logger,
                    self.mesh_nodes,
                    self.led_status,
                    self.parental_status,
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
                        self.mesh_nodes,
                        self.led_status,
                        self.parental_status,
                    ) = await self.hass.async_add_executor_job(update_once)

                if sms_list is not None:
                    self._process_sms_list(sms_list)
                self._last_update_time = datetime.now()
                self.network_updated_at = datetime.now().astimezone()
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
