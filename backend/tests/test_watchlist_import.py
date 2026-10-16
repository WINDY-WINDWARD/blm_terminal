"""Unit and integration tests for TradingView Watchlist Import."""

import json
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user
from app.database import Base, get_db
from app.models.user import User
from app.models.stockuniverse import StockUniverse
from app.models.watchlist import Watchlist as WatchlistModel
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.routers.watchlist import (
    router as watchlist_router,
    _parse_tradingview_html,
    _extract_tv_json_symbols_and_name,
)


CANONICAL_TV_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Canonical Watchlist — TradingView</title>
    <script type="application/prs.init-data+json">
    {
        "name": "Canonical Watchlist",
        "symbols": [
            "NSE:IDBI",
            "NSE:TMPV",
            "NSE:IDFCFIRSTB",
            "NSE:RELIANCE",
            "NSE:HDFCBANK",
            "NSE:ICICIBANK",
            "NSE:WAAREEENER",
            "NSE:ADANIENT"
        ]
    }
    </script>
</head>
<body>
    <div>TradingView Watchlist Page</div>
</body>
</html>"""


CANONICAL_NESTED_TV_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Sectors & Trends | TradingView</title>
    <script type="application/prs.init-data+json">
    {
        "watchlist": {
            "name": "Sectors & Trends",
            "items": [
                {"symbol": "NSE:RELIANCE"},
                {"symbol": "NSE:TCS"},
                {"symbol": "BSE:500325"}
            ]
        }
    }
    </script>
</head>
<body></body>
</html>"""


def test_parse_tradingview_html_canonical():
    name, symbols = _parse_tradingview_html(CANONICAL_TV_HTML)
    assert name == "Canonical Watchlist"
    assert symbols == [
        "NSE:IDBI",
        "NSE:TMPV",
        "NSE:IDFCFIRSTB",
        "NSE:RELIANCE",
        "NSE:HDFCBANK",
        "NSE:ICICIBANK",
        "NSE:WAAREEENER",
        "NSE:ADANIENT",
    ]


def test_parse_tradingview_html_nested_and_title_cleanup():
    name, symbols = _parse_tradingview_html(CANONICAL_NESTED_TV_HTML)
    assert name == "Sectors & Trends"
    assert symbols == ["NSE:RELIANCE", "NSE:TCS", "BSE:500325"]


def test_parse_tradingview_html_regex_fallback():
    html_no_json = """
    <html>
        <head><title>Fallback Watchlist — TradingView</title></head>
        <body>
            <div data-ticker="NSE:RELIANCE">Reliance</div>
            <div data-ticker="NSE:HDFCBANK">HDFC</div>
        </body>
    </html>
    """
    name, symbols = _parse_tradingview_html(html_no_json)
    assert name == "Fallback Watchlist"
    assert "NSE:RELIANCE" in symbols
    assert "NSE:HDFCBANK" in symbols


