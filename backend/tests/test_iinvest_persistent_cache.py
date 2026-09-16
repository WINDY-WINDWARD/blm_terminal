import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from app.services.iinvest_client import IinvestClient

@pytest.mark.asyncio
async def test_iinvest_client_persistent_caching():
    client = IinvestClient()
    client._jwt = "fake-jwt"
    client._jwt_expires_at = datetime.now(timezone.utc) + timedelta(hours=5)
    client._http = MagicMock()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": True, "response": {"items": [1, 2, 3]}}

    get_mock = AsyncMock(return_value=mock_resp)
    client._http.get = get_mock

    # First call - should invoke HTTP get
    res1 = await client.get_announcements("test/path", page=1, size=20)
    assert res1 == {"status": True, "response": {"items": [1, 2, 3]}}
    assert get_mock.call_count == 1

    # Second call with identical params - should be served from SQLite persistent cache
    res2 = await client.get_announcements("test/path", page=1, size=20)
    assert res2 == {"status": True, "response": {"items": [1, 2, 3]}}
    assert get_mock.call_count == 1  # No additional network call!
