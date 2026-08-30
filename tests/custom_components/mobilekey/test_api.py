"""Tests for the MobileKey API client."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
import sys
import types

# ---------------------------------------------------------------------------
# Stub out homeassistant so that importing the custom component works without
# a full Home Assistant installation.
# ---------------------------------------------------------------------------
for _mod in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.components",
    "homeassistant.components.lock",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# Minimal stubs for symbols used during import
_ha = sys.modules["homeassistant"]
_const = sys.modules["homeassistant.const"]
_const.CONF_USERNAME = "username"
_const.CONF_PASSWORD = "password"
_const.Platform = types.SimpleNamespace(LOCK="lock")

_ce = sys.modules["homeassistant.config_entries"]
_ce.ConfigEntry = object
_ce.ConfigFlow = object

_lock = sys.modules["homeassistant.components.lock"]
_lock.LockEntity = object
_lock.LockEntityFeature = types.SimpleNamespace()

_exc = sys.modules["homeassistant.exceptions"]
_exc.ConfigEntryNotReady = Exception
_exc.ConfigEntryAuthFailed = Exception

_coord = sys.modules["homeassistant.helpers.update_coordinator"]
class _GenericBase:
    def __class_getitem__(cls, item):
        return cls

_coord.DataUpdateCoordinator = _GenericBase
_coord.UpdateFailed = Exception
_coord.CoordinatorEntity = _GenericBase

_entity = sys.modules["homeassistant.helpers.entity"]
_entity.DeviceInfo = dict

_ep = sys.modules["homeassistant.helpers.entity_platform"]
_ep.AddEntitiesCallback = None

_ahttp = sys.modules["homeassistant.helpers.aiohttp_client"]
_ahttp.async_get_clientsession = MagicMock()

# Additional stubs needed by __init__.py imports
_core = sys.modules["homeassistant.core"]
_core.HomeAssistant = object
_core.callback = lambda f: f

_ce.ConfigEntry = object

class _FakeConfigFlow:
    pass

_ce.ConfigFlow = _FakeConfigFlow
_ce.FlowResult = dict

import os
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from custom_components.mobilekey.api import (  # noqa: E402
    MobileKeyApiClient,
    MobileKeyAuthError,
    MobileKeyConnectionError,
)
from custom_components.mobilekey.const import (  # noqa: E402
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNKNOWN,
    LOCK_STATE_UNLOCKED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status: int, json_data=None) -> MagicMock:
    """Create a mock aiohttp response context manager."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data or {})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


@pytest.fixture
def mock_session():
    """Return a mock aiohttp ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def client(mock_session):
    """Return a MobileKeyApiClient backed by a mock session."""
    return MobileKeyApiClient(
        username="user@example.com",
        password="testpass",
        session=mock_session,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthenticate:
    async def test_successful_auth(self, client, mock_session):
        mock_session.post.return_value = _make_response(200, {"token": "tok123"})
        token = await client.authenticate()
        assert token == "tok123"
        assert client._token == "tok123"

    async def test_invalid_credentials_raises(self, client, mock_session):
        mock_session.post.return_value = _make_response(401)
        with pytest.raises(MobileKeyAuthError):
            await client.authenticate()

    async def test_connection_error_raises(self, client, mock_session):
        mock_session.post.side_effect = aiohttp.ClientError("network down")
        with pytest.raises(MobileKeyConnectionError):
            await client.authenticate()

    async def test_unexpected_status_raises(self, client, mock_session):
        mock_session.post.return_value = _make_response(503)
        with pytest.raises(MobileKeyConnectionError):
            await client.authenticate()


class TestGetSmartbridges:
    async def test_returns_list(self, client, mock_session):
        client._token = "tok"
        mock_session.get.return_value = _make_response(
            200, [{"id": "sb1", "name": "Bridge 1"}, {"id": "sb2", "name": "Bridge 2"}]
        )
        result = await client.get_smartbridges()
        assert len(result) == 2
        assert result[0]["id"] == "sb1"

    async def test_expired_token_raises(self, client, mock_session):
        client._token = "tok"
        mock_session.get.return_value = _make_response(401)
        with pytest.raises(MobileKeyAuthError):
            await client.get_smartbridges()
        assert client._token is None


class TestGetLocks:
    async def test_returns_locks(self, client, mock_session):
        client._token = "tok"
        mock_session.get.return_value = _make_response(
            200,
            [
                {"id": "l1", "name": "Front Door", "state": "locked"},
                {"id": "l2", "name": "Back Door", "state": "unlocked"},
            ],
        )
        result = await client.get_locks("sb1")
        assert len(result) == 2
        assert result[0]["state"] == LOCK_STATE_LOCKED

    async def test_connection_error_raises(self, client, mock_session):
        client._token = "tok"
        mock_session.get.side_effect = aiohttp.ClientError("fail")
        with pytest.raises(MobileKeyConnectionError):
            await client.get_locks("sb1")


class TestLockUnlock:
    async def test_lock_sends_locked_state(self, client, mock_session):
        client._token = "tok"
        mock_session.patch.return_value = _make_response(200)
        await client.lock("sb1", "l1")
        call_kwargs = mock_session.patch.call_args
        assert call_kwargs.kwargs["json"]["state"] == LOCK_STATE_LOCKED

    async def test_unlock_sends_unlocked_state(self, client, mock_session):
        client._token = "tok"
        mock_session.patch.return_value = _make_response(200)
        await client.unlock("sb1", "l1")
        call_kwargs = mock_session.patch.call_args
        assert call_kwargs.kwargs["json"]["state"] == LOCK_STATE_UNLOCKED

    async def test_lock_connection_error_raises(self, client, mock_session):
        client._token = "tok"
        mock_session.patch.side_effect = aiohttp.ClientError("fail")
        with pytest.raises(MobileKeyConnectionError):
            await client.lock("sb1", "l1")


class TestParseLockState:
    def test_locked(self):
        assert MobileKeyApiClient.parse_lock_state("locked") == LOCK_STATE_LOCKED

    def test_unlocked(self):
        assert MobileKeyApiClient.parse_lock_state("unlocked") == LOCK_STATE_UNLOCKED

    def test_none_returns_unknown(self):
        assert MobileKeyApiClient.parse_lock_state(None) == LOCK_STATE_UNKNOWN

    def test_garbage_returns_unknown(self):
        assert MobileKeyApiClient.parse_lock_state("junk") == LOCK_STATE_UNKNOWN
