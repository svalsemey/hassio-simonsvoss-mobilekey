"""Diagnostics support for the MobileKey integration."""

from collections.abc import Container, Mapping
from dataclasses import asdict
from typing import Any, Final

from homeassistant.components.diagnostics import REDACTED
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
TO_REDACT: Final = frozenset(
    {CONF_PASSWORD, CONF_USERNAME, "email", "pin", "pinCode", "pins"}
)

# Key4Friends keys and ident media are named after people, the invited
# guest and the holder of the medium, so their entries are redacted with
# every name field they carry, at whichever nesting level the cloud
# reports it, together with the free-text notes a Key4Friends lock
# authorization displays to the guest. Names are not redacted globally:
# lock and SmartBridge names describe the installation and are needed
# for troubleshooting.
TO_REDACT_PERSONAL: Final = TO_REDACT | {"name", "notes"}

# Hardware identifiers, in their modeled and raw spellings: the serial
# number of SmartBridges, the radio chip IDs through which locks and
# repeater SmartBridges reference their parent gateway, and the physical
# hardware identifier (PHI) of locks and ident media. Unique to an
# installation, they are pseudonymized rather than erased, so device
# relationships remain visible in the dump.
TO_PSEUDONYMIZE: Final = frozenset(
    {
        "chip_id",
        "chipID",
        "mobile_key_id",
        "mobileKeyID",
        "parent_chip_id",
        "parentChipID",
        "phi",
    }
)

# Placeholder of a pseudonymized identifier, numbered in order of first
# appearance within a dump.
_PSEUDONYM: Final = "**REDACTED-{}**"


class _Redactor:
    """Redaction of one diagnostics dump.

    Redacted fields are erased. Pseudonymized fields are replaced by a
    placeholder assigned to their value on first appearance and reused
    for every later occurrence, so equal identifiers stay equal across
    the dump and a lock can still be matched to its parent SmartBridge.
    Placeholders are not comparable between dumps.
    """

    def __init__(self) -> None:
        """Initialize the redactor with an empty pseudonym table."""
        self._pseudonyms: dict[str, str] = {}

    def _pseudonymize(self, value: str) -> str:
        """Return the placeholder standing for an identifier value."""
        return self._pseudonyms.setdefault(
            value, _PSEUDONYM.format(len(self._pseudonyms) + 1)
        )

    def _redact_field(self, key: Any, value: Any, to_redact: Container[str]) -> Any:
        """Redact one field of a mapping according to its key.

        Absent and empty values are kept as such, so the shape of the
        payload stays visible. An identifier holding anything but a
        string is erased.
        """
        if value is None or value == "":
            return value
        if key in to_redact:
            return REDACTED
        if key in TO_PSEUDONYMIZE:
            return self._pseudonymize(value) if isinstance(value, str) else REDACTED
        return self.redact(value, to_redact)

    def redact(
        self,
        data: Any,
        to_redact: Container[str] = TO_REDACT,
        personal_collections: Container[str] = (),
    ) -> Any:
        """Redact a payload recursively.

        Mappings, lists and tuples are traversed; any other value is
        returned unchanged. The top-level collections named in
        ``personal_collections`` hold entries named after people and are
        redacted with the personal field set instead of ``to_redact``.
        """
        if isinstance(data, (list, tuple)):
            return [self.redact(item, to_redact) for item in data]
        if not isinstance(data, Mapping):
            return data
        return {
            key: self._redact_field(
                key,
                value,
                TO_REDACT_PERSONAL if key in personal_collections else to_redact,
            )
            for key, value in data.items()
        }


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
    device types can be reported and modeled. One redactor serves the
    whole dump, so an identifier gets the same placeholder in the
    snapshot and in the raw payloads.
    """
    coordinator = entry.runtime_data
    client = coordinator.client
    redactor = _Redactor()
    return {
        "entry": {
            "data": redactor.redact(entry.data),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "last_api_call_successful": client.last_call_successful,
        "system": redactor.redact(
            asdict(coordinator.data),
            personal_collections=("ident_media", "key4friends"),
        ),
        "raw": {
            "locking_system": redactor.redact(
                client.raw_locking_system, personal_collections=("identMedia",)
            ),
            "key4friends": redactor.redact(
                client.raw_key4friends, personal_collections=("keys",)
            ),
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: MobileKeyConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device.

    The service device standing for the installation reports the full
    config entry diagnostics; every other device reports its modeled
    state along with the raw API object it was built from, both redacted
    with the field set matching the kind of the device and sharing one
    pseudonym table.
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
    # Kind label, identifier slug, modeled items, raw items and erased
    # fields of every device kind exposing diagnostics.
    device_kinds: tuple[
        tuple[str, str, Mapping[int, Any], Any, Container[str]], ...
    ] = (
        ("lock", SLUG_LOCK, data.locks, raw_system.get("locks"), TO_REDACT),
        (
            "smartbridge",
            SLUG_SMARTBRIDGE,
            data.smart_bridges,
            raw_system.get("smartBridges"),
            TO_REDACT,
        ),
        (
            "ident_medium",
            SLUG_IDENT_MEDIUM,
            data.ident_media,
            raw_system.get("identMedia"),
            TO_REDACT_PERSONAL,
        ),
        (
            "key4friends",
            SLUG_KEY4FRIENDS,
            data.key4friends,
            raw_keys,
            TO_REDACT_PERSONAL,
        ),
    )
    redactor = _Redactor()
    for kind, slug, items, raw_items, to_redact in device_kinds:
        if (item_id := device_item_id(entry, slug, device.identifiers)) is None:
            continue
        item = items.get(item_id)
        return {
            "type": kind,
            "item": None if item is None else redactor.redact(asdict(item), to_redact),
            "raw": redactor.redact(_raw_item(raw_items, item_id), to_redact),
        }
    return {"type": None, "item": None, "raw": None}
