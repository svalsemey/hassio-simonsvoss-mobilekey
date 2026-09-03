"""Button platform for the MobileKey integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import MobileKeyApiClient, MobileKeyError
from .const import DOMAIN
from .coordinator import MobileKeyConfigEntry, MobileKeyCoordinator
from .entity import (
    MobileKeyLockEntity,
    MobileKeySystemEntity,
    async_setup_dynamic_entities,
)

# Commands are relayed to the locks over the radio network; sending them
# one at a time avoids flooding the SmartBridge.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class MobileKeyLockButtonDescription(ButtonEntityDescription):
    """Describes a button sending a command to a MobileKey lock."""

    press_fn: Callable[[MobileKeyApiClient, int], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class MobileKeySystemButtonDescription(ButtonEntityDescription):
    """Describes a button acting on the MobileKey locking system."""

    press_fn: Callable[[MobileKeyCoordinator], Awaitable[None]]


LOCK_DESCRIPTIONS: tuple[MobileKeyLockButtonDescription, ...] = (
    MobileKeyLockButtonDescription(
        key="open",
        translation_key="open",
        press_fn=lambda client, lock_id: client.async_open_lock(lock_id),
    ),
    MobileKeyLockButtonDescription(
        key="read_audit_trail",
        translation_key="read_audit_trail",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda client, lock_id: client.async_read_audit_trail(lock_id),
    ),
)

SYSTEM_DESCRIPTIONS: tuple[MobileKeySystemButtonDescription, ...] = (
    # Manual refreshes go through the coordinator debouncer, which absorbs
    # repeated presses.
    MobileKeySystemButtonDescription(
        key="refresh",
        translation_key="refresh",
        press_fn=lambda coordinator: coordinator.async_request_refresh(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MobileKey buttons from a config entry."""
    # The system device is unique and permanent: no dynamic tracking.
    async_add_entities(
        MobileKeySystemButton(entry.runtime_data, description)
        for description in SYSTEM_DESCRIPTIONS
    )
    async_setup_dynamic_entities(
        entry,
        async_add_entities,
        lambda system: system.locks,
        lambda coordinator, lock: (
            MobileKeyLockButton(coordinator, description, lock)
            for description in LOCK_DESCRIPTIONS
        ),
    )


class MobileKeyLockButton(MobileKeyLockEntity, ButtonEntity):
    """Button sending a command to a MobileKey lock."""

    entity_description: MobileKeyLockButtonDescription
    _command_in_flight = False

    @property
    def available(self) -> bool:
        """Return whether a command can currently be sent to the lock.

        Buttons deliberately ignore polling failures: commands go through
        a separate endpoint that may still succeed. They only require the
        lock to exist in the last known data and no command of their own
        to be awaiting acknowledgment.
        """
        return (
            not self._command_in_flight and self._lock_id in self.coordinator.data.locks
        )

    async def async_press(self) -> None:
        """Send the command of this button to the lock through the cloud.

        The cloud only acknowledges once the SmartBridge has relayed the
        command to the lock; the button is unavailable in the meantime,
        which also rejects duplicate presses.
        """
        lock = self.lock
        self._command_in_flight = True
        self.async_write_ha_state()
        try:
            await self.entity_description.press_fn(self.coordinator.client, lock.id)
        except MobileKeyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lock_command_failed",
                translation_placeholders={"name": lock.name},
            ) from err
        finally:
            self._command_in_flight = False
            self.async_write_ha_state()
        # The lock state changes asynchronously after the acknowledgment;
        # refreshing lets the resulting pending task and state changes
        # surface quickly.
        await self.coordinator.async_request_refresh()


class MobileKeySystemButton(MobileKeySystemEntity, ButtonEntity):
    """Button acting on the MobileKey locking system."""

    entity_description: MobileKeySystemButtonDescription

    @property
    def available(self) -> bool:
        """Return whether the button is available, which is always the case.

        A manual refresh is precisely most useful while cloud polling is
        failing.
        """
        return True

    async def async_press(self) -> None:
        """Execute the system action of this button."""
        await self.entity_description.press_fn(self.coordinator)
