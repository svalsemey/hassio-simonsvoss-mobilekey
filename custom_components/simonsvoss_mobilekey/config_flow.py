"""Config flow for the MobileKey integration."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
import logging
from typing import Any, Final

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_EMAIL,
    CONF_LANGUAGE,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    DateTimeSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import (
    MobileKeyApiClient,
    MobileKeyAuthenticationError,
    MobileKeyConnectionError,
    MobileKeyError,
)
from .const import (
    ATTR_VALID_FROM,
    ATTR_VALID_TO,
    CONF_USER_AGENT,
    DOMAIN,
    KEY4FRIENDS_LANGUAGES,
    SCANINTERVAL_DEFAULT,
    SCANINTERVAL_MAX,
    SCANINTERVAL_MIN,
    USER_AGENT_DEFAULT,
)
from .coordinator import MobileKeyCoordinator, entry_user_agent
from .models import MobileKeyKey4Friends, MobileKeyKey4FriendsAuthorization
from .util import as_local_naive, build_key4friends_authorizations

_LOGGER = logging.getLogger(__name__)

# Field names of the Key4Friends option-flow forms.
CONF_KEY: Final = "key"
CONF_AUTHORIZED_LOCKS: Final = "authorized_locks"

# Default validity offered for a new key: from now until this many days
# later at 23:59:59, in the Home Assistant time zone.
_DEFAULT_VALIDITY_DAYS: Final = 3

# Polling interval field, shared by the user step and the options flow.
_SCAN_INTERVAL_SELECTOR = vol.All(
    NumberSelector(
        NumberSelectorConfig(
            min=SCANINTERVAL_MIN,
            max=SCANINTERVAL_MAX,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=UnitOfTime.SECONDS,
        )
    ),
    vol.Coerce(int),
)

_LANGUAGE_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=list(KEY4FRIENDS_LANGUAGES),
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="key4friends_language",
    )
)

_EMAIL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(
            CONF_SCAN_INTERVAL, default=SCANINTERVAL_DEFAULT
        ): _SCAN_INTERVAL_SELECTOR,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL, default=SCANINTERVAL_DEFAULT
        ): _SCAN_INTERVAL_SELECTOR,
        vol.Required(CONF_USER_AGENT, default=USER_AGENT_DEFAULT): TextSelector(),
    }
)


def _parse_local_naive(value: str) -> datetime | None:
    """Parse a datetime form value into a naive local datetime.

    The cloud stores Key4Friends validity bounds as naive local
    timestamps, mirroring what the mobile applications send. Returns
    None when the value is unparsable.
    """
    if (parsed := dt_util.parse_datetime(value)) is None:
        return None
    return as_local_naive(parsed)


def _form_datetime(value: datetime) -> str:
    """Format a naive local datetime for a datetime selector field."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


