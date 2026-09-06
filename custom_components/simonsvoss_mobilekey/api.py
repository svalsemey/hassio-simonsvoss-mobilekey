"""Asynchronous client for the SimonsVoss MobileKey cloud service."""

import asyncio
from collections.abc import Awaitable, Callable, KeysView, Mapping
from dataclasses import replace
from datetime import datetime
from functools import wraps
from http import HTTPStatus
import logging
import time
from typing import Any, Concatenate, Final

from aiohttp import (
    BasicAuth,
    ClientError,
    ClientResponse,
    ClientSession,
    ClientTimeout,
    hdrs,
)
from yarl import URL

from .const import (
    API_URL_BASE,
    AUTH_METHOD,
    COOKIE_AUTH,
    COOKIE_CLOUDFLARE_BOTMANAGEMENT,
    COOKIE_CLOUDFLARE_USER_VID,
    ENDPOINT_AUTH,
    ENDPOINT_PERFORMREQUEST,
    ENDPOINT_SYSTEM_LOADLOCKING,
    USER_AGENT_DEFAULT,
)
from .models import (
    MobileKeyKey4Friends,
    MobileKeyLockingSystem,
    dto_type,
    parse_datetime,
)

_LOGGER = logging.getLogger(__name__)

_URL_BASE: Final = URL(API_URL_BASE)

# Overall timeout applied to every request, including reading the body.
_TIMEOUT_REQUEST: Final = ClientTimeout(total=30)

# Longer timeout for perform-request commands: lock commands are only
# acknowledged once the SmartBridge has relayed them over the radio.
_TIMEOUT_COMMAND: Final = ClientTimeout(total=60)

# Period during which a freshly obtained session is trusted, so concurrent
# callers hitting an expired session do not trigger redundant logins.
_AUTH_GRACE_PERIOD: Final = 5.0

# HTTP statuses indicating a missing, expired or revoked session.
_AUTH_FAILED_STATUS: Final = frozenset({HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN})

# Cookies that must all be unexpired for requests to be accepted by the
# cloud: the session cookie and the Cloudflare bot-management cookie,
# which is issued with a lifetime of roughly thirty minutes.
_REQUIRED_COOKIES: Final = frozenset(
    {COOKIE_AUTH, COOKIE_CLOUDFLARE_BOTMANAGEMENT, COOKIE_CLOUDFLARE_USER_VID}
)

# Headers sent with every request to the cloud, mirroring those of the
# MobileKey mobile application. The User-Agent completing them is held
# per client instance, as it is configurable. Callers may override any
# header on a per-request basis.
_HEADERS_COMMON: Final[dict[str, str]] = {
    hdrs.ACCEPT: "application/json",
    hdrs.CONTENT_TYPE: "application/json",
    hdrs.ACCEPT_ENCODING: "gzip, deflate, br",
    hdrs.CONNECTION: "keep-alive",
}

# Assembly-qualified DTO type names accepted by the perform-request endpoint.
_DTO_ASSEMBLY: Final = "SimonsVoss.Soho.Services.UserGate"
_DTO_REQUEST_KEY4FRIENDS_CREATE: Final = (
    f"{_DTO_ASSEMBLY}.DTO.CreateKey4FriendsRequest, {_DTO_ASSEMBLY}"
)
_DTO_REQUEST_KEY4FRIENDS_DELETE: Final = (
    f"{_DTO_ASSEMBLY}.DTO.DeleteKey4FriendsRequest, {_DTO_ASSEMBLY}"
)
_DTO_REQUEST_KEY4FRIENDS_LIST: Final = (
    f"{_DTO_ASSEMBLY}.DTO.ListKey4FriendsRequest, {_DTO_ASSEMBLY}"
)
_DTO_REQUEST_KEY4FRIENDS_UPDATE: Final = (
    f"{_DTO_ASSEMBLY}.DTO.UpdateKey4FriendsRequest, {_DTO_ASSEMBLY}"
)
_DTO_REQUEST_LOCK_OPEN: Final = f"{_DTO_ASSEMBLY}.DTO.OpenLockRequest, {_DTO_ASSEMBLY}"
_DTO_REQUEST_AUDITTRAIL_READ: Final = (
    f"{_DTO_ASSEMBLY}.DTO.ReadAuditTrailRequest, {_DTO_ASSEMBLY}"
)
# Bare DTO type prefix and suffix shared by every perform-request
# response, e.g. OkResponse or ListKey4FriendsResponse.
_DTO_RESPONSE_PREFIX: Final = f"{_DTO_ASSEMBLY}.DTO."
_DTO_RESPONSE_SUFFIX: Final = "Response"


