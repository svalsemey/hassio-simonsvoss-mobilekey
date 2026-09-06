"""The MobileKey integration."""

from functools import partial

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .api import MobileKeyApiClient
from .const import DOMAIN
from .coordinator import (
    SLUG_KEY4FRIENDS,
    SLUG_SYSTEM,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
    device_item_id,
    device_removed_signal,
    entry_device_identifier,
    entry_user_agent,
)
from .devices import async_register_devices
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the MobileKey integration.

    Service actions are registered here, once per Home Assistant run, so
    they can be listed and validated even while no config entry is loaded.
    """
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MobileKeyConfigEntry) -> bool:
    """Set up MobileKey from a config entry."""
    # A dedicated session gives this entry its own cookie jar for the
    # mk-auth and Cloudflare cookies; it is closed automatically when the
    # entry is unloaded.
    coordinator = MobileKeyCoordinator(
        hass,
        entry,
        MobileKeyApiClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            async_create_clientsession(hass),
            user_agent=entry_user_agent(entry),
        ),
    )
    # The first refresh authenticates against the cloud and loads the
    # initial state, converting failures into a setup retry or a
    # reauthentication flow.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Devices must exist before entities reference them by identifier.
    # Registered ahead of the platform listeners, the listener also runs
    # first on every refresh, keeping registry data up to date and
    # recreating user-removed devices still reported by the cloud.
    async_register_devices(entry)
    entry.async_on_unload(
        coordinator.async_add_listener(partial(async_register_devices, entry))
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: MobileKeyConfigEntry
) -> None:
    """Apply updated entry options to the running coordinator."""
    entry.runtime_data.apply_options()


async def async_unload_entry(hass: HomeAssistant, entry: MobileKeyConfigEntry) -> bool:
    """Unload a MobileKey config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_delete_key4friends(entry: MobileKeyConfigEntry, key_id: int) -> bool:
    """Delete the Key4Friends key backing a device the user removed.

    The cloud deletion must succeed before the registry device
    disappears, so a failure keeps both sides consistent. A key already
    gone from the coordinator data has no cloud counterpart left, so its
    stale device is simply released.
    """
    if entry.state is not ConfigEntryState.LOADED:
        return False
    coordinator = entry.runtime_data
    if (key := coordinator.data.key4friends.get(key_id)) is None:
        return True
    await coordinator.async_delete_key4friends(key)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MobileKeyConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow the user to remove a lock, SmartBridge, ident medium or key device.

    The service device standing for the installation is the only one
    that must survive for the lifetime of the entry. Removing a
    Key4Friends device deletes the key from the cloud, which is one way
    to revoke a guest. Removing any other device is accepted: the
    dispatcher signal lets entity platforms forget the matching item,
    whose device and entities are recreated at the next refresh as long
    as the cloud still reports it.
    """
    if entry_device_identifier(entry, SLUG_SYSTEM) in device_entry.identifiers:
        return False
    if (
        key_id := device_item_id(entry, SLUG_KEY4FRIENDS, device_entry.identifiers)
    ) is not None:
        return await _async_delete_key4friends(entry, key_id)
    async_dispatcher_send(hass, device_removed_signal(entry), device_entry.identifiers)
    return True
