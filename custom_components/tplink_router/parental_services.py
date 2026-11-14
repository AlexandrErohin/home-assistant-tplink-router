"""Profile actions resolved against the entity registry, never a separate client."""
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry

from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator
from .parental_control import PERIODS
from .permissions import require_admin


PARENTAL_SERVICES = (
    "get_parental_devices", "assign_parental_device", "remove_parental_device",
    "set_parental_bedtime", "set_parental_daily_limit",
)


def _resolve_profile(hass: HomeAssistant, entity_id: str) -> tuple[TPLinkRouterCoordinator, str]:
    entry = entity_registry.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or entry.domain != "switch":
        raise HomeAssistantError("Select a TP-Link parental internet-access switch")
    coordinator = hass.data.get(DOMAIN, {}).get(entry.config_entry_id)
    if coordinator is None or coordinator.parental_status is None:
        raise HomeAssistantError("Parental profile integration is not loaded or supported")
    prefix = f"{coordinator.unique_id}_{DOMAIN}_parental_access_"
    if not entry.unique_id.startswith(prefix) or not entry.unique_id[len(prefix):].strip():
        raise HomeAssistantError("Select a parental internet-access switch, not a schedule or router switch")
    return coordinator, entry.unique_id[len(prefix):]


def register_parental_services(hass: HomeAssistant) -> None:
    async def get_devices(service: ServiceCall) -> dict[str, Any]:
        coordinator, owner_id = _resolve_profile(hass, service.data["profile"])
        return {"devices": await coordinator.get_parental_devices(owner_id, service.data.get("scope", "profile"))}

    async def assign_device(service: ServiceCall) -> None:
        coordinator, owner_id = _resolve_profile(hass, service.data["profile"])
        await coordinator.set_profile_device(owner_id, service.data["device_id"], True)

    async def remove_device(service: ServiceCall) -> None:
        coordinator, owner_id = _resolve_profile(hass, service.data["profile"])
        await coordinator.set_profile_device(owner_id, service.data["device_id"], False)

    async def bedtime(service: ServiceCall) -> None:
        coordinator, owner_id = _resolve_profile(hass, service.data["profile"])
        await coordinator.set_profile_schedule(
            owner_id, service.data["period"], "bed_time",
            **{key: service.data[key] for key in ("enabled", "begin", "end") if key in service.data},
        )

    async def daily_limit(service: ServiceCall) -> None:
        coordinator, owner_id = _resolve_profile(hass, service.data["profile"])
        await coordinator.set_profile_schedule(
            owner_id, service.data["period"], "time_limit",
            **{key: service.data[key] for key in ("enabled", "minutes") if key in service.data},
        )

    profile = {vol.Required("profile"): cv.entity_id}
    period = {**profile, vol.Required("period"): vol.In(PERIODS), vol.Optional("enabled"): bool}
    devices = {**profile, vol.Required("device_id"): vol.All(cv.string, vol.Length(min=1))}
    registrations = (
        ("get_parental_devices", get_devices, vol.Schema({
            **profile, vol.Optional("scope", default="profile"): vol.In(("profile", "inventory")),
        }), SupportsResponse.ONLY),
        ("assign_parental_device", assign_device, vol.Schema(devices), SupportsResponse.NONE),
        ("remove_parental_device", remove_device, vol.Schema(devices), SupportsResponse.NONE),
        ("set_parental_bedtime", bedtime, vol.Schema({
            **period, vol.Optional("begin"): cv.string, vol.Optional("end"): cv.string,
        }), SupportsResponse.NONE),
        ("set_parental_daily_limit", daily_limit, vol.Schema({
            **period, vol.Optional("minutes"): vol.All(vol.Any(int, float), vol.Range(min=15, max=960)),
        }), SupportsResponse.NONE),
    )
    for name, handler, schema, response in registrations:
        if not hass.services.has_service(DOMAIN, name):
            async def authorized(service: ServiceCall, handler=handler):
                await require_admin(hass, service.context)
                return await handler(service)

            hass.services.async_register(DOMAIN, name, authorized, schema=schema, supports_response=response)
