"""Config flow for the MobileKey integration."""

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    MobileKeyApiClient,
    MobileKeyAuthenticationError,
    MobileKeyConnectionError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class MobileKeyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for MobileKey."""

    VERSION = 1

    async def _async_validate_credentials(
        self, username: str, password: str
    ) -> dict[str, str]:
        """Check the credentials against the cloud and return form errors."""
        # A throwaway session keeps validation cookies out of any shared jar.
        session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            await MobileKeyApiClient(username, password, session).async_authenticate()
        except MobileKeyAuthenticationError:
            return {"base": "invalid_auth"}
        except MobileKeyConnectionError:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while validating credentials")
            return {"base": "unknown"}
        finally:
            # Sessions from the helper share the Home Assistant connector and
            # replace close() with a safeguard; detaching is the supported way
            # to release the session while leaving the connector running.
            session.detach()
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial account configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            errors = await self._async_validate_credentials(
                username, user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
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
            errors = await self._async_validate_credentials(
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
