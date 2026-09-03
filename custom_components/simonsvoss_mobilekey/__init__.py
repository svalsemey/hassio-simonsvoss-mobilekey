"""The MobileKey integration."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import MobileKeyApiClient
from .coordinator import MobileKeyConfigEntry, MobileKeyCoordinator
from .entity import smart_bridge_device_info, system_device_info

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

    device_registry = dr.async_get(hass)

    @callback
    def _async_register_hub_devices() -> None:
        """Register the installation and SmartBridge devices.

        The installation service device comes first, then root
        SmartBridges, so every via_device reference resolves.
        """
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id, **system_device_info(coordinator)
        )
        for bridge in sorted(
            coordinator.data.smart_bridges.values(),
            key=lambda bridge: bridge.parent_chip_id is not None,
        ):
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **smart_bridge_device_info(coordinator, bridge),
            )

    # Hub devices must exist before lock entities reference them through
    # via_device. Registered ahead of the platform listeners, this
    # listener also runs first on every refresh, covering SmartBridges
    # appearing later and keeping registry names up to date.
    _async_register_hub_devices()
    entry.async_on_unload(coordinator.async_add_listener(_async_register_hub_devices))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MobileKeyConfigEntry) -> bool:
    """Unload a MobileKey config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
