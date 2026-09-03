"""The MobileKey integration."""

from functools import partial

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import MobileKeyApiClient
from .coordinator import (
    SYSTEM_SLUG,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
    device_removed_signal,
    entry_device_identifier,
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


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MobileKeyConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow the user to remove a lock, SmartBridge or ident medium device.

    The service device standing for the installation is the only one
    that must survive for the lifetime of the entry. Removing any other
    device is accepted: the dispatcher signal lets entity platforms
    forget the matching item, whose device and entities are recreated at
    the next refresh as long as the cloud still reports it. Only entry
    data is used here, so the check is safe in every entry state.
    """
    if entry_device_identifier(entry, SYSTEM_SLUG) in device_entry.identifiers:
        return False
    async_dispatcher_send(hass, device_removed_signal(entry), device_entry.identifiers)
    return True
