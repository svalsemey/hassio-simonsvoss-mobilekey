"""Config flow for the MobileKey integration."""

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    MobileKeyApiClient,
    MobileKeyAuthenticationError,
    MobileKeyConnectionError,
)
from .const import SCANINTERVAL_DEFAULT, DOMAIN, SCANINTERVAL_MAX, SCANINTERVAL_MIN

_LOGGER = logging.getLogger(__name__)

# Polling interval field, shared by the user step and the options flow.
_SCAN_INTERVAL_SELECTOR = vol.All(
    NumberSelector(
        NumberSelectorConfig(
            min=SCANINTERVAL_MIN,
            max=SCANINTERVAL_MAX,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=UnitOfTime.SECONDS,
        )
    ),
    vol.Coerce(int),
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(
            CONF_SCAN_INTERVAL, default=SCANINTERVAL_DEFAULT
        ): _SCAN_INTERVAL_SELECTOR,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL, default=SCANINTERVAL_DEFAULT
        ): _SCAN_INTERVAL_SELECTOR,
    }
)


class MobileKeyOptionsFlow(OptionsFlow):
    """Handle the options flow for MobileKey."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the MobileKey options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )


class MobileKeyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for MobileKey."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MobileKeyOptionsFlow:
        """Create the options flow."""
        return MobileKeyOptionsFlow()

    async def _async_validate_credentials(
        self, username: str, password: str
    ) -> tuple[dict[str, str], str]:
        """Check the credentials against the cloud.

        Return the form errors and the locking system name, which doubles
        as proof that the account data is reachable.
        """
        # A throwaway session keeps validation cookies out of any shared jar.
        session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            system = await MobileKeyApiClient(
                username, password, session
            ).async_get_locking_system()
        except MobileKeyAuthenticationError:
            return {"base": "invalid_auth"}, ""
        except MobileKeyConnectionError:
            return {"base": "cannot_connect"}, ""
        except Exception:
            _LOGGER.exception("Unexpected error while validating credentials")
            return {"base": "unknown"}, ""
        finally:
            # Sessions from the helper share the Home Assistant connector and
            # replace close() with a safeguard; detaching is the supported way
            # to release the session while leaving the connector running.
            session.detach()
        return {}, system.name

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial account configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            errors, system_name = await self._async_validate_credentials(
                username, user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_create_entry(
                    title=system_name or username,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]},
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the re-authentication flow after an authentication failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the new password and update the config entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            errors, _ = await self._async_validate_credentials(
                reauth_entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )
