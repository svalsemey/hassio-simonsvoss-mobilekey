"""Diagnostics support for the MobileKey integration."""

from dataclasses import asdict
from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import MobileKeyConfigEntry

# Account credentials and Key4Friends guest e-mail addresses are
# personal data and never belong in a diagnostics dump.
TO_REDACT: Final = {CONF_PASSWORD, CONF_USERNAME, "email"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MobileKeyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The coordinator snapshot covers the whole locking system: locks and
    their components, SmartBridges, ident media, the authorization
    matrix and the Key4Friends keys.
    """
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "last_api_call_successful": coordinator.client.last_call_successful,
        "system": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }
