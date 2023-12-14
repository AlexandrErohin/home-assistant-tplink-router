"""Config flow for Simple Integration integration."""
import logging

import voluptuous as vol
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
from .const import DOMAIN
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
)
from tplinkrouterc6u import TplinkRouter

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default='http://192.168.0.1'): str,
        vol.Required(CONF_USERNAME, default='admin'): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_SCAN_INTERVAL, default=30): int,
        vol.Required(CONF_VERIFY_SSL, default=True): cv.boolean,
    }
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            router = TplinkRouter(
                user_input[CONF_HOST],
                user_input[CONF_PASSWORD],
                user_input[CONF_USERNAME],
                _LOGGER,
                user_input[CONF_VERIFY_SSL],
            )
            try:
                if await self.hass.async_add_executor_job(router.authorize):
                    return self.async_create_entry(title=user_input["host"], data=user_input)
                else:
                    errors['base'] = 'Cannot connect to the router, check logs for more info'
            except Exception as error:
                _LOGGER.error('TplinkRouter Integration Exception - {}'.format(error))
                errors['base'] = str(error)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)
