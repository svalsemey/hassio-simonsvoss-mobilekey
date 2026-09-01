"""Base entity classes and device descriptions for the MobileKey integration."""

from typing import Final

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MobileKeyCoordinator
from .models import MobileKeyLock, MobileKeySmartBridge

MANUFACTURER: Final = "SimonsVoss"

# Device slug templates, shared by device identifiers and entity unique IDs.
_LOCK_SLUG: Final = "lock_{}"
_SMART_BRIDGE_SLUG: Final = "smartbridge_{}"


def _device_identifier(coordinator: MobileKeyCoordinator, slug: str) -> tuple[str, str]:
    """Return the registry identifier of the device with the given slug."""
    return (DOMAIN, f"{coordinator.unique_base}_{slug}")


def smart_bridge_device_info(
    coordinator: MobileKeyCoordinator, bridge: MobileKeySmartBridge
) -> DeviceInfo:
    """Build the device registry description of a SmartBridge."""
    info = DeviceInfo(
        identifiers={
            _device_identifier(coordinator, _SMART_BRIDGE_SLUG.format(bridge.id))
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
        info["via_device"] = _device_identifier(
            coordinator, _SMART_BRIDGE_SLUG.format(parent.id)
        )
    return info


def lock_device_info(
    coordinator: MobileKeyCoordinator, lock: MobileKeyLock
) -> DeviceInfo:
    """Build the device registry description of a lock."""
    info = DeviceInfo(
        identifiers={_device_identifier(coordinator, _LOCK_SLUG.format(lock.id))},
        manufacturer=MANUFACTURER,
        name=lock.name,
    )
    if lock.core is not None:
        info["model_id"] = lock.core.order_code
        info["sw_version"] = lock.core.firmware
    if lock.network is not None:
        info["serial_number"] = lock.network.chip_id
        if (
            bridge := coordinator.data.smart_bridge_by_chip_id(
                lock.network.parent_chip_id
            )
        ) is not None:
            info["via_device"] = _device_identifier(
                coordinator, _SMART_BRIDGE_SLUG.format(bridge.id)
            )
    return info


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
            _LOCK_SLUG.format(lock.id),
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
            _SMART_BRIDGE_SLUG.format(bridge.id),
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
