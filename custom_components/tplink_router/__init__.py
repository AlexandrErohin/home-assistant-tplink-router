from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN, DEFAULT_USER, EVENT_NEW_SMS
import logging
from .coordinator import TPLinkRouterCoordinator
from homeassistant.helpers import device_registry

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Construct the device
    host = entry.data[CONF_HOST]
    if not (host.startswith('http://') or host.startswith('https://')):
        host = "http://{}".format(host)
    verify_ssl = entry.data[CONF_VERIFY_SSL] if CONF_VERIFY_SSL in entry.data else True
    client = await TPLinkRouterCoordinator.get_client(
        hass=hass,
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
            except Exception:
                pass

        return firm, stat, lte_stat

    firmware, status, lte_status = await hass.async_add_executor_job(TPLinkRouterCoordinator.request, client, callback)

    # Create device coordinator and fetch data
    coordinator = TPLinkRouterCoordinator(hass, client, entry.data[CONF_SCAN_INTERVAL], firmware, status,
                                          lte_status, _LOGGER, entry.entry_id)

    await coordinator.async_config_entry_first_refresh()
    _async_add_listeners(hass, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    register_services(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(config_entry.entry_id)


def register_services(hass: HomeAssistant, coord: TPLinkRouterCoordinator) -> None:

    if not hasattr(coord.router, "send_sms") or coord.lte_status is None:
        return

    dr = device_registry.async_get(hass)

    async def send_sms_service(service: ServiceCall) -> None:
        device = dr.async_get(service.data.get("device"))
        if device is None:
            _LOGGER.error('TplinkRouter Integration Exception - device was not found')
            return
        coordinator = None
        for key in device.config_entries:
            entry = hass.config_entries.async_get_entry(key)
            if not entry:
                continue
            if entry.domain != DOMAIN or not hasattr(hass.data[DOMAIN][key].router, "send_sms"):
                continue
            coordinator = hass.data[DOMAIN][key]

        if coordinator is None:
            _LOGGER.error('TplinkRouter Integration Exception - This device cannot send SMS')
            return

        def callback():
            coord.router.send_sms(service.data.get("number"), service.data.get("text"))
        await hass.async_add_executor_job(TPLinkRouterCoordinator.request, coord.router, callback)

    if not hass.services.has_service(DOMAIN, 'send_sms'):
        hass.services.async_register(DOMAIN, 'send_sms', send_sms_service)


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
