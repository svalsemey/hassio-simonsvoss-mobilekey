"""MobileKey cloud API client."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_AUTH_ENDPOINT,
    API_BASE_URL,
    API_LOCK_CONTROL_ENDPOINT,
    API_LOCKS_ENDPOINT,
    API_SMARTBRIDGES_ENDPOINT,
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNKNOWN,
    LOCK_STATE_UNLOCKED,
)

_LOGGER = logging.getLogger(__name__)


class MobileKeyAuthError(Exception):
    """Raised when authentication fails."""


class MobileKeyConnectionError(Exception):
    """Raised when unable to connect to the MobileKey API."""


class MobileKeyApiClient:
    """Client for the SimonsVoss MobileKey cloud API."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._token: str | None = None

    async def authenticate(self) -> str:
        """Authenticate with the MobileKey API and return the access token."""
        try:
            async with self._session.post(
                f"{API_BASE_URL}{API_AUTH_ENDPOINT}",
                json={"username": self._username, "password": self._password},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    raise MobileKeyAuthError("Invalid credentials")
                if response.status != 200:
                    raise MobileKeyConnectionError(
                        f"Unexpected status code: {response.status}"
                    )
                try:
                    data = await response.json()
                    self._token = data["token"]
                except (KeyError, aiohttp.ContentTypeError) as err:
                    raise MobileKeyConnectionError(
                        f"Unexpected response format: {err}"
                    ) from err
                return self._token
        except aiohttp.ClientError as err:
            raise MobileKeyConnectionError(f"Connection error: {err}") from err

    async def _get_headers(self) -> dict[str, str]:
        """Return authorization headers, re-authenticating if needed."""
        if self._token is None:
            await self.authenticate()
        return {"Authorization": f"Bearer {self._token}"}

    async def get_smartbridges(self) -> list[dict[str, Any]]:
        """Retrieve all SmartBridges associated with the account."""
        try:
            headers = await self._get_headers()
            async with self._session.get(
                f"{API_BASE_URL}{API_SMARTBRIDGES_ENDPOINT}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    self._token = None
                    raise MobileKeyAuthError("Token expired or invalid")
                if response.status != 200:
                    raise MobileKeyConnectionError(
                        f"Unexpected status code: {response.status}"
                    )
                return await response.json()
        except aiohttp.ClientError as err:
            raise MobileKeyConnectionError(f"Connection error: {err}") from err

    async def get_locks(self, smartbridge_id: str) -> list[dict[str, Any]]:
        """Retrieve all locks for a given SmartBridge."""
        try:
            headers = await self._get_headers()
            url = f"{API_BASE_URL}{API_LOCKS_ENDPOINT.format(smartbridge_id=smartbridge_id)}"
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    self._token = None
                    raise MobileKeyAuthError("Token expired or invalid")
                if response.status != 200:
                    raise MobileKeyConnectionError(
                        f"Unexpected status code: {response.status}"
                    )
                return await response.json()
        except aiohttp.ClientError as err:
            raise MobileKeyConnectionError(f"Connection error: {err}") from err

    async def lock(self, smartbridge_id: str, lock_id: str) -> None:
        """Lock the specified lock."""
        await self._set_lock_state(smartbridge_id, lock_id, LOCK_STATE_LOCKED)

    async def unlock(self, smartbridge_id: str, lock_id: str) -> None:
        """Unlock the specified lock."""
        await self._set_lock_state(smartbridge_id, lock_id, LOCK_STATE_UNLOCKED)

    async def _set_lock_state(
        self, smartbridge_id: str, lock_id: str, state: str
    ) -> None:
        """Send a lock/unlock command to the API."""
        try:
            headers = await self._get_headers()
            url = f"{API_BASE_URL}{API_LOCK_CONTROL_ENDPOINT.format(smartbridge_id=smartbridge_id, lock_id=lock_id)}"
            async with self._session.patch(
                url,
                headers=headers,
                json={"state": state},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    self._token = None
                    raise MobileKeyAuthError("Token expired or invalid")
                if response.status not in (200, 204):
                    raise MobileKeyConnectionError(
                        f"Unexpected status code: {response.status}"
                    )
        except aiohttp.ClientError as err:
            raise MobileKeyConnectionError(f"Connection error: {err}") from err

    @staticmethod
    def parse_lock_state(raw_state: str | None) -> str:
        """Normalize the lock state string from the API."""
        if raw_state == LOCK_STATE_LOCKED:
            return LOCK_STATE_LOCKED
        if raw_state == LOCK_STATE_UNLOCKED:
            return LOCK_STATE_UNLOCKED
        return LOCK_STATE_UNKNOWN
