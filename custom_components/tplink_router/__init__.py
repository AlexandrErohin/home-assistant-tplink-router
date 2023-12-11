from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN
import logging
from tplinkrouterc6u import TplinkRouter
from .coordinator import TPLinkRouterCoordinator

PLATFORMS: list[Platform] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Construct the device
    host = config_entry.data[CONF_HOST]
    if not (host.startswith('http://') or host.startswith('https://')):
        host = "http://{}".format(host)
    password = config_entry.data[CONF_PASSWORD]
    username = config_entry.data[CONF_USERNAME]
    verify_ssl = config_entry.data[CONF_VERIFY_SSL] if CONF_VERIFY_SSL in config_entry.data else True
    device = TplinkRouter(host, password, username, _LOGGER, verify_ssl)
    info = await hass.async_add_executor_job(device.get_full_info)

    # Create device coordinator and fetch data
    coord = TPLinkRouterCoordinator(hass, device, config_entry.data[CONF_SCAN_INTERVAL], info, _LOGGER)
    await coord.async_config_entry_first_refresh()

    # Store coordinator in global data
    hass.data[DOMAIN][config_entry.entry_id] = coord

    # Create platform entries
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS))

    # Reload entry when its updated
    config_entry.async_on_unload(
        config_entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(config_entry.entry_id)
