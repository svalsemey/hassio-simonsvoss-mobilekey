"""Coordinator fetching the locking system state from the MobileKey cloud."""

from datetime import timedelta
import logging
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    MobileKeyApiClient,
    MobileKeyAuthenticationError,
    MobileKeyConnectionError,
)
from .const import DOMAIN
from .models import MobileKeyLockingSystem

_LOGGER = logging.getLogger(__name__)

# Polling period of the cloud service, kept conservative to stay close to
# the request rate of the mobile application.
_UPDATE_INTERVAL: Final = timedelta(seconds=60)

type MobileKeyConfigEntry = ConfigEntry[MobileKeyCoordinator]


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
            update_interval=_UPDATE_INTERVAL,
        )
        self.client = client

    @property
    def unique_base(self) -> str:
        """Return the stable prefix shared by device and entity unique IDs.

        The config flow always assigns the account username as the unique
        ID of the entry; the entry ID fallback only satisfies typing.
        """
        return self.config_entry.unique_id or self.config_entry.entry_id

    async def _async_update_data(self) -> MobileKeyLockingSystem:
        """Fetch the current locking system state from the cloud."""
        try:
            return await self.client.async_get_locking_system()
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
