"""Config flow for Simple Integration integration."""
import logging

import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
)
from tplinkrouterc6u import TplinkRouter

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default='192.168.0.1'): str,
        vol.Required(CONF_USERNAME, default='admin'): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SCAN_INTERVAL, default=30): int,
    }
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            router = TplinkRouter(user_input[CONF_HOST],user_input[CONF_PASSWORD], user_input[CONF_USERNAME], _LOGGER)
            try:
                await router.test_connect()
                return self.async_create_entry(title=user_input["host"], data=user_input)
            except Exception as error:
                _LOGGER.error(error)
                errors['base'] = str(error)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)
