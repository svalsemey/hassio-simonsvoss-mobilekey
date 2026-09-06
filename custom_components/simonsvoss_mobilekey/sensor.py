"""Sensor platform for the MobileKey integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import KEY4FRIENDS_LANGUAGES
from .coordinator import (
    SLUG_IDENT_MEDIUM,
    SLUG_KEY4FRIENDS,
    SLUG_LOCK,
    SLUG_SMARTBRIDGE,
    MobileKeyConfigEntry,
)
from .entity import (
    MobileKeyIdentMediumEntity,
    MobileKeyKey4FriendsEntity,
    MobileKeyLockEntity,
    MobileKeySmartBridgeEntity,
    MobileKeySystemEntity,
    async_setup_dynamic_entities,
)
from .models import (
    MobileKeyIdentMedium,
    MobileKeyKey4Friends,
    MobileKeyLock,
    MobileKeyLockingSystem,
    MobileKeySignalQuality,
    MobileKeySmartBridge,
)

# All states come from the coordinator, no per-entity update is performed.
PARALLEL_UPDATES = 0

_SIGNAL_QUALITY_OPTIONS: Final = [
    quality.name.lower()
    for quality in MobileKeySignalQuality
    if quality is not MobileKeySignalQuality.UNKNOWN
]


def _signal_quality_value(quality: MobileKeySignalQuality) -> str | None:
    """Return the enum option for a signal quality, or None when unknown."""
    return None if quality is MobileKeySignalQuality.UNKNOWN else quality.name.lower()


def _door_open_alert_delay(lock: MobileKeyLock) -> int | None:
    """Return the door-open alert threshold in minutes.

    The cloud reports the threshold minus one minute: the lock raises the
    alert once the door stays open for longer than the reported value.
    """
    if lock.door is None or lock.door.open_too_long_timeout is None:
        return None
    return lock.door.open_too_long_timeout + 1


def _last_update(system: MobileKeyLockingSystem) -> datetime | None:
    """Return the data timestamp reported by the cloud, as an aware datetime.

    The cloud reports a naive timestamp expressed in UTC; attaching the
    UTC time zone declares it without shifting the value.
    """
    if system.version is None:
        return None
    return system.version.replace(tzinfo=UTC)


def _as_local_timestamp(value: datetime | None) -> datetime | None:
    """Attach the Home Assistant time zone to a naive local timestamp.

    Key4Friends validity bounds are naive timestamps expressed in local
    time; attaching the configured time zone declares them without
    shifting the value.
    """
    if value is None:
        return None
    return value.replace(tzinfo=dt_util.get_default_time_zone())


def _ident_medium_lock_attributes(
    medium: MobileKeyIdentMedium, system: MobileKeyLockingSystem
) -> dict[str, Any]:
    """Return the locks the ident medium is granted access to.

    Each entry reports both the lock ID and its system name, so entries
    stay unambiguous even when locks share a name.
    """
    return {
        "authorized_locks": [
            {"id": lock.id, "name": lock.name}
            for lock in sorted(
                system.authorized_locks(medium.id), key=lambda lock: lock.id
            )
        ]
    }


def _key4friends_lock_attributes(
    key: MobileKeyKey4Friends, system: MobileKeyLockingSystem
) -> dict[str, Any]:
    """Return the lock authorizations carried by the key.

    Each entry reports the lock ID and system name along with the
    possibly different name shown to the guest. The system name is None
    when the lock is no longer part of the locking system.
    """
    return {
        "authorized_locks": [
            {
                "id": authorization.lock_id,
                "name": (
                    None
                    if (lock := system.locks.get(authorization.lock_id)) is None
                    else lock.name
                ),
                "custom_name": authorization.name,
            }
            for authorization in sorted(
                key.authorizations, key=lambda authorization: authorization.lock_id
            )
        ]
    }


@dataclass(frozen=True, kw_only=True)
class MobileKeyLockSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to a MobileKey lock."""

    value_fn: Callable[[MobileKeyLock], StateType]
    exists_fn: Callable[[MobileKeyLock], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class MobileKeySmartBridgeSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to a MobileKey SmartBridge."""

    value_fn: Callable[[MobileKeySmartBridge], StateType]


@dataclass(frozen=True, kw_only=True)
class MobileKeyIdentMediumSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to a MobileKey ident medium.

    Value and attribute functions also receive the full system state,
    which carries the key/lock authorization matrix.
    """

    value_fn: Callable[[MobileKeyIdentMedium, MobileKeyLockingSystem], StateType]
    attributes_fn: (
        Callable[[MobileKeyIdentMedium, MobileKeyLockingSystem], dict[str, Any]] | None
    ) = None


@dataclass(frozen=True, kw_only=True)
class MobileKeyKey4FriendsSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to a MobileKey Key4Friends key.

    Attribute functions also receive the full system state, which maps
    authorized locks back to their system names.
    """

    value_fn: Callable[[MobileKeyKey4Friends], StateType | datetime]
    attributes_fn: (
        Callable[[MobileKeyKey4Friends, MobileKeyLockingSystem], dict[str, Any]] | None
    ) = None


@dataclass(frozen=True, kw_only=True)
class MobileKeySystemSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to the MobileKey locking system."""

    value_fn: Callable[[MobileKeyLockingSystem], datetime | None]


DESCRIPTIONS_LOCK: tuple[MobileKeyLockSensorDescription, ...] = (
    MobileKeyLockSensorDescription(
        key="signal_quality",
        translation_key="signal_quality",
        device_class=SensorDeviceClass.ENUM,
        options=_SIGNAL_QUALITY_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda lock: (
            None
            if lock.network is None
            else _signal_quality_value(lock.network.quality)
        ),
        exists_fn=lambda lock: lock.network is not None,
    ),
    MobileKeyLockSensorDescription(
        key="id",
        translation_key="lock_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda lock: lock.id,
    ),
    MobileKeyLockSensorDescription(
        key="opening_timeout",
        translation_key="opening_timeout",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda lock: None if lock.core is None else lock.core.timeout,
        exists_fn=lambda lock: lock.core is not None,
    ),
    # Only created when the door-open alert is configured on the lock.
    MobileKeyLockSensorDescription(
        key="door_open_alert_delay",
        translation_key="door_open_alert_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_door_open_alert_delay,
        exists_fn=lambda lock: (
            lock.door is not None and lock.door.open_too_long_timeout is not None
        ),
    ),
)

DESCRIPTIONS_SMARTBRIDGE: tuple[MobileKeySmartBridgeSensorDescription, ...] = (
    MobileKeySmartBridgeSensorDescription(
        key="signal_quality",
        translation_key="signal_quality",
        device_class=SensorDeviceClass.ENUM,
        options=_SIGNAL_QUALITY_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bridge: _signal_quality_value(bridge.quality),
    ),
    MobileKeySmartBridgeSensorDescription(
        key="mobile_key_id",
        translation_key="mobile_key_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bridge: bridge.mobile_key_id,
    ),
)

DESCRIPTIONS_IDENT_MEDIUM: tuple[MobileKeyIdentMediumSensorDescription, ...] = (
    MobileKeyIdentMediumSensorDescription(
        key="id",
        translation_key="ident_medium_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda medium, _: medium.id,
    ),
    MobileKeyIdentMediumSensorDescription(
        key="name",
        translation_key="ident_medium_name",
        value_fn=lambda medium, _: medium.name,
    ),
    MobileKeyIdentMediumSensorDescription(
        key="authorizations",
        translation_key="ident_medium_authorizations",
        value_fn=lambda medium, system: len(system.authorized_locks(medium.id)),
        attributes_fn=_ident_medium_lock_attributes,
    ),
)


DESCRIPTIONS_KEY4FRIENDS: tuple[MobileKeyKey4FriendsSensorDescription, ...] = (
    MobileKeyKey4FriendsSensorDescription(
        key="id",
        translation_key="key4friends_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda key: key.id,
    ),
    MobileKeyKey4FriendsSensorDescription(
        key="name",
        translation_key="key4friends_name",
        value_fn=lambda key: key.name,
    ),
    MobileKeyKey4FriendsSensorDescription(
        key="email",
        translation_key="key4friends_email",
        value_fn=lambda key: key.email,
    ),
    MobileKeyKey4FriendsSensorDescription(
        key="language",
        translation_key="key4friends_language",
        device_class=SensorDeviceClass.ENUM,
        options=list(KEY4FRIENDS_LANGUAGES),
        value_fn=lambda key: (
            key.language if key.language in KEY4FRIENDS_LANGUAGES else None
        ),
    ),
    MobileKeyKey4FriendsSensorDescription(
        key="valid_from",
        translation_key="key4friends_valid_from",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda key: _as_local_timestamp(key.valid_from),
    ),
    MobileKeyKey4FriendsSensorDescription(
        key="valid_to",
        translation_key="key4friends_valid_to",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda key: _as_local_timestamp(key.valid_to),
    ),
    MobileKeyKey4FriendsSensorDescription(
        key="authorizations",
        translation_key="key4friends_authorizations",
        value_fn=lambda key: len(key.authorizations),
        attributes_fn=_key4friends_lock_attributes,
    ),
)


DESCRIPTIONS_SYSTEM: tuple[MobileKeySystemSensorDescription, ...] = (
    MobileKeySystemSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_update,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MobileKey sensors from a config entry."""
    # The system device is unique and permanent: no dynamic tracking.
    async_add_entities(
        MobileKeySystemSensor(entry.runtime_data, description)
        for description in DESCRIPTIONS_SYSTEM
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SLUG_SMARTBRIDGE,
        lambda system: system.smart_bridges,
        lambda coordinator, bridge: (
            MobileKeySmartBridgeSensor(coordinator, description, bridge)
            for description in DESCRIPTIONS_SMARTBRIDGE
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SLUG_LOCK,
        lambda system: system.locks,
        lambda coordinator, lock: (
            MobileKeyLockSensor(coordinator, description, lock)
            for description in DESCRIPTIONS_LOCK
            if description.exists_fn(lock)
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SLUG_IDENT_MEDIUM,
        lambda system: system.ident_media,
        lambda coordinator, medium: (
            MobileKeyIdentMediumSensor(coordinator, description, medium)
            for description in DESCRIPTIONS_IDENT_MEDIUM
        ),
    )

    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SLUG_KEY4FRIENDS,
        lambda system: system.key4friends,
        lambda coordinator, key: (
            MobileKeyKey4FriendsSensor(coordinator, description, key)
            for description in DESCRIPTIONS_KEY4FRIENDS
        ),
    )


class MobileKeyLockSensor(MobileKeyLockEntity, SensorEntity):
    """Sensor reporting a state of a MobileKey lock."""

    entity_description: MobileKeyLockSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.lock)


class MobileKeySmartBridgeSensor(MobileKeySmartBridgeEntity, SensorEntity):
    """Sensor reporting a state of a MobileKey SmartBridge."""

    entity_description: MobileKeySmartBridgeSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.smart_bridge)


class MobileKeyIdentMediumSensor(MobileKeyIdentMediumEntity, SensorEntity):
    """Sensor reporting a state of a MobileKey ident medium."""

    entity_description: MobileKeyIdentMediumSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(
            self.ident_medium, self.coordinator.data
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes describing the ident medium."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.ident_medium, self.coordinator.data)


class MobileKeyKey4FriendsSensor(MobileKeyKey4FriendsEntity, SensorEntity):
    """Sensor reporting a state of a MobileKey Key4Friends key."""

    entity_description: MobileKeyKey4FriendsSensorDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.key4friends)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes describing the key."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.key4friends, self.coordinator.data)


class MobileKeySystemSensor(MobileKeySystemEntity, SensorEntity):
    """Sensor reporting a state of the MobileKey locking system."""

    entity_description: MobileKeySystemSensorDescription

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
