"""Device registry management for the MobileKey integration."""

from typing import Final

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .coordinator import (
    IDENT_MEDIUM_SLUG,
    LOCK_SLUG,
    SMART_BRIDGE_SLUG,
    SYSTEM_SLUG,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
)
from .models import MobileKeyIdentMedium, MobileKeyLock, MobileKeySmartBridge

MANUFACTURER: Final = "SimonsVoss"


def system_device_info(coordinator: MobileKeyCoordinator) -> DeviceInfo:
    """Build the device registry description of the locking system.

    The installation is materialized as a service device carrying
    system-wide entities and anchoring the device hierarchy.
    """
    return DeviceInfo(
        identifiers={coordinator.device_identifier(SYSTEM_SLUG)},
        entry_type=DeviceEntryType.SERVICE,
        manufacturer=MANUFACTURER,
        model="MobileKey locking system",
        name=coordinator.data.name,
    )


def smart_bridge_device_info(
    coordinator: MobileKeyCoordinator, bridge: MobileKeySmartBridge
) -> DeviceInfo:
    """Build the device registry description of a SmartBridge.

    Parent links are managed separately, through registry device IDs.
    """
    return DeviceInfo(
        identifiers={
            coordinator.device_identifier(SMART_BRIDGE_SLUG.format(bridge.id))
        },
        manufacturer=MANUFACTURER,
        model="SmartBridge",
        name=bridge.name,
        serial_number=bridge.chip_id,
    )


def lock_device_info(
    coordinator: MobileKeyCoordinator, lock: MobileKeyLock
) -> DeviceInfo:
    """Build the device registry description of a lock.

    The catalog order code is the model of every MobileKey device; the
    model ID is explicitly cleared so the registry never carries a value
    duplicating it. Parent links are managed separately, through
    registry device IDs.
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


@callback
def async_register_devices(entry: MobileKeyConfigEntry) -> None:
    """Create or update every registry device of the locking system.

    Runs at setup and on every coordinator refresh, so descriptive
    fields follow the cloud report and user-removed devices still
    reported by the cloud are recreated. Devices are created without
    parent links first, then linked through their registry IDs, so
    chains of SmartBridge repeaters resolve regardless of the order
    they are reported in. The registry ignores no-op updates.
    """
    coordinator = entry.runtime_data
    system = coordinator.data
    registry = dr.async_get(coordinator.hass)

    def _register(info: DeviceInfo) -> str:
        """Create or update a device and return its registry ID."""
        return registry.async_get_or_create(config_entry_id=entry.entry_id, **info).id

    system_device_id = _register(system_device_info(coordinator))
    bridge_device_ids = {
        bridge.id: _register(smart_bridge_device_info(coordinator, bridge))
        for bridge in system.smart_bridges.values()
    }
    for medium in system.ident_media.values():
        _register(ident_medium_device_info(coordinator, medium))
    # A repeater SmartBridge reports the chip ID of its parent gateway;
    # root SmartBridges chain to the installation service device.
    for bridge in system.smart_bridges.values():
        parent = system.smart_bridge_by_chip_id(bridge.parent_chip_id)
        registry.async_update_device(
            bridge_device_ids[bridge.id],
            via_device_id=(
                system_device_id if parent is None else bridge_device_ids[parent.id]
            ),
        )
    for lock in system.locks.values():
        parent = (
            None
            if lock.network is None
            else system.smart_bridge_by_chip_id(lock.network.parent_chip_id)
        )
        registry.async_update_device(
            _register(lock_device_info(coordinator, lock)),
            via_device_id=None if parent is None else bridge_device_ids[parent.id],
        )