class MobileKeyError(Exception):
    """Base exception for all MobileKey client errors."""


class MobileKeyConnectionError(MobileKeyError):
    """Raised when the MobileKey cloud cannot be reached."""


class MobileKeyAuthenticationError(MobileKeyError):
    """Raised when the MobileKey cloud rejects the credentials or session."""


def _reports_api_health[**P, R](
    method: Callable[Concatenate["MobileKeyApiClient", P], Awaitable[R]],
) -> Callable[Concatenate["MobileKeyApiClient", P], Awaitable[R]]:
    """Report the outcome of a cloud operation to the API health flag.

    Both successes and cloud-side failures update the flag; usage errors
    raised before any request is sent leave it untouched.
    """

    @wraps(method)
    async def wrapper(
        self: "MobileKeyApiClient", *args: P.args, **kwargs: P.kwargs
    ) -> R:
        try:
            result = await method(self, *args, **kwargs)
        except (MobileKeyAuthenticationError, MobileKeyConnectionError):
            self._record_api_health(successful=False)
            raise
        self._record_api_health(successful=True)
        return result

    return wrapper


def _key4friends_expiration(key: MobileKeyKey4Friends) -> dict[str, str]:
    """Serialize the validity window of a key to its API representation.

    The cloud expects naive local timestamps, as sent by the mobile
    applications.
    """
    if key.valid_from is None or key.valid_to is None:
        raise MobileKeyError("Key4Friends keys require a complete validity window")
    return {
        "validFrom": key.valid_from.isoformat(),
        "validTo": key.valid_to.isoformat(),
    }


# Maximum length of a response body excerpt quoted in error messages.
_ERROR_BODY_EXCERPT_LENGTH: Final = 256


async def _error_body_excerpt(response: ClientResponse) -> str:
    """Return a short excerpt of an error response body.

    Cloud error responses carry the server-side failure reason; quoting
    an excerpt in the raised error surfaces it in the logs without
    dumping arbitrarily large bodies.
    """
    try:
        body = (await response.text()).strip()
    except (TimeoutError, ClientError, UnicodeDecodeError) as err:
        return f"<unreadable body: {err!r}>"
    return body[:_ERROR_BODY_EXCERPT_LENGTH] or "<empty body>"


