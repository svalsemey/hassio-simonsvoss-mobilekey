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
from .coordinator import MobileKeyConfigEntry
from .entity import MobileKeyLockEntity, async_setup_dynamic_entities

# Commands are relayed to the locks over the radio network; sending them
# one at a time avoids flooding the SmartBridge.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class MobileKeyLockButtonDescription(ButtonEntityDescription):
    """Describes a button sending a command to a MobileKey lock."""

    press_fn: Callable[[MobileKeyApiClient, int], Awaitable[None]]


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MobileKeyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MobileKey buttons from a config entry."""
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

    async def async_press(self) -> None:
        """Send the command of this button to the lock through the cloud."""
        lock = self.lock
        try:
            await self.entity_description.press_fn(self.coordinator.client, lock.id)
        except MobileKeyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lock_command_failed",
                translation_placeholders={"name": lock.name},
            ) from err
        # Commands are executed asynchronously by the cloud; refreshing lets
        # the resulting pending task and state changes surface quickly.
        await self.coordinator.async_request_refresh()
