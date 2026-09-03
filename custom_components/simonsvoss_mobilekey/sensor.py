"""Sensor platform for the MobileKey integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import (
    IDENT_MEDIUM_SLUG,
    LOCK_SLUG,
    SMART_BRIDGE_SLUG,
    MobileKeyConfigEntry,
)
from .entity import (
    MobileKeyIdentMediumEntity,
    MobileKeyLockEntity,
    MobileKeySmartBridgeEntity,
    MobileKeySystemEntity,
    async_setup_dynamic_entities,
)
from .models import (
    MobileKeyIdentMedium,
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
    """Describes a sensor attached to a MobileKey ident medium."""

    value_fn: Callable[[MobileKeyIdentMedium], StateType]


@dataclass(frozen=True, kw_only=True)
class MobileKeySystemSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to the MobileKey locking system."""

    value_fn: Callable[[MobileKeyLockingSystem], datetime | None]


LOCK_DESCRIPTIONS: tuple[MobileKeyLockSensorDescription, ...] = (
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
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_door_open_alert_delay,
        exists_fn=lambda lock: (
            lock.door is not None and lock.door.open_too_long_timeout is not None
        ),
    ),
)

SMART_BRIDGE_DESCRIPTIONS: tuple[MobileKeySmartBridgeSensorDescription, ...] = (
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

IDENT_MEDIUM_DESCRIPTIONS: tuple[MobileKeyIdentMediumSensorDescription, ...] = (
    MobileKeyIdentMediumSensorDescription(
        key="id",
        translation_key="ident_medium_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda medium: medium.id,
    ),
    MobileKeyIdentMediumSensorDescription(
        key="name",
        translation_key="ident_medium_name",
        value_fn=lambda medium: medium.name,
    ),
)

SYSTEM_DESCRIPTIONS: tuple[MobileKeySystemSensorDescription, ...] = (
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
        for description in SYSTEM_DESCRIPTIONS
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        SMART_BRIDGE_SLUG,
        lambda system: system.smart_bridges,
        lambda coordinator, bridge: (
            MobileKeySmartBridgeSensor(coordinator, description, bridge)
            for description in SMART_BRIDGE_DESCRIPTIONS
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        LOCK_SLUG,
        lambda system: system.locks,
        lambda coordinator, lock: (
            MobileKeyLockSensor(coordinator, description, lock)
            for description in LOCK_DESCRIPTIONS
            if description.exists_fn(lock)
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        IDENT_MEDIUM_SLUG,
        lambda system: system.ident_media,
        lambda coordinator, medium: (
            MobileKeyIdentMediumSensor(coordinator, description, medium)
            for description in IDENT_MEDIUM_DESCRIPTIONS
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
        return self.entity_description.value_fn(self.ident_medium)


class MobileKeySystemSensor(MobileKeySystemEntity, SensorEntity):
    """Sensor reporting a state of the MobileKey locking system."""

    entity_description: MobileKeySystemSensorDescription

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
