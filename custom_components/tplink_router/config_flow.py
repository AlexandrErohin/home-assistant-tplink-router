"""Config flow for Simple Integration integration."""
import logging

import voluptuous as vol
from typing import Any
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN
from .coordinator import TPLinkRouterCoordinator
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default='http://192.168.0.1'): str,
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
            try:
                router = await TPLinkRouterCoordinator.get_client(
                    hass=self.hass,
                    host=user_input[CONF_HOST],
                    password=user_input[CONF_PASSWORD],
                    logger=_LOGGER,
                    verify_ssl=user_input[CONF_VERIFY_SSL],
                )
                await self.hass.async_add_executor_job(router.authorize)
                return self.async_create_entry(title=user_input["host"], data=user_input)
            except Exception as error:
                _LOGGER.error('TplinkRouter Integration Exception - {}'.format(error))
                errors['base'] = str(error)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlowWithConfigEntry):

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        data = user_input or self.config_entry.data

        if user_input is not None:
            try:
                router = await TPLinkRouterCoordinator.get_client(
                    hass=self.hass,
                    host=user_input[CONF_HOST],
                    password=user_input[CONF_PASSWORD],
                    logger=_LOGGER,
                    verify_ssl=user_input[CONF_VERIFY_SSL],
                )
                await self.hass.async_add_executor_job(router.authorize)
                self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
                return self.async_create_entry(title=user_input["host"], data=user_input)
            except Exception as error:
                _LOGGER.error('TplinkRouter Integration Exception - {}'.format(error))
                errors['base'] = str(error)

        data_schema = vol.Schema({
            vol.Required(CONF_HOST, default=data.get(CONF_HOST)): cv.string,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD)): cv.string,
            vol.Required(CONF_SCAN_INTERVAL, default=data.get(CONF_SCAN_INTERVAL)): int,
            vol.Required(CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL)): cv.boolean,
        })

        return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)