class MobileKeyOptionsFlow(OptionsFlow):
    """Handle the options flow for MobileKey."""

    _key_id: int | None = None
    _draft: MobileKeyKey4Friends | None = None

    @property
    def _coordinator(self) -> MobileKeyCoordinator:
        """Return the coordinator of the config entry being configured."""
        return self.config_entry.runtime_data

    def _key4friends_schema(self, key: MobileKeyKey4Friends | None) -> vol.Schema:
        """Build the form schema creating or editing a Key4Friends key.

        Form schemas are serialized to the frontend, so the validity
        bounds are plain datetime selectors whose string values are
        parsed on submit. The e-mail address is only requested at
        creation: the cloud does not allow changing the recipient of an
        existing key. Lock choices cover the system locks plus any lock
        the key already references, so an authorization is never
        silently dropped.
        """
        lock_options = {
            str(lock.id): lock.name for lock in self._coordinator.data.locks.values()
        }
        if key is not None:
            lock_options |= {
                lock_id: authorization.name
                for authorization in key.authorizations
                if (lock_id := str(authorization.lock_id)) not in lock_options
            }
        schema: dict[vol.Marker, Any] = {vol.Required(CONF_NAME): TextSelector()}
        if key is None:
            schema[vol.Required(CONF_EMAIL)] = _EMAIL_SELECTOR
        schema |= {
            vol.Required(CONF_LANGUAGE): _LANGUAGE_SELECTOR,
            vol.Required(ATTR_VALID_FROM): DateTimeSelector(),
            vol.Required(ATTR_VALID_TO): DateTimeSelector(),
            vol.Required(CONF_AUTHORIZED_LOCKS, default=list): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=value, label=label)
                        for value, label in lock_options.items()
                    ],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
        return vol.Schema(schema)

    def _key4friends_from_input(
        self, user_input: dict[str, Any], key: MobileKeyKey4Friends | None
    ) -> tuple[MobileKeyKey4Friends | None, dict[str, str]]:
        """Build the key described by the form input.

        Returns the key and no errors, or None and the per-field errors
        when a validity bound is unparsable or the window is inverted or
        empty. When editing, the e-mail address and raw state of the key
        are preserved, and so are its existing authorizations, including
        their guest-facing names and notes.
        """
        valid_from = _parse_local_naive(user_input[ATTR_VALID_FROM])
        valid_to = _parse_local_naive(user_input[ATTR_VALID_TO])
        if valid_from is None or valid_to is None:
            return None, {
                field: "invalid_datetime"
                for field, value in (
                    (ATTR_VALID_FROM, valid_from),
                    (ATTR_VALID_TO, valid_to),
                )
                if value is None
            }
        if valid_to <= valid_from:
            return None, {ATTR_VALID_TO: "invalid_validity_window"}
        existing: dict[int, MobileKeyKey4FriendsAuthorization] = (
            {}
            if key is None
            else {
                authorization.lock_id: authorization
                for authorization in key.authorizations
            }
        )
        return (
            MobileKeyKey4Friends(
                id=0 if key is None else key.id,
                name=user_input[CONF_NAME].strip(),
                email=user_input[CONF_EMAIL].strip() if key is None else key.email,
                language=user_input[CONF_LANGUAGE],
                valid_from=valid_from,
                valid_to=valid_to,
                state=0 if key is None else key.state,
                authorizations=build_key4friends_authorizations(
                    self._coordinator.data,
                    (int(lock_id) for lock_id in user_input[CONF_AUTHORIZED_LOCKS]),
                    existing,
                ),
            ),
            {},
        )

    def _lock_system_name(
        self, authorization: MobileKeyKey4FriendsAuthorization
    ) -> str:
        """Return the system name of the authorized lock.

        Falls back to the guest-facing name carried by the authorization
        when the lock is no longer part of the locking system.
        """
        return (
            authorization.name
            if (lock := self._coordinator.data.locks.get(authorization.lock_id))
            is None
            else lock.name
        )

    def _custom_name_fields(
        self, draft: MobileKeyKey4Friends
    ) -> dict[str, MobileKeyKey4FriendsAuthorization]:
        """Map one form field per authorized lock of the draft key.

        Lock names are user data and need no translation, so each field
        is keyed, and therefore labeled, by the system name of its lock.
        A name colliding with a previous field is suffixed with the lock
        ID until unique, so no authorization is ever folded into another.
        """
        fields: dict[str, MobileKeyKey4FriendsAuthorization] = {}
        for authorization in draft.authorizations:
            label = self._lock_system_name(authorization)
            while label in fields:
                label = f"{label} (#{authorization.lock_id})"
            fields[label] = authorization
        return fields

    async def _async_save_key(self, draft: MobileKeyKey4Friends) -> dict[str, str]:
        """Send the draft key to the cloud and merge the result locally.

        Creation and edition are told apart by the edited key ID kept on
        the flow. Returns the form errors to display, empty on success.
        """
        client = self._coordinator.client
        try:
            if self._key_id is None:
                draft = await client.async_create_key4friends(draft)
            else:
                await client.async_update_key4friends(draft)
        except MobileKeyAuthenticationError:
            return {"base": "invalid_auth"}
        except MobileKeyError:
            return {"base": "cannot_connect"}
        self._coordinator.async_upsert_key4friends(draft)
        return {}

    @callback
    def _async_finish(self) -> ConfigFlowResult:
        """Conclude a key management action, leaving the options unchanged."""
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu.

        Key4Friends actions require the entry to be loaded; otherwise
        only the integration settings are reachable. Editing is only
        offered when at least one key exists, so creating the first key
        is a single menu choice away.
        """
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return await self.async_step_settings()
        menu_options = ["settings", "create_key"]
        if self._coordinator.data.key4friends:
            menu_options.append("edit_key")
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the MobileKey integration settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Printable ASCII keeps the value a valid HTTP header and rules
            # out header-injection attempts through control characters.
            user_agent = user_input[CONF_USER_AGENT].strip()
            if user_agent and user_agent.isascii() and user_agent.isprintable():
                return self.async_create_entry(
                    data={**user_input, CONF_USER_AGENT: user_agent}
                )
            errors[CONF_USER_AGENT] = "invalid_user_agent"
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or self.config_entry.options
            ),
            errors=errors,
        )

    async def async_step_create_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the properties of a new Key4Friends key.

        The key is sent to the cloud once the guest-facing lock names
        have been reviewed in the next step; a key without any
        authorized lock is sent directly.
        """
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            draft, errors = self._key4friends_from_input(user_input, None)
            if draft is not None:
                self._draft = draft
                if draft.authorizations:
                    return await self.async_step_guest_lock_names()
                if not (errors := await self._async_save_key(draft)):
                    return self._async_finish()
        # Redisplay the submitted values on error; suggest defaults otherwise.
        suggested_values = user_input
        if suggested_values is None:
            language = self.hass.config.language.partition("-")[0]
            now = dt_util.now().replace(tzinfo=None, microsecond=0)
            suggested_values = {
                CONF_LANGUAGE: language if language in KEY4FRIENDS_LANGUAGES else "en",
                ATTR_VALID_FROM: _form_datetime(now),
                ATTR_VALID_TO: _form_datetime(
                    (now + timedelta(days=_DEFAULT_VALIDITY_DAYS)).replace(
                        hour=23, minute=59, second=59
                    )
                ),
            }
        return self.async_show_form(
            step_id="create_key",
            data_schema=self.add_suggested_values_to_schema(
                self._key4friends_schema(None), suggested_values
            ),
            errors=errors,
        )

    async def async_step_edit_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the Key4Friends key to edit."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._key_id = int(user_input[CONF_KEY])
            return await self.async_step_edit_key_settings()
        return self.async_show_form(
            step_id="edit_key",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_KEY): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=str(key.id),
                                    label=(
                                        f"{key.name} ({key.email})"
                                        if key.email
                                        else key.name
                                    ),
                                )
                                for key in self._coordinator.data.key4friends.values()
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_key_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the selected Key4Friends key."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if (
            self._key_id is None
            or (key := self._coordinator.data.key4friends.get(self._key_id)) is None
        ):
            return self.async_abort(reason="key_not_found")
        errors: dict[str, str] = {}
        if user_input is not None:
            updated, errors = self._key4friends_from_input(user_input, key)
            if updated is not None:
                self._draft = updated
                if updated.authorizations:
                    return await self.async_step_guest_lock_names()
                if not (errors := await self._async_save_key(updated)):
                    return self._async_finish()
        # Redisplay the submitted values on error; suggest the stored key otherwise.
        suggested_values = user_input
        if suggested_values is None:
            suggested_values = {
                CONF_NAME: key.name,
                CONF_LANGUAGE: key.language,
                CONF_AUTHORIZED_LOCKS: [
                    str(authorization.lock_id) for authorization in key.authorizations
                ],
            }
            if key.valid_from is not None:
                suggested_values[ATTR_VALID_FROM] = _form_datetime(key.valid_from)
            if key.valid_to is not None:
                suggested_values[ATTR_VALID_TO] = _form_datetime(key.valid_to)
        return self.async_show_form(
            step_id="edit_key_settings",
            data_schema=self.add_suggested_values_to_schema(
                self._key4friends_schema(key), suggested_values
            ),
            description_placeholders={"name": key.name, "email": key.email or "-"},
            errors=errors,
        )

    async def async_step_guest_lock_names(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Review the lock names shown to the guest, then save the key.

        One optional text field is offered per authorized lock, labeled
        with the system name of the lock and suggesting the name
        currently shown to the guest; an empty field falls back to the
        system name.
        """
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if (draft := self._draft) is None:
            return self.async_abort(reason="key_not_found")
        errors: dict[str, str] = {}
        if user_input is not None:
            self._draft = draft = replace(
                draft,
                authorizations=tuple(
                    replace(
                        authorization,
                        name=(
                            (user_input.get(field) or "").strip()
                            or self._lock_system_name(authorization)
                        ),
                    )
                    for field, authorization in self._custom_name_fields(draft).items()
                ),
            )
            if not (errors := await self._async_save_key(draft)):
                return self._async_finish()
        fields = self._custom_name_fields(draft)
        return self.async_show_form(
            step_id="guest_lock_names",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Optional(field): TextSelector() for field in fields}),
                {field: authorization.name for field, authorization in fields.items()},
            ),
            description_placeholders={"name": draft.name},
            errors=errors,
        )


class MobileKeyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for MobileKey."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MobileKeyOptionsFlow:
        """Create the options flow."""
        return MobileKeyOptionsFlow()

    async def _async_validate_credentials(
        self, username: str, password: str, user_agent: str = USER_AGENT_DEFAULT
    ) -> tuple[dict[str, str], str]:
        """Check the credentials against the cloud.

        The validation client mirrors the runtime configuration, including
        the configured user agent. Return the form errors and the locking
        system name, which doubles as proof that the account data is
        reachable.
        """
        # A throwaway session keeps validation cookies out of any shared jar.
        session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            system = await MobileKeyApiClient(
                username, password, session, user_agent=user_agent
            ).async_get_locking_system()
        except MobileKeyAuthenticationError:
            return {"base": "invalid_auth"}, ""
        except MobileKeyConnectionError:
            return {"base": "cannot_connect"}, ""
        except Exception:
            _LOGGER.exception("Unexpected error while validating credentials")
            return {"base": "unknown"}, ""
        finally:
            # Sessions from the helper share the Home Assistant connector and
            # replace close() with a safeguard; detaching is the supported way
            # to release the session while leaving the connector running.
            session.detach()
        return {}, system.name

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial account configuration step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            errors, system_name = await self._async_validate_credentials(
                username, user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_create_entry(
                    title=system_name or username,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]},
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the re-authentication flow after an authentication failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the new password and update the config entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            errors, _ = await self._async_validate_credentials(
                reauth_entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_agent=entry_user_agent(reauth_entry),
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )
