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
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from .const import (
    DOMAIN,
    DEFAULT_USER,
    EVENT_NEW_SMS,
    CONF_CLIENT_CLASS,
    CONF_SUPPORT_VPN,
    CONF_SUPPORT_TRACKER,
    CONF_SUPPORT_DHCP_RESERVATIONS,
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
from .coordinator import TPLinkRouterCoordinator
from .utils import validate_ipv4_address, validate_mac_address
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
PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Construct the device
    host = entry.data[CONF_HOST]
    if not (host.startswith('http://') or host.startswith('https://')):
        host = "http://{}".format(host)
    verify_ssl = entry.data[CONF_VERIFY_SSL] if CONF_VERIFY_SSL in entry.data else False
    support_vpn = entry.data.get(CONF_SUPPORT_VPN, True)
    support_dhcp_reservations = entry.data.get(CONF_SUPPORT_DHCP_RESERVATIONS, True)

    try:
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
            # Check if router is serving_cells compatible
            serving_cells = None
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
        ) = await hass.async_add_executor_job(
            TPLinkRouterCoordinator.request, client, callback
        )
    except Exception as error:
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
                                          support_dhcp_reservations=support_dhcp_reservations)

    if sms_list is not None:
        coordinator._process_sms_list(sms_list)
        coordinator._last_update_time = datetime.now()
    _async_add_listeners(hass, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

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
            for svc in ("send_sms", "add_reservation", "delete_reservation"):
                if hass.services.has_service(DOMAIN, svc):
                    hass.services.async_remove(DOMAIN, svc)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(config_entry.entry_id)


def register_services(hass: HomeAssistant, coord: TPLinkRouterCoordinator) -> None:
    dr = device_registry.async_get(hass)

    def _get_coordinator(service: ServiceCall, method_name: str) -> TPLinkRouterCoordinator | None:
        device = dr.async_get(service.data.get("device"))
        if device is None:
            _LOGGER.error('TplinkRouter Integration Exception - device was not found')
            return None
        domain_data = hass.data.get(DOMAIN, {})
        for key in device.config_entries:
            entry = hass.config_entries.async_get_entry(key)
            if not entry or entry.domain != DOMAIN:
                continue
            coordinator = domain_data.get(key)
            if coordinator is None or not hasattr(coordinator.router, method_name):
                continue
            if method_name in ("add_ipv4_reservation", "delete_ipv4_reservation") and not getattr(
                coordinator, "support_dhcp_reservations", True
            ):
                continue
            return coordinator

        _LOGGER.error('TplinkRouter Integration Exception - This device does not support %s', method_name)
        return None

    if hasattr(coord.router, "send_sms") and coord.lte_status is not None:
        async def send_sms_service(service: ServiceCall) -> None:
            coordinator = _get_coordinator(service, "send_sms")
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
            coordinator = _get_coordinator(service, "add_ipv4_reservation")
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
            coordinator = _get_coordinator(service, "delete_ipv4_reservation")
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
