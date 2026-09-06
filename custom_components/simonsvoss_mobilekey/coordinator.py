"""Coordinator fetching the locking system state from the MobileKey cloud."""

from dataclasses import replace
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
from .const import (
    CONF_USER_AGENT,
    DOMAIN,
    SCANINTERVAL_DEFAULT,
    USER_AGENT_DEFAULT,
)
from .models import MobileKeyKey4Friends, MobileKeyLockingSystem

_LOGGER = logging.getLogger(__name__)

# Device slug templates, shared by device identifiers and entity unique IDs.
SLUG_LOCK: Final = "lock_{}"
SLUG_SMARTBRIDGE: Final = "smartbridge_{}"
SLUG_IDENT_MEDIUM: Final = "identmedium_{}"
SLUG_KEY4FRIENDS: Final = "key4friends_{}"
# Device slug of the service device representing the whole installation.
SLUG_SYSTEM: Final = "system"

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


def key4friends_id_from_identifiers(
    entry: MobileKeyConfigEntry, identifiers: set[tuple[str, str]]
) -> int | None:
    """Return the Key4Friends key ID encoded in device identifiers, if any."""
    prefix = f"{entry_unique_base(entry)}_{SLUG_KEY4FRIENDS.format('')}"
    return next(
        (
            int(suffix)
            for domain, identifier in identifiers
            if domain == DOMAIN
            and (suffix := identifier.removeprefix(prefix)) != identifier
            and suffix.isdigit()
        ),
        None,
    )


def device_removed_signal(entry: MobileKeyConfigEntry) -> str:
    """Return the dispatcher signal sent when the user removes a device."""
    return f"{DOMAIN}_{entry.entry_id}_device_removed"


def entry_user_agent(entry: MobileKeyConfigEntry) -> str:
    """Return the cloud User-Agent header configured for the entry."""
    return entry.options.get(CONF_USER_AGENT, USER_AGENT_DEFAULT)


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
        # The health listener lets the API health binary sensor react to
        # failed commands immediately instead of waiting for the next poll.
        client.set_health_listener(self.async_update_listeners)

    @property
    def unique_base(self) -> str:
        """Return the stable prefix shared by device and entity unique IDs."""
        return entry_unique_base(self.config_entry)

    def device_identifier(self, slug: str) -> tuple[str, str]:
        """Return the registry identifier of the device with the given slug."""
        return entry_device_identifier(self.config_entry, slug)

    @callback
    def apply_options(self) -> None:
        """Apply the entry options to the coordinator and its API client.

        A new polling interval takes effect once the currently scheduled
        refresh has fired; a new user agent applies from the next request,
        the session being renewed automatically if the cloud rejects it.
        """
        self.update_interval = _configured_update_interval(self.config_entry)
        self.client.user_agent = entry_user_agent(self.config_entry)

    @callback
    def async_upsert_key4friends(self, key: MobileKeyKey4Friends) -> None:
        """Merge a freshly created or edited key into the coordinator data.

        Updating the data immediately materializes the registry device
        and entities of the key without waiting for the next poll.
        """
        self.async_set_updated_data(
            replace(
                self.data,
                key4friends={**self.data.key4friends, key.id: key},
                version=self.client.version or self.data.version,
            )
        )

    @callback
    def async_drop_key4friends(self, key_id: int) -> None:
        """Drop a deleted key from the coordinator data.

        Updating the data immediately releases the entities of the key,
        so its registry device is not resurrected before the next poll.
        """
        self.async_set_updated_data(
            replace(
                self.data,
                key4friends={
                    item_id: item
                    for item_id, item in self.data.key4friends.items()
                    if item_id != key_id
                },
                version=self.client.version or self.data.version,
            )
        )

    async def _async_update_data(self) -> MobileKeyLockingSystem:
        """Fetch the current locking system state from the cloud.

        Key4Friends keys are listed after the locking system state, whose
        version the request echoes and whose locks the returned
        authorizations reference. The reported data version is the most
        recent one seen across both calls.
        """
        try:
            system = await self.client.async_get_locking_system()
            keys = await self.client.async_list_key4friends()
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
                translation_placeholders={"error": str(err)},
            ) from err
        system = replace(
            system,
            key4friends={key.id: key for key in keys},
            version=self.client.version or system.version,
        )
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
            self.device_identifier(SLUG_SYSTEM),
            *(
                self.device_identifier(slug.format(item_id))
                for slug, item_ids in (
                    (SLUG_LOCK, system.locks),
                    (SLUG_SMARTBRIDGE, system.smart_bridges),
                    (SLUG_IDENT_MEDIUM, system.ident_media),
                    (SLUG_KEY4FRIENDS, system.key4friends),
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
