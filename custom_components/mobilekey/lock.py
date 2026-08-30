"""Lock platform for SimonsVoss MobileKey."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MobileKeyApiClient, MobileKeyConnectionError
from .const import DOMAIN, LOCK_STATE_LOCKED, LOCK_STATE_UNLOCKED
from .coordinator import MobileKeyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MobileKey lock entities from a config entry."""
    coordinators: list[MobileKeyCoordinator] = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[MobileKeyLockEntity] = []
    for coordinator in coordinators:
        for lock_id, lock_data in coordinator.data.items():
            entities.append(
                MobileKeyLockEntity(coordinator, coordinator.client, lock_id, lock_data)
            )

    async_add_entities(entities)


class MobileKeyLockEntity(CoordinatorEntity[MobileKeyCoordinator], LockEntity):
    """Representation of a SimonsVoss MobileKey lock."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MobileKeyCoordinator,
        client: MobileKeyApiClient,
        lock_id: str,
        lock_data: dict[str, Any],
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator)
        self._client = client
        self._lock_id = lock_id
        self._attr_unique_id = f"{coordinator.smartbridge_id}_{lock_id}"
        self._attr_name = lock_data.get("name", lock_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, lock_id)},
            name=lock_data.get("name", lock_id),
            manufacturer="SimonsVoss",
            model="MobileKey Lock",
            via_device=(DOMAIN, coordinator.smartbridge_id),
        )

    @property
    def is_locked(self) -> bool | None:
        """Return true if the lock is locked."""
        lock_data = self.coordinator.data.get(self._lock_id)
        if lock_data is None:
            return None
        state = lock_data.get("state")
        if state == LOCK_STATE_LOCKED:
            return True
        if state == LOCK_STATE_UNLOCKED:
            return False
        return None

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        try:
            await self._client.lock(self.coordinator.smartbridge_id, self._lock_id)
        except MobileKeyConnectionError as err:
            _LOGGER.error("Failed to lock %s: %s", self._attr_name, err)
            return
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        try:
            await self._client.unlock(self.coordinator.smartbridge_id, self._lock_id)
        except MobileKeyConnectionError as err:
            _LOGGER.error("Failed to unlock %s: %s", self._attr_name, err)
            return
        await self.coordinator.async_request_refresh()
