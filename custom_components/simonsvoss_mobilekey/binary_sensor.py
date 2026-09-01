"""Binary sensor platform for the MobileKey integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MobileKeyConfigEntry
from .entity import (
    MobileKeyLockEntity,
    MobileKeySmartBridgeEntity,
    async_setup_dynamic_entities,
)
from .models import (
    MobileKeyDoorStatus,
    MobileKeyLock,
    MobileKeyLockingSystem,
    MobileKeySmartBridge,
)

# All states come from the coordinator, no per-entity update is performed.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MobileKeyLockBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor attached to a MobileKey lock."""

    is_on_fn: Callable[[MobileKeyLock], bool | None]
    exists_fn: Callable[[MobileKeyLock], bool] = lambda _: True
    attributes_fn: (
        Callable[[MobileKeyLock, MobileKeyLockingSystem], dict[str, Any]] | None
    ) = None


@dataclass(frozen=True, kw_only=True)
class MobileKeySmartBridgeBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor attached to a MobileKey SmartBridge."""

    is_on_fn: Callable[[MobileKeySmartBridge], bool | None]


def _door_open(lock: MobileKeyLock) -> bool | None:
    """Return whether the door is open, or None when not reported."""
    if lock.door is None or lock.door.door_status is MobileKeyDoorStatus.UNKNOWN:
        return None
    return lock.door.door_status is MobileKeyDoorStatus.OPEN


def _lock_unlocked(lock: MobileKeyLock) -> bool | None:
    """Return whether the bolt is unlocked, or None when not reported."""
    if lock.door is None or lock.door.door_status is MobileKeyDoorStatus.UNKNOWN:
        return None
    return lock.door.door_status is not MobileKeyDoorStatus.CLOSED_LOCKED


def _authorization_attributes(
    lock: MobileKeyLock, system: MobileKeyLockingSystem
) -> dict[str, Any]:
    """Return the names of the keys granted access to the lock."""
    return {
        "authorized_keys": sorted(
            medium.name for medium in system.authorized_media(lock.id)
        )
    }


LOCK_DESCRIPTIONS: tuple[MobileKeyLockBinarySensorDescription, ...] = (
    # The lock entity exists on every lock device: it carries the
    # authorization attributes even when no door monitoring component
    # reports the bolt state.
    MobileKeyLockBinarySensorDescription(
        key="lock",
        device_class=BinarySensorDeviceClass.LOCK,
        is_on_fn=_lock_unlocked,
        attributes_fn=_authorization_attributes,
    ),
    MobileKeyLockBinarySensorDescription(
        key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        is_on_fn=_door_open,
        exists_fn=lambda lock: lock.door is not None,
    ),
    MobileKeyLockBinarySensorDescription(
        key="battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda lock: None if lock.core is None else lock.core.battery_critical,
        exists_fn=lambda lock: lock.core is not None,
    ),
    MobileKeyLockBinarySensorDescription(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda lock: lock.connected,
    ),
)

SMART_BRIDGE_DESCRIPTIONS: tuple[MobileKeySmartBridgeBinarySensorDescription, ...] = (
    MobileKeySmartBridgeBinarySensorDescription(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda bridge: bridge.connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MobileKey binary sensors from a config entry."""
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        lambda system: system.smart_bridges,
        lambda coordinator, bridge: (
            MobileKeySmartBridgeBinarySensor(coordinator, description, bridge)
            for description in SMART_BRIDGE_DESCRIPTIONS
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        lambda system: system.locks,
        lambda coordinator, lock: (
            MobileKeyLockBinarySensor(coordinator, description, lock)
            for description in LOCK_DESCRIPTIONS
            if description.exists_fn(lock)
        ),
    )


class MobileKeyLockBinarySensor(MobileKeyLockEntity, BinarySensorEntity):
    """Binary sensor reporting a state of a MobileKey lock."""

    entity_description: MobileKeyLockBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        return self.entity_description.is_on_fn(self.lock)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes describing the lock."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.lock, self.coordinator.data)


class MobileKeySmartBridgeBinarySensor(MobileKeySmartBridgeEntity, BinarySensorEntity):
    """Binary sensor reporting a state of a MobileKey SmartBridge."""

    entity_description: MobileKeySmartBridgeBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        return self.entity_description.is_on_fn(self.smart_bridge)
