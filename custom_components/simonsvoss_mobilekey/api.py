"""Asynchronous client for the SimonsVoss MobileKey cloud service."""

import asyncio
from http import HTTPStatus
import logging
import time
from typing import TYPE_CHECKING, Any, Final

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
    API_BASE_URL,
    AUTH_COOKIE,
    AUTH_ENDPOINT,
    AUTH_METHOD,
    CF_BM_COOKIE,
    LOAD_LOCKING_SYSTEM_ENDPOINT,
    USER_AGENT,
)
from .models import MobileKeyLockingSystem

if TYPE_CHECKING:
    from collections.abc import KeysView

_LOGGER = logging.getLogger(__name__)

_BASE_URL: Final = URL(API_BASE_URL)

# Overall timeout applied to every request, including reading the body.
_REQUEST_TIMEOUT: Final = ClientTimeout(total=30)

# Period during which a freshly obtained session is trusted, so concurrent
# callers hitting an expired session do not trigger redundant logins.
_AUTH_GRACE_PERIOD: Final = 5.0

# HTTP statuses indicating a missing, expired or revoked session.
_AUTH_FAILED_STATUS: Final = frozenset({HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN})

# Cookies that must all be unexpired for requests to be accepted by the
# cloud: the session cookie and the Cloudflare bot-management cookie,
# which is issued with a lifetime of roughly thirty minutes.
_REQUIRED_COOKIES: Final = frozenset({AUTH_COOKIE, CF_BM_COOKIE})

# Headers sent with every request to the cloud, mirroring those of the
# MobileKey mobile application. Callers may override any of them.
_DEFAULT_HEADERS: Final[dict[str, str]] = {
    hdrs.USER_AGENT: USER_AGENT,
    hdrs.ACCEPT: "application/json",
    hdrs.CONTENT_TYPE: "application/json",
    hdrs.ACCEPT_ENCODING: "gzip, deflate, br",
    hdrs.CONNECTION: "keep-alive",
}


class MobileKeyError(Exception):
    """Base exception for all MobileKey client errors."""


class MobileKeyConnectionError(MobileKeyError):
    """Raised when the MobileKey cloud cannot be reached."""


class MobileKeyAuthenticationError(MobileKeyError):
    """Raised when the MobileKey cloud rejects the credentials or session."""


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
    """

    def __init__(self, username: str, password: str, session: ClientSession) -> None:
        """Initialize the client with account credentials and an HTTP session."""
        self._basic_auth = BasicAuth(username, password)
        self._session = session
        self._auth_lock = asyncio.Lock()
        self._authenticated_at: float | None = None

    def _unexpired_cookie_names(self) -> KeysView[str]:
        """Return the names of the unexpired cookies held for the API host.

        Filtering the jar purges expired cookies, so a cookie past its
        expiration time is absent from the returned view.
        """
        return self._session.cookie_jar.filter_cookies(_BASE_URL).keys()

    @property
    def authenticated(self) -> bool:
        """Return whether an unexpired session cookie is held for the API host."""
        return AUTH_COOKIE in self._unexpired_cookie_names()

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
                AUTH_METHOD, AUTH_ENDPOINT, auth=self._basic_auth
            )
            response.release()

            if response.status in _AUTH_FAILED_STATUS:
                raise MobileKeyAuthenticationError(
                    "Credentials rejected by the MobileKey cloud"
                )
            if response.status != HTTPStatus.OK:
                raise MobileKeyConnectionError(
                    f"Unexpected HTTP {response.status} from authentication endpoint"
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

    async def async_get_locking_system(self) -> MobileKeyLockingSystem:
        """Fetch the full state of the locking system in a single call."""
        # MobileKey client errors from the request helper propagate as-is;
        # only payloads not matching the documented schema are translated,
        # so callers treat them as retryable communication failures.
        try:
            return MobileKeyLockingSystem.from_api(
                await self._async_request_json(
                    hdrs.METH_GET, LOAD_LOCKING_SYSTEM_ENDPOINT
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            raise MobileKeyConnectionError(
                f"Malformed locking system payload: {err!r}"
            ) from err

    async def _async_request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Send an authenticated request and return the decoded JSON body."""
        response = await self.async_request(method, url, **kwargs)
        async with response:
            if response.status != HTTPStatus.OK:
                raise MobileKeyConnectionError(
                    f"Unexpected HTTP {response.status} from {url}"
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
        kwargs["headers"] = {**_DEFAULT_HEADERS, **kwargs.get("headers", {})}
        try:
            return await self._session.request(
                method,
                url,
                timeout=_REQUEST_TIMEOUT,
                **kwargs,
            )
        except TimeoutError as err:
            raise MobileKeyConnectionError(
                "Timeout while contacting the MobileKey cloud"
            ) from err
        except ClientError as err:
            raise MobileKeyConnectionError(
                f"Communication error with the MobileKey cloud: {err}"
            ) from err
