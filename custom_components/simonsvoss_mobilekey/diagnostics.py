"""Diagnostics support for the MobileKey integration."""

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .coordinator import (
    SLUG_IDENT_MEDIUM,
    SLUG_KEY4FRIENDS,
    SLUG_LOCK,
    SLUG_SMARTBRIDGE,
    SLUG_SYSTEM,
    MobileKeyConfigEntry,
    device_item_id,
    entry_device_identifier,
)

# Account credentials, Key4Friends guest e-mail addresses and any PIN
# code carried by keypad devices are personal data and never belong in a
# diagnostics dump, be it in the modeled state or in the raw payloads.
TO_REDACT: Final = {CONF_PASSWORD, CONF_USERNAME, "email", "pin", "pinCode", "pins"}


def _raw_item(raw_items: Any, item_id: int) -> Any:
    """Return the raw API object carrying the given cloud ID, if any."""
    if not isinstance(raw_items, list):
        return None
    return next(
        (
            item
            for item in raw_items
            if isinstance(item, Mapping) and item.get("id") == item_id
        ),
        None,
    )


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MobileKeyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The modeled snapshot covers the whole locking system: locks and
    their components, SmartBridges, ident media, the authorization
    matrix and the Key4Friends keys. The raw payloads of the most recent
    cloud responses are included verbatim, redacted, so unsupported
    device types can be reported and modeled.
    """
    coordinator = entry.runtime_data
    client = coordinator.client
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "last_api_call_successful": client.last_call_successful,
        "system": async_redact_data(asdict(coordinator.data), TO_REDACT),
        "raw": async_redact_data(
            {
                "locking_system": client.raw_locking_system,
                "key4friends": client.raw_key4friends,
            },
            TO_REDACT,
        ),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: MobileKeyConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device.

    The service device standing for the installation reports the full
    config entry diagnostics; every other device reports its modeled
    state along with the raw API object it was built from.
    """
    if entry_device_identifier(entry, SLUG_SYSTEM) in device.identifiers:
        return await async_get_config_entry_diagnostics(hass, entry)
    coordinator = entry.runtime_data
    client = coordinator.client
    data = coordinator.data
    raw_system = (
        client.raw_locking_system
        if isinstance(client.raw_locking_system, Mapping)
        else {}
    )
    raw_keys = (
        client.raw_key4friends.get("keys")
        if isinstance(client.raw_key4friends, Mapping)
        else None
    )
    for kind, slug, items, raw_items in (
        ("lock", SLUG_LOCK, data.locks, raw_system.get("locks")),
        (
            "smartbridge",
            SLUG_SMARTBRIDGE,
            data.smart_bridges,
            raw_system.get("smartBridges"),
        ),
        (
            "ident_medium",
            SLUG_IDENT_MEDIUM,
            data.ident_media,
            raw_system.get("identMedia"),
        ),
        ("key4friends", SLUG_KEY4FRIENDS, data.key4friends, raw_keys),
    ):
        if (item_id := device_item_id(entry, slug, device.identifiers)) is None:
            continue
        item = items.get(item_id)
        return {
            "type": kind,
            "item": (
                None if item is None else async_redact_data(asdict(item), TO_REDACT)
            ),
            "raw": async_redact_data(_raw_item(raw_items, item_id), TO_REDACT),
        }
    return {"type": None, "item": None, "raw": None}
