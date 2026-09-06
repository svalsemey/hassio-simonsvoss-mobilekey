"""Shared helpers for the MobileKey integration."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .models import (
    MobileKeyKey4Friends,
    MobileKeyKey4FriendsAuthorization,
    MobileKeyLockingSystem,
)


def as_local_naive(value: datetime) -> datetime:
    """Return the value as a naive timestamp expressed in local time.

    The cloud stores Key4Friends validity bounds as naive local
    timestamps, mirroring what the mobile applications send. Naive
    values are already local and pass through unchanged; aware values
    are converted to the Home Assistant time zone first.
    """
    if value.tzinfo is None:
        return value
    return dt_util.as_local(value).replace(tzinfo=None)


def as_local_timestamp(value: datetime | None) -> datetime | None:
    """Attach the Home Assistant time zone to a naive local timestamp.

    Key4Friends validity bounds are naive timestamps expressed in local
    time; attaching the configured time zone declares them without
    shifting the value.
    """
    if value is None:
        return None
    return value.replace(tzinfo=dt_util.get_default_time_zone())


def key4friends_expired(key: MobileKeyKey4Friends) -> bool | None:
    """Return whether the validity window of the key has ended.

    Validity bounds are naive timestamps expressed in the Home Assistant
    time zone, so the comparison uses the local wall-clock time. The
    cloud keeps expired keys listed until their owner deletes them.
    """
    if key.valid_to is None:
        return None
    return dt_util.now().replace(tzinfo=None) > key.valid_to


def key4friends_lock_summary(
    key: MobileKeyKey4Friends, system: MobileKeyLockingSystem
) -> list[dict[str, Any]]:
    """Summarize the lock authorizations carried by the key.

    Each entry reports the lock ID and system name along with the
    possibly different name shown to the guest. The system name is None
    when the lock is no longer part of the locking system.
    """
    return [
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


def build_key4friends_authorizations(
    system: MobileKeyLockingSystem,
    lock_ids: Iterable[int],
    existing: Mapping[int, MobileKeyKey4FriendsAuthorization],
    custom_names: Mapping[int, str] | None = None,
) -> tuple[MobileKeyKey4FriendsAuthorization, ...]:
    """Build the authorization entries of a Key4Friends key.

    Existing entries are reused so guest-facing names and notes survive
    edits; locks newly authorized default to their system name, which
    requires them to be part of the locking system. Custom names, when
    provided, override the guest-facing name of their lock.
    """
    names = custom_names or {}
    authorizations: list[MobileKeyKey4FriendsAuthorization] = []
    for lock_id in lock_ids:
        authorization = existing.get(lock_id) or MobileKeyKey4FriendsAuthorization(
            lock_id=lock_id, name=system.locks[lock_id].name
        )
        if (name := names.get(lock_id)) is not None:
            authorization = replace(authorization, name=name)
        authorizations.append(authorization)
    return tuple(authorizations)
