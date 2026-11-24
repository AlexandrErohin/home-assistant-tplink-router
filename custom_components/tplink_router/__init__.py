import base64
import binascii
import re

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    Platform,
)
from datetime import datetime
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from .const import (
    DOMAIN,
    DEFAULT_USER,
    EVENT_NEW_SMS,
    CONF_CLIENT_CLASS,
    CONF_DECO_TMP_USERNAME,
    CONF_DECO_TMP_HOST_KEY_SHA256,
    CONF_SUPPORT_VPN,
    CONF_SUPPORT_TRACKER,
    CONF_SUPPORT_DHCP_RESERVATIONS,
    CONF_SUPPORT_SERVING_CELLS,
    CONF_SCAN_RETRIES,
    CONF_SCAN_BACKOFF,
    CONF_SCAN_PAUSE,
    CONF_OFFLINE_TIMEOUT,
    DEFAULT_SCAN_RETRIES,
    DEFAULT_SCAN_BACKOFF,
    DEFAULT_SCAN_PAUSE,
    DEFAULT_OFFLINE_TIMEOUT,
)
import logging
from .coordinator import (
    TPLinkRouterCoordinator,
    collect_mesh_nodes,
    supports_access_control,
    supports_led_control,
    is_verified_deco_wifi_client,
)
from .utils import validate_ipv4_address, validate_mac_address, is_retryable_error
from homeassistant.helpers import device_registry


def _vol_mac(value: str) -> str:
    try:
        return validate_mac_address(value)
    except ValueError as err:
        raise vol.Invalid(str(err)) from err


def _vol_ipv4(value: str) -> str:
    try:
        return validate_ipv4_address(value)
    except ValueError as err:
        raise vol.Invalid(str(err)) from err


ADD_RESERVATION_SCHEMA = vol.Schema(
    {
        vol.Required("device"): cv.string,
        vol.Required("mac"): vol.All(cv.string, _vol_mac),
        vol.Required("ip"): vol.All(cv.string, _vol_ipv4),
        vol.Optional("comment", default=""): cv.string,
        vol.Optional("enable", default=True): cv.boolean,
    }
)
DELETE_RESERVATION_SCHEMA = vol.Schema(
    {
        vol.Required("device"): cv.string,
        vol.Required("mac"): vol.All(cv.string, _vol_mac),
    }
)
BLOCK_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("device"): cv.string,
        vol.Required("mac"): vol.All(cv.string, _vol_mac),
        vol.Optional("name", default=""): cv.string,
    }
)
UNBLOCK_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("device"): cv.string,
        vol.Required("mac"): vol.All(cv.string, _vol_mac),
    }
)
SERVICES = ("send_sms", "add_reservation", "delete_reservation", "block_device", "unblock_device")
PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)
_TMP_CONFIG_ERROR = "Deco app control requires a valid account SHA-1 and host-key fingerprint"


class DecoTmpConfigurationError(ValueError):
    """An invalid local Deco app-control configuration, without private values."""


