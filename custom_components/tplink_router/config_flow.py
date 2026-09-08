import logging
import voluptuous as vol
from typing import Any
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from .const import (
    DOMAIN, DEFAULT_USER, DEFAULT_HOST, CONF_CLIENT_CLASS,
    CONF_SUPPORT_VPN, CONF_SUPPORT_TRACKER, CONF_SCAN_RETRIES, CONF_SCAN_BACKOFF,
    CONF_SCAN_PAUSE, CONF_OFFLINE_TIMEOUT, DEFAULT_SCAN_RETRIES, DEFAULT_SCAN_BACKOFF,
    DEFAULT_SCAN_PAUSE, DEFAULT_OFFLINE_TIMEOUT, MAX_SCAN_RETRIES, MAX_SCAN_BACKOFF,
    MAX_SCAN_PAUSE, MAX_OFFLINE_TIMEOUT,
)
from .coordinator import TPLinkRouterCoordinator
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
)

_LOGGER = logging.getLogger(__name__)

SCAN_RETRIES_SCHEMA = vol.All(
    cv.positive_int,
    vol.Range(min=1, max=MAX_SCAN_RETRIES),
)
SCAN_BACKOFF_SCHEMA = vol.All(
    cv.positive_float,
    vol.Range(min=0.1, max=MAX_SCAN_BACKOFF),
)
SCAN_PAUSE_SCHEMA = vol.All(
    vol.Coerce(int),
    vol.Range(min=0, max=MAX_SCAN_PAUSE),
)
OFFLINE_TIMEOUT_SCHEMA = vol.All(
    vol.Coerce(int),
    vol.Range(min=0, max=MAX_OFFLINE_TIMEOUT),
)


def _user_schema(
    data: dict[str, Any] | None = None,
    *,
    include_username: bool = False,
) -> vol.Schema:
    data = data or {}
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=data.get(CONF_HOST, DEFAULT_HOST)): str,
        vol.Required(CONF_PASSWORD): cv.string,
    }
    if include_username:
        schema[
            vol.Required(
                CONF_USERNAME,
                default=data.get(CONF_USERNAME, DEFAULT_USER),
            )
        ] = str
    schema.update(
        {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=data.get(CONF_SCAN_INTERVAL, 30),
            ): int,
            vol.Optional(
                CONF_SCAN_RETRIES,
                default=data.get(CONF_SCAN_RETRIES, DEFAULT_SCAN_RETRIES),
            ): SCAN_RETRIES_SCHEMA,
            vol.Optional(
                CONF_SCAN_BACKOFF,
                default=data.get(CONF_SCAN_BACKOFF, DEFAULT_SCAN_BACKOFF),
            ): SCAN_BACKOFF_SCHEMA,
            vol.Optional(
                CONF_SCAN_PAUSE,
                default=data.get(CONF_SCAN_PAUSE, DEFAULT_SCAN_PAUSE),
            ): SCAN_PAUSE_SCHEMA,
            vol.Optional(
                CONF_OFFLINE_TIMEOUT,
                default=data.get(CONF_OFFLINE_TIMEOUT, DEFAULT_OFFLINE_TIMEOUT),
            ): OFFLINE_TIMEOUT_SCHEMA,
            vol.Required(
                CONF_VERIFY_SSL,
                default=data.get(CONF_VERIFY_SSL, False),
            ): cv.boolean,
        }
    )
    return vol.Schema(schema, extra=vol.ALLOW_EXTRA)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self.data_initial: dict[str, Any] = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step: connection settings and router auth."""
        errors = {}
        if user_input is not None:
            try:
                router = await TPLinkRouterCoordinator.get_client(
                    hass=self.hass,
                    host=user_input[CONF_HOST],
                    password=user_input[CONF_PASSWORD],
                    username=user_input.get(CONF_USERNAME, DEFAULT_USER),
                    logger=_LOGGER,
                    verify_ssl=user_input[CONF_VERIFY_SSL],
                )

                def authorize_and_status():
                    return TPLinkRouterCoordinator.request(router, router.get_status)

                status = await self.hass.async_add_executor_job(authorize_and_status)
                await self.async_set_unique_id(status.lan_macaddr.lower())
                self._abort_if_unique_id_configured()

                user_input[CONF_CLIENT_CLASS] = router.__class__.__name__
                self.data_initial = user_input
                return await self.async_step_custom()
            except AbortFlow:
                raise
            except Exception as error:
                _LOGGER.error("TplinkRouter Integration Exception - %s", error)
                errors["base"] = str(error)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(
                user_input,
                include_username=user_input is not None,
            ),
            errors=errors,
        )

    async def async_step_custom(self, user_input=None):
        """Handle functional customization options after a successful auth."""
        if user_input is not None:
            data = {**self.data_initial, **user_input}
            return self.async_create_entry(title=data[CONF_HOST], data=data)

        return self.async_show_form(
            step_id="custom",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SUPPORT_VPN,
                        default=self.data_initial.get(CONF_SUPPORT_VPN, True),
                    ): cv.boolean,
                    vol.Required(
                        CONF_SUPPORT_TRACKER,
                        default=self.data_initial.get(CONF_SUPPORT_TRACKER, True),
                    ): cv.boolean,
                },
                extra=vol.ALLOW_EXTRA,
            ),
        )

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
                    username=user_input[CONF_USERNAME],
                    logger=_LOGGER,
                    verify_ssl=user_input[CONF_VERIFY_SSL],
                )
                await self.hass.async_add_executor_job(
                    TPLinkRouterCoordinator.request, router, router.get_status
                )
                user_input[CONF_CLIENT_CLASS] = router.__class__.__name__
                self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
                return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)
            except AbortFlow:
                raise
            except Exception as error:
                _LOGGER.error("TplinkRouter Integration Exception - %s", error)
                errors["base"] = str(error)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=data.get(CONF_HOST)): cv.string,
                vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, DEFAULT_USER)): cv.string,
                vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD)): cv.string,
                vol.Required(CONF_SCAN_INTERVAL, default=data.get(CONF_SCAN_INTERVAL)): int,
                vol.Optional(
                    CONF_SCAN_RETRIES,
                    default=data.get(CONF_SCAN_RETRIES, DEFAULT_SCAN_RETRIES),
                ): SCAN_RETRIES_SCHEMA,
                vol.Optional(
                    CONF_SCAN_BACKOFF,
                    default=data.get(CONF_SCAN_BACKOFF, DEFAULT_SCAN_BACKOFF),
                ): SCAN_BACKOFF_SCHEMA,
                vol.Optional(
                    CONF_SCAN_PAUSE,
                    default=data.get(CONF_SCAN_PAUSE, DEFAULT_SCAN_PAUSE),
                ): SCAN_PAUSE_SCHEMA,
                vol.Optional(
                    CONF_OFFLINE_TIMEOUT,
                    default=data.get(CONF_OFFLINE_TIMEOUT, DEFAULT_OFFLINE_TIMEOUT),
                ): OFFLINE_TIMEOUT_SCHEMA,
                vol.Required(CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL)): cv.boolean,
                vol.Required(CONF_SUPPORT_VPN, default=data.get(CONF_SUPPORT_VPN, True)): cv.boolean,
                vol.Required(CONF_SUPPORT_TRACKER, default=data.get(CONF_SUPPORT_TRACKER, True)): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA
        )

        return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)
