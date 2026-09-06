"""Service actions for the MobileKey integration."""

from dataclasses import replace
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID, CONF_EMAIL, CONF_LANGUAGE, CONF_NAME
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import MobileKeyError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_LOCK_NAMES,
    ATTR_LOCKS,
    ATTR_VALID_FROM,
    ATTR_VALID_TO,
    DOMAIN,
    KEY4FRIENDS_LANGUAGES,
    SERVICE_KEY4FRIENDS_CREATE,
    SERVICE_KEY4FRIENDS_DELETE,
    SERVICE_KEY4FRIENDS_GET,
    SERVICE_KEY4FRIENDS_LIST,
    SERVICE_KEY4FRIENDS_UPDATE,
)
from .coordinator import (
    SLUG_KEY4FRIENDS,
    SLUG_LOCK,
    MobileKeyConfigEntry,
    MobileKeyCoordinator,
    device_item_id,
)
from .models import MobileKeyKey4Friends
from .util import (
    as_local_naive,
    as_local_timestamp,
    build_key4friends_authorizations,
    key4friends_expired,
    key4friends_lock_summary,
)

# String fields that must keep printable content once stripped.
_NON_EMPTY_STRING = vol.All(cv.string, str.strip, vol.Length(min=1))

_ENTRY_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})

_DEVICE_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})

_CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(CONF_NAME): _NON_EMPTY_STRING,
        vol.Required(CONF_EMAIL): _NON_EMPTY_STRING,
        vol.Required(CONF_LANGUAGE): vol.In(KEY4FRIENDS_LANGUAGES),
        vol.Required(ATTR_VALID_FROM): cv.datetime,
        vol.Required(ATTR_VALID_TO): cv.datetime,
        vol.Optional(ATTR_LOCKS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_LOCK_NAMES, default=dict): {cv.string: _NON_EMPTY_STRING},
    }
)

# Omitted optional fields leave the corresponding key property unchanged.
_UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(CONF_NAME): _NON_EMPTY_STRING,
        vol.Optional(CONF_LANGUAGE): vol.In(KEY4FRIENDS_LANGUAGES),
        vol.Optional(ATTR_VALID_FROM): cv.datetime,
        vol.Optional(ATTR_VALID_TO): cv.datetime,
        vol.Optional(ATTR_LOCKS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_LOCK_NAMES, default=dict): {cv.string: _NON_EMPTY_STRING},
    }
)


def _device_label(device: dr.DeviceEntry) -> str:
    """Return the user-facing name of a registry device."""
    return device.name_by_user or device.name or device.id


