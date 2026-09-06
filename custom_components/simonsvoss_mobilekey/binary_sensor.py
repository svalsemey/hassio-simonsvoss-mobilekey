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
from homeassistant.util import dt as dt_util

from .coordinator import (
    SLUG_KEY4FRIENDS,
    SLUG_LOCK,
    SLUG_SMARTBRIDGE,
    MobileKeyConfigEntry,
)
from .entity import (
    MobileKeyKey4FriendsEntity,
    MobileKeyLockEntity,
    MobileKeySmartBridgeEntity,
    async_setup_dynamic_entities,
)
from .models import (
    MobileKeyDoorStatus,
    MobileKeyKey4Friends,
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


@dataclass(frozen=True, kw_only=True)
class MobileKeyKey4FriendsBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor attached to a MobileKey Key4Friends key."""

    is_on_fn: Callable[[MobileKeyKey4Friends], bool | None]


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


def _key4friends_expired(key: MobileKeyKey4Friends) -> bool | None:
    """Return whether the validity window of the key has ended.

    Validity bounds are naive timestamps expressed in the Home Assistant
    time zone, so the comparison uses the local wall-clock time. The
    cloud keeps expired keys listed until their owner deletes them.
    """
    if key.valid_to is None:
        return None
    return dt_util.now().replace(tzinfo=None) > key.valid_to


DESCRIPTIONS_LOCK: tuple[MobileKeyLockBinarySensorDescription, ...] = (
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
        key="permanent_opening",
        translation_key="permanent_opening",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda lock: None if lock.core is None else lock.core.flip_flop,
        exists_fn=lambda lock: lock.core is not None,
    ),
    MobileKeyLockBinarySensorDescription(
        key="pending_task",
        translation_key="pending_task",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda lock: lock.has_pending_task,
    ),
    MobileKeyLockBinarySensorDescription(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda lock: lock.connected,
    ),
)

DESCRIPTIONS_SMARTBRIDGE: tuple[MobileKeySmartBridgeBinarySensorDescription, ...] = (
    MobileKeySmartBridgeBinarySensorDescription(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda bridge: bridge.connected,
    ),
)

DESCRIPTIONS_KEY4FRIENDS: tuple[MobileKeyKey4FriendsBinarySensorDescription, ...] = (
    # Time-based state: reevaluated against the current time on every
    # coordinator refresh, which bounds its staleness to one poll cycle.
    MobileKeyKey4FriendsBinarySensorDescription(
        key="expired",
        translation_key="expired",
        is_on_fn=_key4friends_expired,
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
        SLUG_SMARTBRIDGE,
        lambda system: system.smart_bridges,
        lambda coordinator, bridge: (
            MobileKeySmartBridgeBinarySensor(coordinator, description, bridge)
            for description in DESCRIPTIONS_SMARTBRIDGE
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SLUG_LOCK,
        lambda system: system.locks,
        lambda coordinator, lock: (
            MobileKeyLockBinarySensor(coordinator, description, lock)
            for description in DESCRIPTIONS_LOCK
            if description.exists_fn(lock)
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SLUG_KEY4FRIENDS,
        lambda system: system.key4friends,
        lambda coordinator, key: (
            MobileKeyKey4FriendsBinarySensor(coordinator, description, key)
            for description in DESCRIPTIONS_KEY4FRIENDS
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


class MobileKeyKey4FriendsBinarySensor(MobileKeyKey4FriendsEntity, BinarySensorEntity):
    """Binary sensor reporting a state of a MobileKey Key4Friends key."""

    entity_description: MobileKeyKey4FriendsBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        return self.entity_description.is_on_fn(self.key4friends)
