"""Base entity classes and device descriptions for the MobileKey integration."""

from collections.abc import Callable, Iterable, Mapping
from typing import Final

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    IDENT_MEDIUM_SLUG,
    LOCK_SLUG,
    SMART_BRIDGE_SLUG,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
)
from .models import (
    MobileKeyIdentMedium,
    MobileKeyLock,
    MobileKeyLockingSystem,
    MobileKeySmartBridge,
)

MANUFACTURER: Final = "SimonsVoss"


@callback
def async_setup_dynamic_entities[ItemT](
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    items_fn: Callable[[MobileKeyLockingSystem], Mapping[int, ItemT]],
    entities_fn: Callable[[MobileKeyCoordinator, ItemT], Iterable[Entity]],
) -> None:
    """Add entities for the current items and for items appearing later.

    The tracked IDs always mirror the latest cloud report, so the entities
    of an item removed and later reintroduced are created anew, its stale
    registry entries having been pruned by the coordinator in between.
    """
    coordinator = entry.runtime_data
    known_ids: set[int] = set()

    @callback
    def _async_sync_entities() -> None:
        items = items_fn(coordinator.data)
        if new_ids := items.keys() - known_ids:
            async_add_entities(
                entity
                for item_id in new_ids
                for entity in entities_fn(coordinator, items[item_id])
            )
        known_ids.clear()
        known_ids.update(items.keys())

    _async_sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync_entities))


def smart_bridge_device_info(
    coordinator: MobileKeyCoordinator, bridge: MobileKeySmartBridge
) -> DeviceInfo:
    """Build the device registry description of a SmartBridge."""
    info = DeviceInfo(
        identifiers={
            coordinator.device_identifier(SMART_BRIDGE_SLUG.format(bridge.id))
        },
        manufacturer=MANUFACTURER,
        model="SmartBridge",
        name=bridge.name,
        serial_number=bridge.chip_id,
    )
    # A repeater SmartBridge reports the chip ID of its parent gateway.
    if (
        parent := coordinator.data.smart_bridge_by_chip_id(bridge.parent_chip_id)
    ) is not None:
        info["via_device"] = coordinator.device_identifier(
            SMART_BRIDGE_SLUG.format(parent.id)
        )
    return info


def lock_device_info(
    coordinator: MobileKeyCoordinator, lock: MobileKeyLock
) -> DeviceInfo:
    """Build the device registry description of a lock.

    The catalog order code is the model of every MobileKey device; the
    model ID is explicitly cleared so the registry never carries a value
    duplicating it.
    """
    info = DeviceInfo(
        identifiers={coordinator.device_identifier(LOCK_SLUG.format(lock.id))},
        manufacturer=MANUFACTURER,
        name=lock.name,
        model_id=None,
    )
    if lock.core is not None:
        info["model"] = lock.core.order_code
        info["sw_version"] = lock.core.firmware
    if lock.network is not None:
        info["serial_number"] = lock.network.chip_id
        if (
            bridge := coordinator.data.smart_bridge_by_chip_id(
                lock.network.parent_chip_id
            )
        ) is not None:
            info["via_device"] = coordinator.device_identifier(
                SMART_BRIDGE_SLUG.format(bridge.id)
            )
    return info


def ident_medium_device_info(
    coordinator: MobileKeyCoordinator, medium: MobileKeyIdentMedium
) -> DeviceInfo:
    """Build the device registry description of an ident medium.

    The catalog order code is the model of every MobileKey device; the
    model ID and firmware fields are explicitly cleared so the registry
    never carries values duplicating or supplementing it.
    """
    return DeviceInfo(
        identifiers={
            coordinator.device_identifier(IDENT_MEDIUM_SLUG.format(medium.id))
        },
        manufacturer=MANUFACTURER,
        name=medium.name,
        model=medium.order_code,
        model_id=None,
        sw_version=None,
        serial_number=medium.phi,
    )


class MobileKeyEntity(CoordinatorEntity[MobileKeyCoordinator]):
    """Base class for all MobileKey entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MobileKeyCoordinator,
        description: EntityDescription,
        device_slug: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the entity and attach it to its device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.unique_base}_{device_slug}_{description.key}"
        )
        self._attr_device_info = device_info


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
        super().__init__(
            coordinator,
            description,
            LOCK_SLUG.format(lock.id),
            lock_device_info(coordinator, lock),
        )

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
        super().__init__(
            coordinator,
            description,
            SMART_BRIDGE_SLUG.format(bridge.id),
            smart_bridge_device_info(coordinator, bridge),
        )

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
        super().__init__(
            coordinator,
            description,
            IDENT_MEDIUM_SLUG.format(medium.id),
            ident_medium_device_info(coordinator, medium),
        )

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
