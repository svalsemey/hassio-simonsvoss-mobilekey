"""The SimonsVoss MobileKey integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MobileKeyApiClient, MobileKeyAuthError, MobileKeyConnectionError
from .const import DOMAIN
from .coordinator import MobileKeyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LOCK]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SimonsVoss MobileKey from a config entry."""
    session = async_get_clientsession(hass)
    client = MobileKeyApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    try:
        await client.authenticate()
        smartbridges = await client.get_smartbridges()
    except MobileKeyAuthError as err:
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except MobileKeyConnectionError as err:
        raise ConfigEntryNotReady(f"Unable to connect to MobileKey API: {err}") from err

    coordinators: list[MobileKeyCoordinator] = []
    for smartbridge in smartbridges:
        coordinator = MobileKeyCoordinator(
            hass=hass,
            client=client,
            smartbridge_id=smartbridge["id"],
            smartbridge_name=smartbridge.get("name", smartbridge["id"]),
        )
        await coordinator.async_config_entry_first_refresh()
        coordinators.append(coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
