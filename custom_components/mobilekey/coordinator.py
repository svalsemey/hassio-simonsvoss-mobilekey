"""Data update coordinator for SimonsVoss MobileKey."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MobileKeyApiClient, MobileKeyAuthError, MobileKeyConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MobileKeyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that fetches lock states for a single SmartBridge."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MobileKeyApiClient,
        smartbridge_id: str,
        smartbridge_name: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{smartbridge_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.smartbridge_id = smartbridge_id
        self.smartbridge_name = smartbridge_name

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch lock states from the MobileKey API."""
        try:
            locks = await self.client.get_locks(self.smartbridge_id)
        except MobileKeyAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except MobileKeyConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

        return {lock["id"]: lock for lock in locks}
