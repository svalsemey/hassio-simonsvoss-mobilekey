"""Binary sensor platform for the MobileKey integration."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MobileKeyConfigEntry
from .entity import MobileKeyLockEntity, MobileKeySmartBridgeEntity
from .models import MobileKeyDoorStatus, MobileKeyLock, MobileKeySmartBridge

# All states come from the coordinator, no per-entity update is performed.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MobileKeyLockBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor attached to a MobileKey lock."""

    is_on_fn: Callable[[MobileKeyLock], bool | None]
    exists_fn: Callable[[MobileKeyLock], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class MobileKeySmartBridgeBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor attached to a MobileKey SmartBridge."""

    is_on_fn: Callable[[MobileKeySmartBridge], bool | None]


def _door_open(lock: MobileKeyLock) -> bool | None:
    """Return whether the door is open, or None when not reported."""
    if lock.door is None or lock.door.door_status is MobileKeyDoorStatus.UNKNOWN:
        return None
    return lock.door.door_status is MobileKeyDoorStatus.OPEN


LOCK_DESCRIPTIONS: tuple[MobileKeyLockBinarySensorDescription, ...] = (
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
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MobileKeySmartBridgeBinarySensor(coordinator, description, bridge)
            for bridge in coordinator.data.smart_bridges.values()
            for description in SMART_BRIDGE_DESCRIPTIONS
        ]
        + [
            MobileKeyLockBinarySensor(coordinator, description, lock)
            for lock in coordinator.data.locks.values()
            for description in LOCK_DESCRIPTIONS
            if description.exists_fn(lock)
        ]
    )


class MobileKeyLockBinarySensor(MobileKeyLockEntity, BinarySensorEntity):
    """Binary sensor reporting a state of a MobileKey lock."""

    entity_description: MobileKeyLockBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        return self.entity_description.is_on_fn(self.lock)


class MobileKeySmartBridgeBinarySensor(MobileKeySmartBridgeEntity, BinarySensorEntity):
    """Binary sensor reporting a state of a MobileKey SmartBridge."""

    entity_description: MobileKeySmartBridgeBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        return self.entity_description.is_on_fn(self.smart_bridge)
