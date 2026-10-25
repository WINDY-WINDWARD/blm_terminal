"""Tests verifying the decomposed OAuthSessionManager behavior for slice P5.

Verifies:
- Unknown state raises KeyError.
- Cancelled session unregisters listener exactly once.
- Expired session unregisters listener and cancels proxy session.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.oauth_session_manager import OAuthSessionManager, PendingOAuthSession


@pytest.mark.asyncio
async def test_unknown_state_raises_key_error():
    """Verify polling an unregistered / unknown state raises KeyError."""
    mgr = OAuthSessionManager()
    with pytest.raises(KeyError) as exc_info:
        await mgr.poll_session(state="non_existent_state_abc123")
    assert "non_existent_state_abc123" in str(exc_info.value)


@pytest.mark.asyncio
async def test_cancelled_session_unregisters_exactly_once():
    """Verify a cancelled session returns cancelled status and unregisters listener."""
    cb_server = MagicMock()
    cb_server.unregister = AsyncMock()
    mgr = OAuthSessionManager(callback_server=cb_server)

    state = "state_cancel_test"
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="cancelled",
    )
    mgr._sessions[state] = session

    res = await mgr.poll_session(state)
    assert res["status"] == "cancelled"
    assert cb_server.unregister.await_count == 1
    cb_server.unregister.assert_awaited_with(state)


@pytest.mark.asyncio
async def test_expiry_cancels_proxy_and_unregisters():
    """Verify an expired session unregisters callback and calls proxy cancel_oauth_session."""
    cb_server = MagicMock()
    cb_server.unregister = AsyncMock()
    mgr = OAuthSessionManager(callback_server=cb_server)

    state = "state_expire_test"
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=time.time() - 1000.0,
        expires_at=time.time() - 10.0,
        status="pending",
    )
    mgr._sessions[state] = session

    mock_supervisor = MagicMock()
    mock_supervisor.is_running = True
    mgmt_client = MagicMock()
    mgmt_client.cancel_oauth_session = AsyncMock()
    mock_supervisor.get_management_client.return_value = mgmt_client

    with patch("app.services.oauth_session_manager.get_proxy_supervisor", return_value=mock_supervisor):
        res = await mgr.poll_session(state)

    assert res["status"] == "expired"
    assert cb_server.unregister.await_count == 1
    cb_server.unregister.assert_awaited_with(state)
    mgmt_client.cancel_oauth_session.assert_awaited_once_with(state)