# ───────────────────────────────────────────────────────────────────────────
# Endpoints Integration Tests (TestClient + In-Memory SQLite)
# ───────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_enqueue(monkeypatch):
    import app.routers.watchlist as wl_module

    async def _inline_enqueue(prio, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(wl_module, "enqueue_write_async", _inline_enqueue)


@pytest.fixture
async def test_env(mock_enqueue, monkeypatch):
    from sqlalchemy.pool import StaticPool
    import uuid

    # Unique shared memory URI per test
    db_id = uuid.uuid4().hex
    sync_uri = f"sqlite:///file:{db_id}?mode=memory&cache=shared&uri=true"
    async_uri = f"sqlite+aiosqlite:///file:{db_id}?mode=memory&cache=shared&uri=true"

    sync_engine = sa.create_engine(
        sync_uri,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(sync_engine)

    engine = create_async_engine(
        async_uri,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Base.metadata.create_all(sync_engine)

    # Patch _SyncSessionLocal to use our sync in-memory engine
    TestSyncSession = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    import app.routers.watchlist as wl_module
    monkeypatch.setattr(wl_module, "_SyncSessionLocal", TestSyncSession)

    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    # Seed User and StockUniverse
    canonical_symbols = [
        "IDBI", "TMPV", "IDFCFIRSTB", "RELIANCE",
        "HDFCBANK", "ICICIBANK", "WAAREEENER", "ADANIENT",
        "TCS", "INFY", "BAJAJ-AUTO"
    ]

    # Seed once into the shared test DB
    with TestSyncSession() as ssession:
        user_sync = User(id=1, username="testuser", hashed_password="pw", is_admin=False)
        ssession.add(user_sync)
        for s in canonical_symbols:
            stk_sync = StockUniverse(
                symbol=s,
                company_name=f"{s} LTD",
                segment="EQUITY",
                industry="TEST",
                industry_info={},
                ticker_failure_count=0,
            )
            ssession.add(stk_sync)
        ssession.commit()

    app = FastAPI()
    app.include_router(watchlist_router, prefix="/api")

    async def _override_get_db():
        async with AsyncSessionLocal() as session:
            yield session

    async def _override_get_current_user():
        return User(id=1, username="testuser", hashed_password="pw", is_admin=False)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    client = TestClient(app)
    yield client, TestSyncSession

    await engine.dispose()


class TestWatchlistImportEndpoints:
    def test_import_url_invalid_domain(self, test_env):
        client, _ = test_env
        resp = client.post("/api/watchlists/import-url", json={"url": "https://google.com/watchlists/123"})
        assert resp.status_code == 400
        assert "Only TradingView URLs" in resp.json()["detail"]

    def test_import_url_non_watchlist_path(self, test_env):
        client, _ = test_env
        resp = client.post("/api/watchlists/import-url", json={"url": "https://in.tradingview.com/chart/abc"})
        assert resp.status_code == 400
        assert "Must be a shared watchlist link" in resp.json()["detail"]

    def test_import_url_mocked_success(self, test_env, monkeypatch):
        client, _ = test_env

        class MockResponse:
            status_code = 200
            text = CANONICAL_TV_HTML

        class MockAsyncClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, url):
                return MockResponse()

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockAsyncClient())

        resp = client.post(
            "/api/watchlists/import-url",
            json={"url": "https://in.tradingview.com/watchlists/115430006/"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_name"] == "Canonical Watchlist"
        assert len(data["raw_symbols"]) == 8
        assert "NSE:IDBI" in data["raw_symbols"]
        assert "NSE:RELIANCE" in data["raw_symbols"]

    def test_import_create_flat_mode(self, test_env):
        client, _ = test_env
        payload = {
            "base_name": "My Canonical List",
            "mode": "create",
            "split_sections": False,
            "sections": [
                {
                    "name": "DEFAULT",
                    "items": [
                        {"symbol": "IDBI", "exchange": "NSE"},
                        {"symbol": "TMPV", "exchange": "NSE"},
                        {"symbol": "RELIANCE", "exchange": "NSE"},
                        {"symbol": "500325", "exchange": "BSE"},  # Unsupported exchange
                        {"symbol": "UNKNOWN123", "exchange": "NSE"},  # Not in universe
                    ],
                }
            ],
        }
        resp = client.post("/api/watchlists/import", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total_imported"] == 3
        assert len(data["created_watchlists"]) == 1
        assert data["created_watchlists"][0]["name"] == "My Canonical List"

        # Check skipped items
        skipped = {s["symbol"]: s["reason"] for s in data["skipped_symbols"]}
        assert "500325" in skipped
        assert "Unsupported exchange" in skipped["500325"]
        assert "UNKNOWN123" in skipped
        assert "not found in NSE universe" in skipped["UNKNOWN123"]

    def test_import_create_split_sections_mode(self, test_env):
        client, _ = test_env
        payload = {
            "base_name": "Sector Watch",
            "mode": "create",
            "split_sections": True,
            "sections": [
                {
                    "name": "Banking",
                    "items": [
                        {"symbol": "HDFCBANK", "exchange": "NSE"},
                        {"symbol": "ICICIBANK", "exchange": "NSE"},
                    ],
                },
                {
                    "name": "Auto & Energy",
                    "items": [
                        {"symbol": "BAJAJ-AUTO", "exchange": "NSE"},
                        {"symbol": "WAAREEENER", "exchange": "NSE"},
                    ],
                },
            ],
        }
        resp = client.post("/api/watchlists/import", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total_imported"] == 4
        assert len(data["created_watchlists"]) == 2
        names = [w["name"] for w in data["created_watchlists"]]
        assert "Sector Watch - Banking" in names
        assert "Sector Watch - Auto  Energy" in names or any("Auto" in n for n in names)

    def test_import_append_and_replace_modes(self, test_env):
        client, SyncSession = test_env

        # Create target watchlist in sync DB
        target_id = None
        with SyncSession() as session:
            target_wl = WatchlistModel(name="Existing List", user_id=1)
            session.add(target_wl)
            session.commit()
            session.refresh(target_wl)
            target_id = target_wl.id

            # Add initial item TCS
            item = WatchlistItemModel(watchlist_id=target_id, symbol="TCS", exchange="NSE")
            session.add(item)
            session.commit()

        # 1. Append mode
        append_payload = {
            "base_name": "Ignored In Append",
            "mode": "append",
            "target_watchlist_id": target_id,
            "sections": [
                {
                    "name": "DEFAULT",
                    "items": [
                        {"symbol": "TCS", "exchange": "NSE"},  # Already exists, should not duplicate
                        {"symbol": "INFY", "exchange": "NSE"}, # New
                    ],
                }
            ],
        }
        resp_app = client.post("/api/watchlists/import", json=append_payload)
        assert resp_app.status_code == 200
        assert resp_app.json()["total_imported"] == 1  # Only INFY added

        # 2. Replace mode
        replace_payload = {
            "base_name": "Ignored In Replace",
            "mode": "replace",
            "target_watchlist_id": target_id,
            "sections": [
                {
                    "name": "DEFAULT",
                    "items": [
                        {"symbol": "RELIANCE", "exchange": "NSE"},
                        {"symbol": "ADANIENT", "exchange": "NSE"},
                    ],
                }
            ],
        }
        resp_rep = client.post("/api/watchlists/import", json=replace_payload)
        assert resp_rep.status_code == 200
        assert resp_rep.json()["total_imported"] == 2

        # Verify target watchlist now has only RELIANCE and ADANIENT
        with SyncSession() as session:
            items = session.execute(
                sa.select(WatchlistItemModel.symbol).where(WatchlistItemModel.watchlist_id == target_id)
            ).scalars().all()
            assert set(items) == {"RELIANCE", "ADANIENT"}

    def test_import_url_strict_security(self, test_env):
        client, _ = test_env

        # 1. Reject non-https
        r1 = client.post("/api/watchlists/import-url", json={"url": "http://in.tradingview.com/watchlists/123/"})
        assert r1.status_code == 400
        assert "Scheme must be https" in r1.json()["detail"]

        # 2. Reject credentials
        r2 = client.post("/api/watchlists/import-url", json={"url": "https://user:pass@in.tradingview.com/watchlists/123/"})
        assert r2.status_code == 400
        assert "User credentials" in r2.json()["detail"]

        # 3. Reject non-default port
        r3 = client.post("/api/watchlists/import-url", json={"url": "https://in.tradingview.com:8443/watchlists/123/"})
        assert r3.status_code == 400
        assert "Non-default ports" in r3.json()["detail"]

        # 4. Reject unauthorized domain
        r4 = client.post("/api/watchlists/import-url", json={"url": "https://attacker-tradingview.com/watchlists/123/"})
        assert r4.status_code == 400
        assert "Only TradingView URLs" in r4.json()["detail"]

    def test_import_url_redirect_handling(self, test_env, monkeypatch):
        client, _ = test_env
        import httpx

        # Scenario A: Valid redirect chain (1 hop)
        class MockRedirectClientA:
            def __init__(self):
                self.calls = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, url):
                self.calls.append(url)
                if url == "https://tradingview.com/watchlists/115430006/":
                    resp = httpx.Response(301, headers={"Location": "https://in.tradingview.com/watchlists/115430006/"})
                    return resp
                return httpx.Response(200, text=CANONICAL_TV_HTML)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockRedirectClientA())
        resp_a = client.post("/api/watchlists/import-url", json={"url": "https://tradingview.com/watchlists/115430006/"})
        assert resp_a.status_code == 200
        assert resp_a.json()["source_name"] == "Canonical Watchlist"

        # Scenario B: Disallowed redirect destination (e.g. to external domain)
        class MockRedirectClientB:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, url):
                return httpx.Response(302, headers={"Location": "https://evil.com/watchlists/bad"})

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockRedirectClientB())
        resp_b = client.post("/api/watchlists/import-url", json={"url": "https://in.tradingview.com/watchlists/115430006/"})
        assert resp_b.status_code == 502
        assert "Disallowed redirect location" in resp_b.json()["detail"]

        # Scenario C: Excessive redirects (>3 hops)
        class MockRedirectClientC:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, url):
                return httpx.Response(301, headers={"Location": "https://in.tradingview.com/watchlists/115430006/"})

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockRedirectClientC())
        resp_c = client.post("/api/watchlists/import-url", json={"url": "https://in.tradingview.com/watchlists/115430006/"})
        assert resp_c.status_code == 502
        assert "exceeded maximum allowed redirects" in resp_c.json()["detail"]

    def test_import_zero_valid_symbols_returns_400(self, test_env):
        client, _ = test_env
        payload = {
            "base_name": "Zero Valid",
            "mode": "create",
            "split_sections": False,
            "sections": [
                {
                    "name": "DEFAULT",
                    "items": [
                        {"symbol": "500325", "exchange": "BSE"},
                        {"symbol": "NONEXISTENT999", "exchange": "NSE"},
                    ],
                }
            ],
        }
        resp = client.post("/api/watchlists/import", json=payload)
        assert resp.status_code == 400
        assert "No valid symbols to import" in resp.json()["detail"]

    def test_import_append_duplicate_and_capacity_cap(self, test_env):
        client, SyncSession = test_env
        target_id = None

        with SyncSession() as session:
            wl = WatchlistModel(name="Cap List", user_id=1)
            session.add(wl)
            session.commit()
            session.refresh(wl)
            target_id = wl.id

            # Seed 998 dummy symbols to leave 2 spaces remaining
            for idx in range(998):
                session.add(WatchlistItemModel(watchlist_id=target_id, symbol=f"SYM{idx}", exchange="NSE"))
            # Also add TCS
            session.add(WatchlistItemModel(watchlist_id=target_id, symbol="TCS", exchange="NSE"))
            session.commit()

        # At this point, target has 999 items -> exactly 1 space left
        # Attempt to append:
        # - TCS (already in target -> should be skipped with "Already in target watchlist")
        # - RELIANCE (takes the 1 remaining space)
        # - INFY (capacity reached -> skipped with "Watchlist capacity reached (1000)")
        payload = {
            "base_name": "Append Cap",
            "mode": "append",
            "target_watchlist_id": target_id,
            "sections": [
                {
                    "name": "DEFAULT",
                    "items": [
                        {"symbol": "TCS", "exchange": "NSE"},
                        {"symbol": "RELIANCE", "exchange": "NSE"},
                        {"symbol": "INFY", "exchange": "NSE"},
                    ],
                }
            ],
        }
        resp = client.post("/api/watchlists/import", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_imported"] == 1

        skipped = {s["symbol"]: s["reason"] for s in data["skipped_symbols"]}
        assert "TCS" in skipped
        assert "Already in target watchlist" in skipped["TCS"]
        assert "INFY" in skipped
        assert "Watchlist capacity reached" in skipped["INFY"]

    def test_import_split_sections_independent_duplicates(self, test_env):
        client, _ = test_env
        payload = {
            "base_name": "Multi Sec",
            "mode": "create",
            "split_sections": True,
            "sections": [
                {
                    "name": "Sec1",
                    "items": [
                        {"symbol": "RELIANCE", "exchange": "NSE"},
                        {"symbol": "RELIANCE", "exchange": "NSE"},  # Duplicate within Sec1
                    ],
                },
                {
                    "name": "Sec2",
                    "items": [
                        {"symbol": "RELIANCE", "exchange": "NSE"},  # Permitted in Sec2 because split
                        {"symbol": "TCS", "exchange": "NSE"},
                    ],
                },
            ],
        }
        resp = client.post("/api/watchlists/import", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_imported"] == 3  # RELIANCE (Sec1), RELIANCE (Sec2), TCS (Sec2)
        assert len(data["created_watchlists"]) == 2

        # Verify duplicate within Sec1 was skipped
        skipped = [s for s in data["skipped_symbols"] if s["symbol"] == "RELIANCE"]
        assert len(skipped) == 1
        assert "Duplicate symbol in destination" in skipped[0]["reason"]

    def test_split_sections_forbidden_in_append_mode(self, test_env):
        client, _ = test_env
        payload = {
            "base_name": "Test",
            "mode": "append",
            "split_sections": True,
            "target_watchlist_id": 1,
            "sections": [{"name": "SEC", "items": [{"symbol": "TCS", "exchange": "NSE"}]}],
        }
        resp = client.post("/api/watchlists/import", json=payload)
        assert resp.status_code == 400
        assert "split_sections is only supported" in resp.json()["detail"]


@pytest.mark.slow
def test_live_canonical_url():
    """Optional live test verifying the real TradingView shared link fixture."""
    import httpx
    url = "https://in.tradingview.com/watchlists/115430006/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
    assert resp.status_code == 200
    name, symbols = _parse_tradingview_html(resp.text)
    assert len(symbols) >= 8
    expected = {"NSE:IDBI", "NSE:TMPV", "NSE:IDFCFIRSTB", "NSE:RELIANCE", "NSE:HDFCBANK", "NSE:ICICIBANK", "NSE:WAAREEENER", "NSE:ADANIENT"}
    assert expected.issubset(set(symbols))
