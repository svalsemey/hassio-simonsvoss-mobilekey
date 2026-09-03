"""Base entity classes for the MobileKey integration."""

from collections.abc import Callable, Iterable, Mapping

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    IDENT_MEDIUM_SLUG,
    LOCK_SLUG,
    SMART_BRIDGE_SLUG,
    SYSTEM_SLUG,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
    device_removed_signal,
)
from .models import (
    MobileKeyIdentMedium,
    MobileKeyLock,
    MobileKeyLockingSystem,
    MobileKeySmartBridge,
)


@callback
def async_setup_dynamic_entities[ItemT](
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    device_slug: str,
    items_fn: Callable[[MobileKeyLockingSystem], Mapping[int, ItemT]],
    entities_fn: Callable[[MobileKeyCoordinator, ItemT], Iterable[Entity]],
) -> None:
    """Add entities for the current items and for items appearing later.

    The tracked IDs always mirror the latest cloud report, so the entities
    of an item removed and later reintroduced are created anew, its stale
    registry entries having been pruned by the coordinator in between.
    An item whose device is removed on user request is dropped from the
    tracking through the dispatcher signal, so its entities are recreated
    at the next refresh as long as the cloud still reports it.
    """
    coordinator = entry.runtime_data
    known_ids: set[int] = set()

    @callback
    def _async_sync_entities() -> None:
        """Add entities for items not currently tracked."""
        items = items_fn(coordinator.data)
        if new_ids := items.keys() - known_ids:
            async_add_entities(
                entity
                for item_id in new_ids
                for entity in entities_fn(coordinator, items[item_id])
            )
        known_ids.clear()
        known_ids.update(items.keys())

    @callback
    def _async_device_removed(identifiers: set[tuple[str, str]]) -> None:
        """Forget items whose registry device was removed by the user."""
        known_ids.difference_update(
            {
                item_id
                for item_id in known_ids
                if coordinator.device_identifier(device_slug.format(item_id))
                in identifiers
            }
        )

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))
    entry.async_on_unload(
        async_dispatcher_connect(
            coordinator.hass, device_removed_signal(entry), _async_device_removed
        )
    )


class MobileKeyEntity(CoordinatorEntity[MobileKeyCoordinator]):
    """Base class for all MobileKey entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MobileKeyCoordinator,
        description: EntityDescription,
        device_slug: str,
    ) -> None:
        """Initialize the entity and attach it to its registry device.

        Devices are created and maintained centrally from the coordinator
        data, so entities only reference them by identifier.
        """
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.unique_base}_{device_slug}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={coordinator.device_identifier(device_slug)}
        )


class MobileKeyLockEntity(MobileKeyEntity):
    """Base class for entities reporting the state of a lock."""

    def __init__(
        self,
        coordinator: MobileKeyCoordinator,
        description: EntityDescription,
        lock: MobileKeyLock,
    ) -> None:
        """Initialize the entity and attach it to the lock device."""
        self._lock_id = lock.id
        super().__init__(coordinator, description, LOCK_SLUG.format(lock.id))

    @property
    def lock(self) -> MobileKeyLock:
        """Return the current state of the lock backing this entity."""
        return self.coordinator.data.locks[self._lock_id]

    @property
    def available(self) -> bool:
        """Return whether the lock is still reported by the cloud."""
        return super().available and self._lock_id in self.coordinator.data.locks


class MobileKeySmartBridgeEntity(MobileKeyEntity):
    """Base class for entities reporting the state of a SmartBridge."""

    def __init__(
        self,
        coordinator: MobileKeyCoordinator,
        description: EntityDescription,
        bridge: MobileKeySmartBridge,
    ) -> None:
        """Initialize the entity and attach it to the SmartBridge device."""
        self._bridge_id = bridge.id
        super().__init__(coordinator, description, SMART_BRIDGE_SLUG.format(bridge.id))

    @property
    def smart_bridge(self) -> MobileKeySmartBridge:
        """Return the current state of the SmartBridge backing this entity."""
        return self.coordinator.data.smart_bridges[self._bridge_id]

    @property
    def available(self) -> bool:
        """Return whether the SmartBridge is still reported by the cloud."""
        return (
            super().available and self._bridge_id in self.coordinator.data.smart_bridges
        )


class MobileKeyIdentMediumEntity(MobileKeyEntity):
    """Base class for entities reporting the state of an ident medium."""

    def __init__(
        self,
        coordinator: MobileKeyCoordinator,
        description: EntityDescription,
        medium: MobileKeyIdentMedium,
    ) -> None:
        """Initialize the entity and attach it to the ident medium device."""
        self._medium_id = medium.id
        super().__init__(coordinator, description, IDENT_MEDIUM_SLUG.format(medium.id))

    @property
    def ident_medium(self) -> MobileKeyIdentMedium:
        """Return the current state of the ident medium backing this entity."""
        return self.coordinator.data.ident_media[self._medium_id]

    @property
    def available(self) -> bool:
        """Return whether the ident medium is still reported by the cloud."""
        return (
            super().available and self._medium_id in self.coordinator.data.ident_media
        )


class MobileKeySystemEntity(MobileKeyEntity):
    """Base class for entities reporting the state of the locking system."""

    def __init__(
        self, coordinator: MobileKeyCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity and attach it to the system device."""
        super().__init__(coordinator, description, SYSTEM_SLUG)
