"""Coordinator fetching the locking system state from the MobileKey cloud."""

from datetime import timedelta
import logging
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    MobileKeyApiClient,
    MobileKeyAuthenticationError,
    MobileKeyConnectionError,
)
from .const import SCANINTERVAL_DEFAULT, DOMAIN
from .models import MobileKeyLockingSystem

_LOGGER = logging.getLogger(__name__)

# Device slug templates, shared by device identifiers and entity unique IDs.
LOCK_SLUG: Final = "lock_{}"
SMART_BRIDGE_SLUG: Final = "smartbridge_{}"
IDENT_MEDIUM_SLUG: Final = "identmedium_{}"
# Device slug of the service device representing the whole installation.
SYSTEM_SLUG: Final = "system"

type MobileKeyConfigEntry = ConfigEntry[MobileKeyCoordinator]


def entry_unique_base(entry: MobileKeyConfigEntry) -> str:
    """Return the stable prefix shared by device and entity unique IDs.

    The config flow always assigns the account username as the unique
    ID of the entry; the entry ID fallback only satisfies typing.
    """
    return entry.unique_id or entry.entry_id


def entry_device_identifier(entry: MobileKeyConfigEntry, slug: str) -> tuple[str, str]:
    """Return the registry identifier of the device with the given slug."""
    return (DOMAIN, f"{entry_unique_base(entry)}_{slug}")


def device_removed_signal(entry: MobileKeyConfigEntry) -> str:
    """Return the dispatcher signal sent when the user removes a device."""
    return f"{DOMAIN}_{entry.entry_id}_device_removed"


def _configured_update_interval(entry: MobileKeyConfigEntry) -> timedelta:
    """Return the polling interval configured in the entry options."""
    return timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, SCANINTERVAL_DEFAULT)
    )


class MobileKeyCoordinator(DataUpdateCoordinator[MobileKeyLockingSystem]):
    """Poll the full locking system state for one MobileKey account."""

    config_entry: MobileKeyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MobileKeyConfigEntry,
        client: MobileKeyApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=_configured_update_interval(config_entry),
        )
        self.client = client

    @property
    def unique_base(self) -> str:
        """Return the stable prefix shared by device and entity unique IDs."""
        return entry_unique_base(self.config_entry)

    def device_identifier(self, slug: str) -> tuple[str, str]:
        """Return the registry identifier of the device with the given slug."""
        return entry_device_identifier(self.config_entry, slug)

    @callback
    def apply_options(self) -> None:
        """Apply the entry options to the coordinator.

        A new polling interval takes effect once the currently scheduled
        refresh has fired.
        """
        self.update_interval = _configured_update_interval(self.config_entry)

    async def _async_update_data(self) -> MobileKeyLockingSystem:
        """Fetch the current locking system state from the cloud."""
        try:
            system = await self.client.async_get_locking_system()
        except MobileKeyAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={
                    "username": self.config_entry.data[CONF_USERNAME]
                },
            ) from err
        except MobileKeyConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
            ) from err
        self._async_prune_stale_devices(system)
        return system

    @callback
    def _async_prune_stale_devices(self, system: MobileKeyLockingSystem) -> None:
        """Remove registry devices no longer reported by the locking system.

        The cloud always returns the full installation, so any registered
        device missing from the payload has been deleted; removing it also
        cascades the removal of its entities. The service device standing
        for the installation itself is always kept.
        """
        identifiers = {
            self.device_identifier(SYSTEM_SLUG),
            *(
                self.device_identifier(slug.format(item_id))
                for slug, item_ids in (
                    (LOCK_SLUG, system.locks),
                    (SMART_BRIDGE_SLUG, system.smart_bridges),
                    (IDENT_MEDIUM_SLUG, system.ident_media),
                )
                for item_id in item_ids
            ),
        }
        device_registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, self.config_entry.entry_id
        ):
            if device.identifiers.isdisjoint(identifiers):
                device_registry.async_remove_device(device.id)