def _get_entry(hass: HomeAssistant, entry_id: str) -> MobileKeyConfigEntry:
    """Return the loaded MobileKey config entry with the given ID.

    Raises ServiceValidationError when the entry does not exist, belongs
    to another integration or is not currently loaded.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_found"
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"title": entry.title},
        )
    return entry


def _get_device(hass: HomeAssistant, device_id: str) -> dr.DeviceEntry:
    """Return the registry device with the given ID."""
    if (device := dr.async_get(hass).async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )
    return device


def _key_context(
    call: ServiceCall,
) -> tuple[MobileKeyConfigEntry, dr.DeviceEntry, MobileKeyKey4Friends]:
    """Resolve the entry, device and key targeted by a device-bound call.

    The registry lookup is scoped to this integration, so devices of
    other integrations resolve as not found. The loaded state of the
    entry is checked here, as only a loaded entry carries runtime data.
    """
    device_id: str = call.data[ATTR_DEVICE_ID]
    device, entry = dr.async_get_device_and_config_entry_for_domain(
        call.hass, device_id, domain=DOMAIN
    )
    if device is None or entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device_id": device_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"title": entry.title},
        )
    key_id = device_item_id(entry, SLUG_KEY4FRIENDS, device.identifiers)
    if key_id is None or (
        key := entry.runtime_data.data.key4friends.get(key_id)
    ) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="key4friends_not_found",
            translation_placeholders={"device": _device_label(device)},
        )
    return entry, device, key


def _lock_id(entry: MobileKeyConfigEntry, device: dr.DeviceEntry) -> int:
    """Return the cloud ID of a lock device belonging to the entry.

    Matching the device identifiers against the entry-specific prefix
    also rejects locks of another MobileKey account.
    """
    lock_id = device_item_id(entry, SLUG_LOCK, device.identifiers)
    if lock_id is None or lock_id not in entry.runtime_data.data.locks:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_lock",
            translation_placeholders={"device": _device_label(device)},
        )
    return lock_id


def _lock_ids(call: ServiceCall, entry: MobileKeyConfigEntry) -> list[int]:
    """Resolve the authorized lock devices of the call, deduplicated."""
    return [
        _lock_id(entry, _get_device(call.hass, device_id))
        for device_id in dict.fromkeys(call.data[ATTR_LOCKS])
    ]


def _custom_lock_names(
    call: ServiceCall, entry: MobileKeyConfigEntry, lock_ids: list[int]
) -> dict[int, str]:
    """Resolve the guest-facing lock names, keyed by cloud lock ID.

    Every referenced device must be among the authorized locks of the
    key being built, so a mistyped device ID never drops a name silently.
    """
    names: dict[int, str] = {}
    for device_id, name in call.data[ATTR_LOCK_NAMES].items():
        device = _get_device(call.hass, device_id)
        if (lock_id := _lock_id(entry, device)) not in lock_ids:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="custom_name_not_authorized",
                translation_placeholders={"device": _device_label(device)},
            )
        names[lock_id] = name
    return names


def _validity_window(
    call: ServiceCall, key: MobileKeyKey4Friends | None
) -> tuple[datetime, datetime]:
    """Return the validity window of the call as naive local datetimes.

    Bounds omitted from the call fall back to those of the edited key.
    """
    valid_from = None if key is None else key.valid_from
    valid_to = None if key is None else key.valid_to
    if (value := call.data.get(ATTR_VALID_FROM)) is not None:
        valid_from = as_local_naive(value)
    if (value := call.data.get(ATTR_VALID_TO)) is not None:
        valid_to = as_local_naive(value)
    if valid_from is None or valid_to is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="incomplete_validity_window"
        )
    if valid_to <= valid_from:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_validity_window"
        )
    return valid_from, valid_to


def _iso_timestamp(value: datetime | None) -> str | None:
    """Serialize a naive local timestamp as an aware ISO 8601 string."""
    return None if (aware := as_local_timestamp(value)) is None else aware.isoformat()


def _key_response(
    hass: HomeAssistant, entry: MobileKeyConfigEntry, key: MobileKeyKey4Friends
) -> dict[str, Any]:
    """Serialize a Key4Friends key for a service response.

    The device ID lets callers chain into the device-bound actions; it
    is None while the registry device does not exist yet.
    """
    coordinator = entry.runtime_data
    device = dr.async_get(hass).async_get_device_by_identifier(
        coordinator.device_identifier(SLUG_KEY4FRIENDS.format(key.id)), entry.entry_id
    )
    return {
        "id": key.id,
        "device_id": None if device is None else device.id,
        "name": key.name,
        "email": key.email,
        "language": key.language,
        "valid_from": _iso_timestamp(key.valid_from),
        "valid_to": _iso_timestamp(key.valid_to),
        "expired": key4friends_expired(key),
        "authorized_locks": key4friends_lock_summary(key, coordinator.data),
    }


async def _async_save_key(
    coordinator: MobileKeyCoordinator, draft: MobileKeyKey4Friends, *, create: bool
) -> MobileKeyKey4Friends:
    """Send the key to the cloud and merge the result into the local data."""
    try:
        if create:
            draft = await coordinator.client.async_create_key4friends(draft)
        else:
            await coordinator.client.async_update_key4friends(draft)
    except MobileKeyError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="key4friends_save_failed",
            translation_placeholders={"name": draft.name},
        ) from err
    coordinator.async_upsert_key4friends(draft)
    return draft


async def _async_list_key4friends(call: ServiceCall) -> ServiceResponse:
    """Return every Key4Friends key of the targeted MobileKey account."""
    entry = _get_entry(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    return {
        "keys": [
            _key_response(call.hass, entry, key)
            for key in sorted(
                entry.runtime_data.data.key4friends.values(), key=lambda key: key.id
            )
        ]
    }


async def _async_get_key4friends(call: ServiceCall) -> ServiceResponse:
    """Return the details of the targeted Key4Friends key."""
    entry, _device, key = _key_context(call)
    return _key_response(call.hass, entry, key)


async def _async_create_key4friends(call: ServiceCall) -> ServiceResponse:
    """Create a Key4Friends key and email the invitation to the guest."""
    entry = _get_entry(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    coordinator = entry.runtime_data
    valid_from, valid_to = _validity_window(call, None)
    lock_ids = _lock_ids(call, entry)
    created = await _async_save_key(
        coordinator,
        MobileKeyKey4Friends(
            id=0,
            name=call.data[CONF_NAME],
            email=call.data[CONF_EMAIL],
            language=call.data[CONF_LANGUAGE],
            valid_from=valid_from,
            valid_to=valid_to,
            state=0,
            authorizations=build_key4friends_authorizations(
                coordinator.data,
                lock_ids,
                {},
                _custom_lock_names(call, entry, lock_ids),
            ),
        ),
        create=True,
    )
    return _key_response(call.hass, entry, created) if call.return_response else None


async def _async_update_key4friends(call: ServiceCall) -> ServiceResponse:
    """Update the targeted Key4Friends key; omitted fields are kept."""
    entry, _device, key = _key_context(call)
    coordinator = entry.runtime_data
    valid_from, valid_to = _validity_window(call, key)
    existing = {
        authorization.lock_id: authorization for authorization in key.authorizations
    }
    lock_ids = (
        _lock_ids(call, entry) if ATTR_LOCKS in call.data else list(existing)
    )
    updated = replace(
        key,
        name=call.data.get(CONF_NAME, key.name),
        language=call.data.get(CONF_LANGUAGE, key.language),
        valid_from=valid_from,
        valid_to=valid_to,
        authorizations=build_key4friends_authorizations(
            coordinator.data,
            lock_ids,
            existing,
            _custom_lock_names(call, entry, lock_ids),
        ),
    )
    # An unchanged draft skips the cloud call, so no-op automations do
    # not spam the guest with change notification emails.
    if updated != key:
        await _async_save_key(coordinator, updated, create=False)
    return _key_response(call.hass, entry, updated) if call.return_response else None


async def _async_delete_key4friends(call: ServiceCall) -> None:
    """Delete the targeted Key4Friends key and its registry device."""
    entry, device, key = _key_context(call)
    await entry.runtime_data.async_delete_key4friends(key)
    dr.async_get(call.hass).async_remove_device(device.id)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the MobileKey service actions.

    Registration happens once at integration setup, so the actions are
    listed and validated even while no config entry is loaded; handlers
    resolve and check their target entry on every call.
    """
    for service, handler, schema, supports_response in (
        (
            SERVICE_KEY4FRIENDS_LIST,
            _async_list_key4friends,
            _ENTRY_SCHEMA,
            SupportsResponse.ONLY,
        ),
        (
            SERVICE_KEY4FRIENDS_GET,
            _async_get_key4friends,
            _DEVICE_SCHEMA,
            SupportsResponse.ONLY,
        ),
        (
            SERVICE_KEY4FRIENDS_CREATE,
            _async_create_key4friends,
            _CREATE_SCHEMA,
            SupportsResponse.OPTIONAL,
        ),
        (
            SERVICE_KEY4FRIENDS_UPDATE,
            _async_update_key4friends,
            _UPDATE_SCHEMA,
            SupportsResponse.OPTIONAL,
        ),
        (
            SERVICE_KEY4FRIENDS_DELETE,
            _async_delete_key4friends,
            _DEVICE_SCHEMA,
            SupportsResponse.NONE,
        ),
    ):
        hass.services.async_register(
            DOMAIN, service, handler, schema=schema, supports_response=supports_response
        )
