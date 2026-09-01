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

from .coordinator import MobileKeyConfigEntry
from .entity import MobileKeyLockEntity, MobileKeySmartBridgeEntity
from .models import MobileKeyLock, MobileKeySignalQuality, MobileKeySmartBridge

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

    value_fn: Callable[[MobileKeyLock], str | None]
    exists_fn: Callable[[MobileKeyLock], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class MobileKeySmartBridgeSensorDescription(SensorEntityDescription):
    """Describes a sensor attached to a MobileKey SmartBridge."""

    value_fn: Callable[[MobileKeySmartBridge], str | None]


LOCK_DESCRIPTIONS: tuple[MobileKeyLockSensorDescription, ...] = (
    MobileKeyLockSensorDescription(
        key="signal_quality",
        translation_key="signal_quality",
        device_class=SensorDeviceClass.ENUM,
        options=_SIGNAL_QUALITY_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
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
        entity_registry_enabled_default=False,
        value_fn=lambda bridge: _signal_quality_value(bridge.quality),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MobileKey sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MobileKeySmartBridgeSensor(coordinator, description, bridge)
            for bridge in coordinator.data.smart_bridges.values()
            for description in SMART_BRIDGE_DESCRIPTIONS
        ]
        + [
            MobileKeyLockSensor(coordinator, description, lock)
            for lock in coordinator.data.locks.values()
            for description in LOCK_DESCRIPTIONS
            if description.exists_fn(lock)
        ]
    )


class MobileKeyLockSensor(MobileKeyLockEntity, SensorEntity):
    """Sensor reporting a state of a MobileKey lock."""

    entity_description: MobileKeyLockSensorDescription

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.lock)


class MobileKeySmartBridgeSensor(MobileKeySmartBridgeEntity, SensorEntity):
    """Sensor reporting a state of a MobileKey SmartBridge."""

    entity_description: MobileKeySmartBridgeSensorDescription

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.smart_bridge)
