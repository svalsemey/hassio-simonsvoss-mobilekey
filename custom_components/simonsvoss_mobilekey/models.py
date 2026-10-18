"""Data models for the SimonsVoss MobileKey cloud API."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from functools import cache
import logging
from typing import Any, Final, Self

_LOGGER = logging.getLogger(__name__)

# Bare DTO type names used to discriminate polymorphic API objects.
_DTO_TRANSPONDER: Final = "SimonsVoss.Soho.Services.UserGate.DTO.Transponder"
_DTO_FIXED_DATES_EXPIRATION: Final = (
    "SimonsVoss.Soho.Services.UserGate.DTO.FixedDatesExpirationSettings"
)
_DTO_CORE_COMPONENT: Final = "SimonsVoss.Soho.Services.UserGate.DTO.CoreComponent"
_DTO_DM_COMPONENT: Final = "SimonsVoss.Soho.Services.UserGate.DTO.DMComponent"
_DTO_NETWORK_COMPONENT: Final = "SimonsVoss.Soho.Services.UserGate.DTO.NetworkComponent"

# Value of a lock or SmartBridge ``state`` field reporting connectivity.
_CONNECTED_STATE: Final = 2

# Value of an authorization ``state`` field granting access to a lock.
_AUTHORIZATION_GRANTED: Final = 1

# Value of a ``batteryStatus`` field reporting a healthy battery.
_BATTERY_OK: Final = 0


def dto_type(raw: Mapping[str, Any]) -> str:
    """Return the bare DTO type name, without the assembly qualifier."""
    return str(raw.get("$type", "")).partition(",")[0].strip()


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp, or None when absent or malformed."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _printable(value: Any) -> str:
    """Return the value as text stripped of non-printable characters.

    Some devices report corrupted free-text fields, such as catalog
    order codes containing control characters; stripping them keeps
    registry fields and logs clean.
    """
    return "".join(char for char in str(value) if char.isprintable()).strip()


@cache
def _log_unsupported_item(kind: str, type_name: str) -> None:
    """Warn about an API item the models cannot represent.

    The cache keeps one entry per kind and DTO type pair, so recurring
    polls reporting the same unsupported item do not flood the log.
    """
    _LOGGER.warning(
        "Skipping unsupported %s of type %s reported by the MobileKey cloud;"
        " the related device is not available in Home Assistant",
        kind,
        type_name,
    )


def _parse_api_item[ItemT](
    raw: Any, factory: Callable[[Mapping[str, Any]], ItemT], kind: str
) -> ItemT | None:
    """Build one API item, or None when the factory cannot represent it."""
    try:
        item = factory(raw)
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        _log_unsupported_item(
            kind,
            (dto_type(raw) if isinstance(raw, Mapping) else type(raw).__name__)
            or "<untyped>",
        )
        _LOGGER.debug("Unsupported %s item (%r): %s", kind, err, raw)
        return None
    return item


def parse_api_items[ItemT](
    raw_items: Iterable[Any],
    factory: Callable[[Mapping[str, Any]], ItemT],
    kind: str,
) -> list[ItemT]:
    """Build the items of an API collection, skipping unsupported ones.

    The cloud reports every component of the installation, including
    device types not modeled here, such as PIN code keypads. Items the
    factory cannot represent are skipped with a warning instead of
    failing the whole payload, so a single exotic device never prevents
    the rest of the installation from loading.
    """
    return [
        item
        for raw in raw_items
        if (item := _parse_api_item(raw, factory, kind)) is not None
    ]


def _parse_component[T](
    components: Mapping[str, Mapping[str, Any]],
    dto_type: str,
    factory: Callable[[Mapping[str, Any]], T],
) -> T | None:
    """Build the lock component of the given DTO type, if present."""
    return None if (raw := components.get(dto_type)) is None else factory(raw)


class MobileKeyDoorStatus(IntEnum):
    """Door and bolt state reported by the door monitoring component."""

    UNKNOWN = -1
    OPEN = 1
    CLOSED_LOCKED = 2
    CLOSED_UNLOCKED = 3

    @classmethod
    def _missing_(cls, value: object) -> Self:
        """Map values not documented by the API to UNKNOWN."""
        return cls.UNKNOWN


class MobileKeySignalQuality(IntEnum):
    """Radio signal quality, from no connection (0) to optimal (3)."""

    UNKNOWN = -1
    NONE = 0
    WEAK = 1
    GOOD = 2
    EXCELLENT = 3

    @classmethod
    def _missing_(cls, value: object) -> Self:
        """Map values not documented by the API to UNKNOWN."""
        return cls.UNKNOWN


@dataclass(frozen=True, slots=True, kw_only=True)
class _ConnectableModel:
    """Base model for devices reporting a cloud connectivity state."""

    state: int

    @property
    def connected(self) -> bool:
        """Return whether the device is currently reported as connected."""
        return self.state == _CONNECTED_STATE


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyCoreComponent:
    """Intrinsic properties of the locking device itself."""

    phi: str
    firmware: str
    order_code: str
    battery_critical: bool
    flip_flop: bool
    timeout: int

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the component from its API representation.

        Some devices report a corrupted catalog order code; non-printable
        characters are stripped from it.
        """
        return cls(
            phi=raw["phi"],
            firmware=raw["firmware"],
            order_code=_printable(raw["orderCode"]),
            battery_critical=raw["batteryStatus"] != _BATTERY_OK,
            flip_flop=raw["settings"]["flipFlop"],
            timeout=raw["settings"]["timeout"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyDoorMonitoringComponent:
    """Door monitoring properties of a lock."""

    door_status: MobileKeyDoorStatus
    sensor_status: int
    open_too_long_timeout: int | None
    bolt_monitoring_disabled: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the component from its API representation."""
        return cls(
            door_status=MobileKeyDoorStatus(raw["doorStatus"]),
            sensor_status=raw["sensorStatus"],
            open_too_long_timeout=raw["settings"]["openTooLongTimeout"],
            bolt_monitoring_disabled=raw["settings"]["deactivateBoltMonitoring"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyNetworkComponent(_ConnectableModel):
    """Radio network properties of a lock."""

    quality: MobileKeySignalQuality
    parent_chip_id: str | None
    is_online: bool
    chip_id: str
    wake_up_mode: int

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the component from its API representation."""
        return cls(
            state=raw["state"],
            quality=MobileKeySignalQuality(raw["quality"]),
            parent_chip_id=raw.get("parentChipID"),
            is_online=raw["settings"]["isOnline"],
            chip_id=raw["settings"]["chipID"],
            wake_up_mode=raw["settings"]["wakeUpMode"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyIdentMedium:
    """An identification medium (key) enrolled in the locking system."""

    id: int
    name: str
    is_transponder: bool
    phi: str | None
    firmware: str | None
    production_date: datetime | None
    order_code: str | None
    long_opening: bool
    valid_from: datetime | None
    valid_to: datetime | None
    key_state: int
    state: int
    has_pending_task: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the ident medium from its API representation."""
        info = raw.get("info") or {}
        key_data = raw["keyData"]
        # Validity dates are only meaningful for fixed-dates expiration.
        expiration = key_data.get("expirationSettings") or {}
        if dto_type(expiration) != _DTO_FIXED_DATES_EXPIRATION:
            expiration = {}
        return cls(
            id=raw["id"],
            name=key_data["name"],
            is_transponder=dto_type(raw) == _DTO_TRANSPONDER,
            phi=info.get("phi"),
            firmware=info.get("firmware"),
            production_date=parse_datetime(info.get("productionDate")),
            order_code=(
                None if (code := info.get("orderCode")) is None else _printable(code)
            ),
            long_opening=key_data["longOpening"],
            valid_from=parse_datetime(expiration.get("validFrom")),
            valid_to=parse_datetime(expiration.get("validTo")),
            key_state=key_data["state"],
            state=raw["state"],
            has_pending_task=raw.get("pendingTask") is not None,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyLock(_ConnectableModel):
    """A lock and its components."""

    id: int
    name: str
    has_pending_task: bool
    core: MobileKeyCoreComponent | None
    door: MobileKeyDoorMonitoringComponent | None
    network: MobileKeyNetworkComponent | None

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the lock from its API representation.

        Components are matched on their DTO type, never on their position.
        """
        components = {
            dto_type(component): component for component in raw["components"]
        }
        return cls(
            id=raw["id"],
            name=raw["name"],
            state=raw["state"],
            has_pending_task=raw.get("pendingTask") is not None,
            core=_parse_component(
                components, _DTO_CORE_COMPONENT, MobileKeyCoreComponent.from_api
            ),
            door=_parse_component(
                components,
                _DTO_DM_COMPONENT,
                MobileKeyDoorMonitoringComponent.from_api,
            ),
            network=_parse_component(
                components, _DTO_NETWORK_COMPONENT, MobileKeyNetworkComponent.from_api
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeySmartBridge(_ConnectableModel):
    """A SmartBridge gateway relaying locks to the cloud."""

    id: int
    name: str
    mobile_key_id: str
    chip_id: str
    quality: MobileKeySignalQuality
    parent_chip_id: str | None

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the SmartBridge from its API representation."""
        return cls(
            id=raw["id"],
            name=raw["name"],
            mobile_key_id=raw["mobileKeyID"],
            chip_id=raw["chipID"],
            state=raw["state"],
            quality=MobileKeySignalQuality(raw["quality"]),
            parent_chip_id=raw.get("parentChipID"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyAuthorization:
    """An entry of the key/lock authorization matrix."""

    lock_id: int
    ekey_id: int
    granted: bool
    readonly: bool

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the authorization from its API representation."""
        return cls(
            lock_id=raw["lockID"],
            ekey_id=raw["eKeyID"],
            granted=raw["state"] == _AUTHORIZATION_GRANTED,
            readonly=raw["readonly"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyKey4FriendsAuthorization:
    """A lock authorization carried by a Key4Friends key."""

    lock_id: int
    name: str
    notes: str = ""

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the authorization from its API representation."""
        return cls(
            lock_id=raw["lockID"],
            name=raw["name"],
            notes=raw.get("notes") or "",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyKey4Friends:
    """A Key4Friends virtual key shared with a guest by e-mail.

    Validity bounds are naive timestamps expressed in local time,
    mirroring what the mobile applications send. An expired key stays
    listed by the cloud until its owner deletes it.
    """

    id: int
    name: str
    email: str | None
    language: str
    valid_from: datetime | None
    valid_to: datetime | None
    state: int
    authorizations: tuple[MobileKeyKey4FriendsAuthorization, ...]

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the key from its API representation."""
        expiration = raw.get("expirationSettings") or {}
        return cls(
            id=raw["id"],
            name=raw["name"],
            email=raw.get("email"),
            language=raw["language"],
            valid_from=parse_datetime(expiration.get("validFrom")),
            valid_to=parse_datetime(expiration.get("validTo")),
            state=raw["state"],
            authorizations=tuple(
                map(MobileKeyKey4FriendsAuthorization.from_api, raw["authorizations"])
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MobileKeyLockingSystem:
    """Full state of a MobileKey locking system."""

    name: str
    # Naive timestamp of the last data change, expressed in UTC.
    version: datetime | None
    locks: Mapping[int, MobileKeyLock]
    ident_media: Mapping[int, MobileKeyIdentMedium]
    smart_bridges: Mapping[int, MobileKeySmartBridge]
    authorizations: tuple[MobileKeyAuthorization, ...]
    # Key4Friends keys, fetched separately and merged in by the coordinator.
    key4friends: Mapping[int, MobileKeyKey4Friends] = field(default_factory=dict)

    def smart_bridge_by_chip_id(
        self, chip_id: str | None
    ) -> MobileKeySmartBridge | None:
        """Return the SmartBridge owning the given chip ID, if any.

        Locks and chained SmartBridges reference their parent gateway
        through its chip ID rather than its numeric ID.
        """
        if chip_id is None:
            return None
        return next(
            (
                bridge
                for bridge in self.smart_bridges.values()
                if bridge.chip_id == chip_id
            ),
            None,
        )

    def authorized_media(self, lock_id: int) -> tuple[MobileKeyIdentMedium, ...]:
        """Return the ident media granted access to the given lock."""
        return tuple(
            medium
            for authorization in self.authorizations
            if authorization.lock_id == lock_id
            and authorization.granted
            and (medium := self.ident_media.get(authorization.ekey_id)) is not None
        )

    def authorized_locks(self, ekey_id: int) -> tuple[MobileKeyLock, ...]:
        """Return the locks the given ident medium is granted access to."""
        return tuple(
            lock
            for authorization in self.authorizations
            if authorization.ekey_id == ekey_id
            and authorization.granted
            and (lock := self.locks.get(authorization.lock_id)) is not None
        )

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> Self:
        """Build the locking system from its API representation.

        Collections are parsed leniently: items of an unsupported type,
        such as PIN code keypads, are skipped so the rest of the
        installation keeps working.
        """
        return cls(
            name=raw["name"],
            version=parse_datetime(raw["version"]),
            locks={
                lock.id: lock
                for lock in parse_api_items(raw["locks"], MobileKeyLock.from_api, "lock")
            },
            ident_media={
                medium.id: medium
                for medium in parse_api_items(
                    raw["identMedia"], MobileKeyIdentMedium.from_api, "ident medium"
                )
            },
            smart_bridges={
                bridge.id: bridge
                for bridge in parse_api_items(
                    raw["smartBridges"], MobileKeySmartBridge.from_api, "SmartBridge"
                )
            },
            authorizations=tuple(
                parse_api_items(
                    raw["authorizations"], MobileKeyAuthorization.from_api, "authorization"
                )
            ),
        )