def validate_deco_tmp_config(data: dict) -> dict[str, str] | None:
    """Validate both optional app-control fields without contacting the router."""
    username = data.get(CONF_DECO_TMP_USERNAME)
    pin = data.get(CONF_DECO_TMP_HOST_KEY_SHA256)
    if username in (None, "") and pin in (None, ""):
        return None
    if not isinstance(username, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", username):
        raise DecoTmpConfigurationError(_TMP_CONFIG_ERROR)
    if not isinstance(pin, str) or not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", pin):
        raise DecoTmpConfigurationError(_TMP_CONFIG_ERROR)
    try:
        digest = base64.b64decode(pin[7:] + "=", validate=True)
    except (binascii.Error, ValueError):
        raise DecoTmpConfigurationError(_TMP_CONFIG_ERROR) from None
    canonical = "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
    if len(digest) != 32 or canonical != pin:
        raise DecoTmpConfigurationError(_TMP_CONFIG_ERROR)
    return {"username_sha1": username.lower(), "host_key_sha256": pin}


def configure_deco_tmp_wifi(client, data: dict) -> None:
    """Bind optional app control locally; setup never opens a TMP connection."""
    settings = validate_deco_tmp_config(data)
    if settings is None:
        return
    configure = getattr(client, "configure_tmp_wifi", None)
    if not is_verified_deco_wifi_client(client) or not callable(configure):
        raise DecoTmpConfigurationError("Deco app control is not supported by this router client")
    try:
        configure(**settings)
    except ValueError:
        raise DecoTmpConfigurationError(_TMP_CONFIG_ERROR) from None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Construct the device
    host = entry.data[CONF_HOST]
    if not (host.startswith('http://') or host.startswith('https://')):
        host = "http://{}".format(host)
    verify_ssl = entry.data[CONF_VERIFY_SSL] if CONF_VERIFY_SSL in entry.data else False
    support_vpn = entry.data.get(CONF_SUPPORT_VPN, True)
    support_dhcp_reservations = entry.data.get(CONF_SUPPORT_DHCP_RESERVATIONS, True)
    support_serving_cells = entry.data.get(CONF_SUPPORT_SERVING_CELLS, True)

    try:
        validate_deco_tmp_config(entry.data)
        client_class = entry.data.get(CONF_CLIENT_CLASS)
        if not client_class:
            client = await TPLinkRouterCoordinator.get_client(
                hass=hass,
                host=host,
                password=entry.data[CONF_PASSWORD],
                username=entry.data.get(CONF_USERNAME, DEFAULT_USER),
                logger=_LOGGER,
                verify_ssl=verify_ssl
            )
            new_data = dict(entry.data)
            new_data[CONF_CLIENT_CLASS] = client.__class__.__name__
            hass.config_entries.async_update_entry(
                entry,
                data=new_data,
            )
        else:
            client = TPLinkRouterCoordinator.get_client_by_class(client_class)(
                host=host,
                password=entry.data[CONF_PASSWORD],
                username=entry.data.get(CONF_USERNAME, DEFAULT_USER),
                logger=_LOGGER,
                verify_ssl=verify_ssl
            )

        configure_deco_tmp_wifi(client, entry.data)

        def callback():
            firm = client.get_firmware()
            stat = client.get_status()
            # Check if router is lte_status compatible
            lte_stat = None
            if hasattr(client, "get_lte_status"):
                try:
                    lte_stat = client.get_lte_status()
                except Exception as err:
                    _LOGGER.debug(
                        "TP-Link router %s: get_lte_status failed: %s",
                        client.__class__.__name__,
                        err,
                    )
            # Check router VPN compatibility, if needed
            vpn_server_stat = None
            vpn_client_stat = None
            if support_vpn:
                # Check if router is vpn_server compatible
                if hasattr(client, "get_vpn_status"):
                    try:
                        vpn_server_stat = client.get_vpn_status()
                    except Exception as err:
                        _LOGGER.debug(
                            "TP-Link router %s: get_vpn_status failed: %s",
                            client.__class__.__name__,
                            err,
                        )
                # Check if router is vpn_client compatible
                if hasattr(client, "get_vpn_client_status"):
                    try:
                        vpn_client_stat = client.get_vpn_client_status()
                    except Exception as err:
                        _LOGGER.debug(
                            "TP-Link router %s: get_vpn_client_status failed: %s",
                            client.__class__.__name__,
                            err,
                        )
            # Check router serving_cells compatibility, if needed
            serving_cells = None
            if support_serving_cells:
                # Check if router is serving_cells compatible
                if hasattr(client, "get_lte_serving_cells"):
                    try:
                        serving_cells = client.get_lte_serving_cells()
                    except Exception as err:
                        _LOGGER.debug(
                            "TP-Link router %s: get_lte_serving_cells failed: %s",
                            client.__class__.__name__,
                            err,
                        )
            # Check if router is port_status compatible
            port_status = None
            if hasattr(client, "get_port_status"):
                try:
                    port_status = client.get_port_status()
                except Exception as err:
                    _LOGGER.debug(
                        "TP-Link router %s: get_port_status failed: %s",
                        client.__class__.__name__,
                        err,
                    )
            sms_list = None
            if hasattr(client, "get_sms") and lte_stat is not None:
                try:
                    sms_list = client.get_sms()
                except Exception as err:
                    _LOGGER.debug(
                        "TP-Link router %s: get_sms failed: %s",
                        client.__class__.__name__,
                        err,
                    )
            reservations = None
            if support_dhcp_reservations and hasattr(client, "get_ipv4_reservations"):
                try:
                    reservations = client.get_ipv4_reservations()
                except Exception as err:
                    _LOGGER.debug(
                        "TP-Link router %s: get_ipv4_reservations failed: %s",
                        client.__class__.__name__,
                        err,
                    )
            # Probe EasyMesh once so node trackers exist before the first poll.
            # None = unsupported (stop asking); a list (even empty) keeps polling.
            mesh_nodes = collect_mesh_nodes(client, _LOGGER)
            led_status = None
            if supports_led_control(client):
                try:
                    led_status = client.led_status()
                except Exception as err:
                    _LOGGER.debug(
                        "TP-Link router %s: led_status failed: %s",
                        client.__class__.__name__,
                        err,
                    )
            # Probe Access Control once: a client class shared by many models may
            # have the methods while this firmware has no Access Control page.
            access_control = None
            blocked_devices = None
            if supports_access_control(client):
                try:
                    blocked_devices = client.get_blocked_devices()
                    access_control = client.get_access_control()
                except Exception as err:
                    access_control = None
                    blocked_devices = None
                    _LOGGER.debug(
                        "TP-Link router %s: Access Control failed: %s",
                        client.__class__.__name__,
                        err,
                    )
            return (
                firm,
                stat,
                lte_stat,
                vpn_server_stat,
                vpn_client_stat,
                serving_cells,
                port_status,
                sms_list,
                reservations,
                mesh_nodes,
                led_status,
                access_control,
                blocked_devices,
            )

        (
            firmware,
            status,
            lte_status,
            vpn_server_stat,
            vpn_client_status,
            serving_cells,
            port_status,
            sms_list,
            reservations,
            mesh_nodes,
            led_status,
            access_control,
            blocked_devices,
        ) = await hass.async_add_executor_job(
            TPLinkRouterCoordinator.request, client, callback
        )
    except DecoTmpConfigurationError as error:
        _LOGGER.error("TPLink Router app-control configuration failed: %s", error)
        return False
    except Exception as error:
        if is_retryable_error(error):
            raise ConfigEntryNotReady(
                f"TPLink Router setup failed for {host}: {error}"
            ) from error
        _LOGGER.error(
            "TPLink Router setup failed for %s: %s",
            host,
            error,
            exc_info=True,
        )
        return False
    # Create device coordinator and fetch data
    coordinator = TPLinkRouterCoordinator(hass, client, entry.data[CONF_SCAN_INTERVAL], firmware, status,
                                          lte_status, _LOGGER, entry.entry_id, vpn_server_stat, vpn_client_status,
                                          serving_cells, port_status,
                                          retries=entry.data.get(CONF_SCAN_RETRIES, DEFAULT_SCAN_RETRIES),
                                          backoff_seconds=entry.data.get(CONF_SCAN_BACKOFF, DEFAULT_SCAN_BACKOFF),
                                          scan_pause_minutes=entry.data.get(CONF_SCAN_PAUSE, DEFAULT_SCAN_PAUSE),
                                          offline_timeout_seconds=entry.data.get(
                                              CONF_OFFLINE_TIMEOUT, DEFAULT_OFFLINE_TIMEOUT),
                                          reservations=reservations,
                                          support_dhcp_reservations=support_dhcp_reservations,
                                          mesh_nodes=mesh_nodes,
                                          led_status=led_status,
                                          access_control=access_control,
                                          blocked_devices=blocked_devices)

    if sms_list is not None:
        coordinator._process_sms_list(sms_list)
        coordinator._last_update_time = datetime.now()
    _async_add_listeners(hass, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Register the router device before platforms so client/mesh via_device_id
    # lookups can resolve the parent (via_device tuples are deprecated).
    device_registry.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers=coordinator.device_info["identifiers"],
        connections=coordinator.device_info.get("connections"),
        manufacturer=coordinator.device_info.get("manufacturer"),
        model=coordinator.device_info.get("model"),
        name=coordinator.device_info.get("name"),
        sw_version=coordinator.device_info.get("sw_version"),
        hw_version=coordinator.device_info.get("hw_version"),
        configuration_url=coordinator.device_info.get("configuration_url"),
    )

    platforms = list(PLATFORMS)
    if not entry.data.get(CONF_SUPPORT_TRACKER, True):
        platforms.remove(Platform.DEVICE_TRACKER)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    register_services(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = list(PLATFORMS)
    if not entry.data.get(CONF_SUPPORT_TRACKER, True):
        platforms.remove(Platform.DEVICE_TRACKER)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            for svc in SERVICES:
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(config_entry.entry_id)


def get_coordinator_for_device(
    hass: HomeAssistant,
    device_id: str | None,
    method_name: str,
) -> TPLinkRouterCoordinator | None:
    """Return the loaded coordinator that owns ``device_id`` for a service call.

    Uses the config-entry-scoped device-registry helper instead of the deprecated
    ``DeviceEntry.config_entries`` multi-entry set.
    """
    if not device_id:
        _LOGGER.error('TplinkRouter Integration Exception - device was not found')
        return None

    _device, entry = device_registry.async_get_device_and_config_entry_for_domain(
        hass, device_id, domain=DOMAIN
    )
    if entry is None:
        _LOGGER.error('TplinkRouter Integration Exception - device was not found')
        return None

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None or not hasattr(coordinator.router, method_name):
        _LOGGER.error(
            'TplinkRouter Integration Exception - This device does not support %s',
            method_name,
        )
        return None
    if method_name in ("add_ipv4_reservation", "delete_ipv4_reservation") and not getattr(
        coordinator, "support_dhcp_reservations", True
    ):
        _LOGGER.error(
            'TplinkRouter Integration Exception - This device does not support %s',
            method_name,
        )
        return None
    if method_name in ("block_device", "unblock_device") and getattr(
        coordinator, "blocked_devices", None
    ) is None:
        _LOGGER.error(
            'TplinkRouter Integration Exception - This device does not support %s',
            method_name,
        )
        return None
    return coordinator


def register_services(hass: HomeAssistant, coord: TPLinkRouterCoordinator) -> None:
    if hasattr(coord.router, "send_sms") and coord.lte_status is not None:
        async def send_sms_service(service: ServiceCall) -> None:
            coordinator = get_coordinator_for_device(
                hass, service.data.get("device"), "send_sms"
            )
            if coordinator is None:
                return
            await coordinator.send_sms(
                service.data.get("number"),
                service.data.get("text"),
            )

        if not hass.services.has_service(DOMAIN, 'send_sms'):
            hass.services.async_register(DOMAIN, 'send_sms', send_sms_service)

    if coord.support_dhcp_reservations and hasattr(coord.router, "add_ipv4_reservation"):
        async def add_reservation_service(service: ServiceCall) -> None:
            coordinator = get_coordinator_for_device(
                hass, service.data.get("device"), "add_ipv4_reservation"
            )
            if coordinator is None:
                return
            await coordinator.add_ipv4_reservation(
                service.data["mac"],
                service.data["ip"],
                service.data.get("comment", ""),
                service.data.get("enable", True),
            )

        if not hass.services.has_service(DOMAIN, 'add_reservation'):
            hass.services.async_register(
                DOMAIN,
                'add_reservation',
                add_reservation_service,
                schema=ADD_RESERVATION_SCHEMA,
            )

    if coord.support_dhcp_reservations and hasattr(coord.router, "delete_ipv4_reservation"):
        async def delete_reservation_service(service: ServiceCall) -> None:
            coordinator = get_coordinator_for_device(
                hass, service.data.get("device"), "delete_ipv4_reservation"
            )
            if coordinator is None:
                return
            await coordinator.delete_ipv4_reservation(service.data["mac"])

        if not hass.services.has_service(DOMAIN, 'delete_reservation'):
            hass.services.async_register(
                DOMAIN,
                'delete_reservation',
                delete_reservation_service,
                schema=DELETE_RESERVATION_SCHEMA,
            )

    if coord.blocked_devices is not None:
        async def block_device_service(service: ServiceCall) -> None:
            coordinator = get_coordinator_for_device(
                hass, service.data.get("device"), "block_device"
            )
            if coordinator is None:
                return
            await coordinator.block_device(service.data["mac"], service.data.get("name", ""))

        async def unblock_device_service(service: ServiceCall) -> None:
            coordinator = get_coordinator_for_device(
                hass, service.data.get("device"), "unblock_device"
            )
            if coordinator is None:
                return
            await coordinator.unblock_device(service.data["mac"])

        if not hass.services.has_service(DOMAIN, 'block_device'):
            hass.services.async_register(
                DOMAIN, 'block_device', block_device_service, schema=BLOCK_DEVICE_SCHEMA
            )
        if not hass.services.has_service(DOMAIN, 'unblock_device'):
            hass.services.async_register(
                DOMAIN, 'unblock_device', unblock_device_service, schema=UNBLOCK_DEVICE_SCHEMA
            )


def _async_add_listeners(hass: HomeAssistant, coord: TPLinkRouterCoordinator) -> None:

    if not hasattr(coord.router, "get_sms") or coord.lte_status is None:
        return

    coord.async_add_listener(
        lambda: _fire_sms_event(hass, coord)
    )


def _fire_sms_event(hass: HomeAssistant, coord: TPLinkRouterCoordinator) -> None:
    for sms in coord.new_sms:
        hass.bus.fire(
            EVENT_NEW_SMS,
            {
                'sender': sms.sender,
                'content': sms.content,
                'received_at': sms.received_at.isoformat(),
            },
        )
    coord.new_sms = []
