"""The MobileKey integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    MobileKeyApiClient,
    MobileKeyAuthenticationError,
    MobileKeyConnectionError,
)
from .const import DOMAIN

PLATFORMS: list[Platform] = []

type MobileKeyConfigEntry = ConfigEntry[MobileKeyApiClient]


async def async_setup_entry(hass: HomeAssistant, entry: MobileKeyConfigEntry) -> bool:
    """Set up MobileKey from a config entry."""
    # A dedicated session gives this entry its own cookie jar for the
    # mk-auth and Cloudflare cookies; it is closed automatically on unload.
    client = MobileKeyApiClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        async_create_clientsession(hass),
    )

    try:
        await client.async_authenticate()
    except MobileKeyAuthenticationError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"username": entry.data[CONF_USERNAME]},
        ) from err
    except MobileKeyConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MobileKeyConfigEntry) -> bool:
    """Unload a MobileKey config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
