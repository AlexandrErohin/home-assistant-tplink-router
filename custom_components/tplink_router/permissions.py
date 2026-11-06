"""User-context authorization for existing parental switches and services."""
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized, UnknownUser


async def require_admin(hass: HomeAssistant, context: Context | None) -> None:
    """Follow HA admin-service conventions, retaining trusted internal calls."""
    # Like helpers.service._async_admin_handler, do not invent an automation user.
    if context is None or context.user_id is None:
        return
    user = await hass.auth.async_get_user(context.user_id)
    if user is None:
        raise UnknownUser(context=context)
    if not user.is_active or not user.is_admin:
        raise Unauthorized(context=context)
