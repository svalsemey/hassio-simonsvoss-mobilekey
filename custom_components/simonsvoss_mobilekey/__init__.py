"""The MobileKey integration."""

from functools import partial

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import MobileKeyApiClient, MobileKeyError
from .const import DOMAIN
from .coordinator import (
    SLUG_SYSTEM,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
    device_removed_signal,
    entry_device_identifier,
    key4friends_id_from_identifiers,
)
from .devices import async_register_devices

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


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

    Removing the device is the one way to delete a key: the cloud
    deletion must succeed before the registry device disappears, so a
    failure keeps both sides consistent. A key already gone from the
    coordinator data has no cloud counterpart left, so its stale device
    is simply released.
    """
    if entry.state is not ConfigEntryState.LOADED:
        return False
    coordinator = entry.runtime_data
    if (key := coordinator.data.key4friends.get(key_id)) is None:
        return True
    try:
        await coordinator.client.async_delete_key4friends(key_id)
    except MobileKeyError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="key4friends_delete_failed",
            translation_placeholders={"name": key.name},
        ) from err
    coordinator.async_drop_key4friends(key_id)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MobileKeyConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow the user to remove a lock, SmartBridge, ident medium or key device.

    The service device standing for the installation is the only one
    that must survive for the lifetime of the entry. Removing a
    Key4Friends device deletes the key from the cloud, which is the
    intended way to revoke a guest. Removing any other device is
    accepted: the dispatcher signal lets entity platforms forget the
    matching item, whose device and entities are recreated at the next
    refresh as long as the cloud still reports it.
    """
    if entry_device_identifier(entry, SLUG_SYSTEM) in device_entry.identifiers:
        return False
    if (
        key_id := key4friends_id_from_identifiers(entry, device_entry.identifiers)
    ) is not None:
        return await _async_delete_key4friends(entry, key_id)
    async_dispatcher_send(hass, device_removed_signal(entry), device_entry.identifiers)
    return True