class MobileKeyApiClient:
    """Client managing the authenticated session with the MobileKey cloud.

    Authentication is performed with HTTP Basic credentials and yields the
    ``mk-auth`` session cookie, along with the Cloudflare ``__cf_bm`` and
    ``_cfuvid`` cookies. All of them are persisted in the session cookie jar
    and automatically sent back on every subsequent request.
    Cookie lifetime is handled at two levels: the jar transparently stores
    every refreshed ``__cf_bm`` issued by Cloudflare on regular responses,
    and a request attempted after a required cookie has expired triggers a
    re-authentication first, which reissues the full cookie set.
    The outcome of the most recent cloud operation is exposed through
    ``last_call_successful`` and reported to an optional listener, so
    callers can surface the health of the cloud service.
    """

    def __init__(
        self,
        username: str,
        password: str,
        session: ClientSession,
        *,
        user_agent: str = USER_AGENT_DEFAULT,
    ) -> None:
        """Initialize the client with account credentials and an HTTP session."""
        self._basic_auth = BasicAuth(username, password)
        self._session = session
        self._headers = {**_HEADERS_COMMON, hdrs.USER_AGENT: user_agent}
        self._auth_lock = asyncio.Lock()
        self._authenticated_at: float | None = None
        # Outcome of the most recent cloud operation, None before the first
        # one completes; the listener is invoked whenever the value changes.
        self._last_call_successful: bool | None = None
        self._health_listener: Callable[[], None] | None = None
        # Most recent system data version reported by the cloud. The raw
        # string is echoed verbatim in command payloads, as the mobile
        # application does; the parsed form orders successive reports.
        self._version_raw: str | None = None
        self._version: datetime | None = None

    @property
    def version(self) -> datetime | None:
        """Return the most recent system data version reported by the cloud."""
        return self._version

    @property
    def user_agent(self) -> str:
        """Return the User-Agent header sent with every cloud request."""
        return self._headers[hdrs.USER_AGENT]

    @user_agent.setter
    def user_agent(self, value: str) -> None:
        """Change the User-Agent header sent with subsequent requests."""
        self._headers[hdrs.USER_AGENT] = value

    @property
    def last_call_successful(self) -> bool | None:
        """Return the outcome of the most recent cloud operation.

        None means no operation has completed yet.
        """
        return self._last_call_successful

    def set_health_listener(self, listener: Callable[[], None] | None) -> None:
        """Set the callback invoked when the API health flag changes."""
        self._health_listener = listener

    def _record_api_health(self, *, successful: bool) -> None:
        """Record the outcome of a cloud operation, notifying on changes."""
        if successful == self._last_call_successful:
            return
        self._last_call_successful = successful
        if self._health_listener is not None:
            self._health_listener()

    def _track_version(self, version: Any) -> None:
        """Keep the most recent system data version reported by the cloud."""
        if (parsed := parse_datetime(version)) is None:
            return
        if self._version is None or parsed > self._version:
            self._version = parsed
            self._version_raw = version

    def _unexpired_cookie_names(self) -> KeysView[str]:
        """Return the names of the unexpired cookies held for the API host.

        Filtering the jar purges expired cookies, so a cookie past its
        expiration time is absent from the returned view.
        """
        return self._session.cookie_jar.filter_cookies(_URL_BASE).keys()

    @property
    def authenticated(self) -> bool:
        """Return whether an unexpired session cookie is held for the API host."""
        return COOKIE_AUTH in self._unexpired_cookie_names()

    @property
    def _session_fresh(self) -> bool:
        """Return whether every cookie required by the cloud is unexpired."""
        return _REQUIRED_COOKIES.issubset(self._unexpired_cookie_names())

    async def async_authenticate(self) -> None:
        """Authenticate with the cloud and store the session cookies.

        Raises MobileKeyAuthenticationError if the credentials are rejected or
        no session cookie is issued, MobileKeyConnectionError otherwise.
        """
        async with self._auth_lock:
            if (
                self._authenticated_at is not None
                and time.monotonic() - self._authenticated_at < _AUTH_GRACE_PERIOD
                and self.authenticated
            ):
                # Trust a session freshly obtained by a concurrent caller:
                # repeating the login immediately would not yield different
                # cookies, and a Cloudflare cookie still missing here is
                # reissued by upcoming responses anyway.
                return

            response = await self._async_raw_request(
                AUTH_METHOD, ENDPOINT_AUTH, auth=self._basic_auth
            )
            async with response:
                if response.status in _AUTH_FAILED_STATUS:
                    raise MobileKeyAuthenticationError(
                        "Credentials rejected by the MobileKey cloud"
                    )
                if response.status != HTTPStatus.OK:
                    raise MobileKeyConnectionError(
                        f"Unexpected HTTP {response.status} from authentication"
                        f" endpoint: {await _error_body_excerpt(response)}"
                    )
            if not self.authenticated:
                raise MobileKeyAuthenticationError(
                    "No session cookie issued by the authentication endpoint"
                )

            self._authenticated_at = time.monotonic()
            _LOGGER.debug(
                "Authentication successful, cookies in jar: %s",
                sorted({cookie.key for cookie in self._session.cookie_jar}),
            )

    async def async_request(
        self, method: str, url: str, **kwargs: Any
    ) -> ClientResponse:
        """Send an authenticated request, renewing the session once if expired."""
        # Renew the session proactively when a required cookie has expired,
        # e.g. the Cloudflare cookie after a long idle period.
        if not self._session_fresh:
            await self.async_authenticate()

        response = await self._async_raw_request(method, url, **kwargs)
        if response.status not in _AUTH_FAILED_STATUS:
            return response

        # The session cookie was rejected, most likely expired: renew it once.
        _LOGGER.debug("Got HTTP %s from %s, renewing the session", response.status, url)
        response.release()
        await self.async_authenticate()

        response = await self._async_raw_request(method, url, **kwargs)
        if response.status in _AUTH_FAILED_STATUS:
            response.release()
            raise MobileKeyAuthenticationError(
                "Request rejected even after session renewal"
            )
        return response

    @_reports_api_health
    async def async_get_locking_system(self) -> MobileKeyLockingSystem:
        """Fetch the full state of the locking system in a single call."""
        payload = await self._async_request_json(
            hdrs.METH_GET, ENDPOINT_SYSTEM_LOADLOCKING
        )
        # Payloads not matching the documented schema are translated so
        # callers treat them as retryable communication failures.
        try:
            system = MobileKeyLockingSystem.from_api(payload)
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Malformed locking system payload: %s", payload)
            raise MobileKeyConnectionError(
                f"Malformed locking system payload: {err!r}"
            ) from err
        self._track_version(payload["version"])
        return system

    @_reports_api_health
    async def async_open_lock(self, lock_id: int) -> None:
        """Ask the cloud to remotely open the given lock."""
        await self._async_perform_request(_DTO_REQUEST_LOCK_OPEN, {"lockID": lock_id})

    @_reports_api_health
    async def async_read_audit_trail(self, lock_id: int) -> None:
        """Ask the cloud to read out the audit trail of the given lock."""
        await self._async_perform_request(
            _DTO_REQUEST_AUDITTRAIL_READ, {"lockID": lock_id}
        )

    @_reports_api_health
    async def async_list_key4friends(self) -> tuple[MobileKeyKey4Friends, ...]:
        """Fetch the Key4Friends keys of the locking system.

        The locking system state must have been loaded first: the request
        echoes its version and the returned authorizations reference its
        locks.
        """
        payload = await self._async_perform_request(_DTO_REQUEST_KEY4FRIENDS_LIST)
        try:
            return tuple(map(MobileKeyKey4Friends.from_api, payload["keys"]))
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Malformed Key4Friends list payload: %s", payload)
            raise MobileKeyConnectionError(
                f"Malformed Key4Friends list payload: {err!r}"
            ) from err

    @_reports_api_health
    async def async_create_key4friends(
        self, key: MobileKeyKey4Friends
    ) -> MobileKeyKey4Friends:
        """Create a Key4Friends key and return it with its cloud-assigned ID."""
        payload = await self._async_perform_request(
            _DTO_REQUEST_KEY4FRIENDS_CREATE,
            {
                "name": key.name,
                "email": key.email,
                "language": key.language,
                "expirationSettings": _key4friends_expiration(key),
                "authorizations": [
                    {"lockID": authorization.lock_id, "name": authorization.name}
                    for authorization in key.authorizations
                ],
            },
        )
        try:
            return replace(key, id=payload["key4FriendsID"])
        except (KeyError, TypeError) as err:
            _LOGGER.debug("Malformed Key4Friends creation payload: %s", payload)
            raise MobileKeyConnectionError(
                f"Malformed Key4Friends creation payload: {err!r}"
            ) from err

    @_reports_api_health
    async def async_update_key4friends(self, key: MobileKeyKey4Friends) -> None:
        """Update the name, language, validity and authorizations of a key.

        The e-mail address of an existing key cannot be changed. The
        silent flag is always sent as false, as the mobile application
        does, so the guest is notified of the change.
        """
        await self._async_perform_request(
            _DTO_REQUEST_KEY4FRIENDS_UPDATE,
            {
                "key4FriendsID": key.id,
                "name": key.name,
                "language": key.language,
                "expirationSettings": _key4friends_expiration(key),
                "authorizations": [
                    {
                        "lockID": authorization.lock_id,
                        "name": authorization.name,
                        "notes": authorization.notes,
                    }
                    for authorization in key.authorizations
                ],
                "silent": False,
            },
        )

    @_reports_api_health
    async def async_delete_key4friends(self, key4friends_id: int) -> None:
        """Delete the given Key4Friends key.

        The silent flag is always sent as false, as the mobile application
        does, so the guest is notified of the deletion.
        """
        await self._async_perform_request(
            _DTO_REQUEST_KEY4FRIENDS_DELETE,
            {"key4FriendsID": key4friends_id, "silent": False},
        )

    async def _async_perform_request(
        self, request_type: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        """Submit a command to the perform-request endpoint.

        The request body leads with the ``$type`` discriminator: the
        cloud deserializer resolves the concrete request DTO from
        metadata properties placed at the start of the JSON object only,
        and rejects commands whose discriminator appears later.
        Every command echoes the version string of the last known system
        state, as the mobile application does, and therefore requires the
        locking system to have been loaded at least once.
        A succeeding command always answers with a response DTO, e.g.
        ``OkResponse`` or ``ListKey4FriendsResponse``, whose ``version``
        field reports the resulting system data version; only the most
        recent version is kept, so concurrent calls completing out of
        order never regress it. Lock commands are queued by the cloud and
        only acknowledged once the SmartBridge has relayed them over the
        radio, hence the extended timeout.
        """
        if (version := self._version_raw) is None:
            raise MobileKeyError(
                "The locking system state must be loaded before sending commands"
            )
        _LOGGER.debug("Performing request %s", request_type)
        response_payload = await self._async_request_json(
            hdrs.METH_POST,
            ENDPOINT_PERFORMREQUEST,
            json={"$type": request_type, "version": version, **(payload or {})},
            timeout=_TIMEOUT_COMMAND,
        )
        if not isinstance(response_payload, Mapping) or not (
            (response_type := dto_type(response_payload)).startswith(
                _DTO_RESPONSE_PREFIX
            )
            and response_type.endswith(_DTO_RESPONSE_SUFFIX)
        ):
            _LOGGER.debug("Unexpected perform-request response: %s", response_payload)
            raise MobileKeyConnectionError(
                f"Unexpected response to {request_type} from the perform-request"
                " endpoint"
            )
        self._track_version(response_payload.get("version"))
        return response_payload

    async def _async_request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Send an authenticated request and return the decoded JSON body."""
        response = await self.async_request(method, url, **kwargs)
        async with response:
            if response.status != HTTPStatus.OK:
                raise MobileKeyConnectionError(
                    f"Unexpected HTTP {response.status} from {url}:"
                    f" {await _error_body_excerpt(response)}"
                )
            try:
                return await response.json()
            except (TimeoutError, ClientError, ValueError) as err:
                raise MobileKeyConnectionError(f"Invalid JSON body from {url}") from err

    async def _async_raw_request(
        self, method: str, url: str, **kwargs: Any
    ) -> ClientResponse:
        """Send a request, translating transport failures into client errors."""
        # Caller-supplied headers are merged over the defaults.
        kwargs["headers"] = {**self._headers, **kwargs.get("headers", {})}
        kwargs.setdefault("timeout", _TIMEOUT_REQUEST)
        try:
            response = await self._session.request(method, url, **kwargs)
        except TimeoutError as err:
            raise MobileKeyConnectionError(
                f"Timeout while contacting the MobileKey cloud at {url}"
            ) from err
        except ClientError as err:
            raise MobileKeyConnectionError(
                f"Communication error with the MobileKey cloud at {url}: {err}"
            ) from err
        _LOGGER.debug("%s %s -> HTTP %s", method, url, response.status)
        return response
