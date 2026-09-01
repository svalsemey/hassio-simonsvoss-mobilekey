"""Sensor platform for the MobileKey integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import MobileKeyConfigEntry
from .entity import (
    MobileKeyIdentMediumEntity,
    MobileKeyLockEntity,
    MobileKeySmartBridgeEntity,
    async_setup_dynamic_entities,
)
from .models import (
    MobileKeyIdentMedium,
    MobileKeyLock,
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MobileKey sensors from a config entry."""
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        lambda system: system.smart_bridges,
        lambda coordinator, bridge: (
            MobileKeySmartBridgeSensor(coordinator, description, bridge)
            for description in SMART_BRIDGE_DESCRIPTIONS
        ),
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
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
