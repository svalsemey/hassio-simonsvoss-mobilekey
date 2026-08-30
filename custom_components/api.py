"""Asynchronous client for the SimonsVoss MobileKey cloud service."""

from __future__ import annotations

import asyncio
import logging
import time
from http import HTTPStatus
from typing import Any, Final

from aiohttp import (
    BasicAuth,
    ClientError,
    ClientResponse,
    ClientSession,
    ClientTimeout,
    hdrs,
)
from yarl import URL

from .const import API_BASE_URL, AUTH_COOKIE, AUTH_ENDPOINT, AUTH_METHOD, USER_AGENT

_LOGGER = logging.getLogger(__name__)

_BASE_URL: Final = URL(API_BASE_URL)

# Overall timeout applied to every request, including reading the body.
_REQUEST_TIMEOUT: Final = ClientTimeout(total=30)

# Period during which a freshly obtained session is trusted, so concurrent
# callers hitting an expired session do not trigger redundant logins.
_AUTH_GRACE_PERIOD: Final = 5.0

# HTTP statuses indicating a missing, expired or revoked session.
_AUTH_FAILED_STATUS: Final = frozenset(
    {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
)


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
    and automatically sent back on every subsequent request, mirroring the
    behavior of the official iOS application.
    """

    def __init__(
        self, username: str, password: str, session: ClientSession
    ) -> None:
        """Initialize the client with account credentials and an HTTP session."""
        self._basic_auth = BasicAuth(username, password)
        self._session = session
        self._auth_lock = asyncio.Lock()
        self._authenticated_at: float | None = None

    @property
    def authenticated(self) -> bool:
        """Return whether a session cookie is currently held for the API host."""
        return AUTH_COOKIE in self._session.cookie_jar.filter_cookies(_BASE_URL)

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
                # A concurrent caller just refreshed the session: reuse it.
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
        if not self.authenticated:
            await self.async_authenticate()

        response = await self._async_raw_request(method, url, **kwargs)
        if response.status not in _AUTH_FAILED_STATUS:
            return response

        # The session cookie was rejected, most likely expired: renew it once.
        _LOGGER.debug(
            "Got HTTP %s from %s, renewing the session", response.status, url
        )
        response.release()
        await self.async_authenticate()

        response = await self._async_raw_request(method, url, **kwargs)
        if response.status in _AUTH_FAILED_STATUS:
            response.release()
            raise MobileKeyAuthenticationError(
                "Request rejected even after session renewal"
            )
        return response

    async def _async_raw_request(
        self, method: str, url: str, **kwargs: Any
    ) -> ClientResponse:
        """Send a request, translating transport failures into client errors."""
        try:
            return await self._session.request(
                method,
                url,
                headers={hdrs.USER_AGENT: USER_AGENT},
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
