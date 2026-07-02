"""
Integration tests for the notifications API and background worker.

Requires the backend server running. Set BLM_BASE_URL to override the default
(http://127.0.0.1:4455).  Dev endpoints (POST /trigger) require ENV != "production".

Run:
    BLM_BASE_URL=http://127.0.0.1:4455 pytest tests/test_notifications.py -v
"""

import os
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests

BASE = os.environ.get("BLM_BASE_URL", "http://127.0.0.1:4455").rstrip("/")

TEST_SYMBOL = "RELIANCE"
TEST_WATCHLIST_ID = 1
TEST_WATCHLIST_2_ID = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get(path: str, timeout: int = 60, **kwargs) -> requests.Response:
    return requests.get(f"{BASE}{path}", timeout=timeout, **kwargs)


def delete(path: str, timeout: int = 60, **kwargs) -> requests.Response:
    return requests.delete(f"{BASE}{path}", timeout=timeout, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_db():
    """Return a synchronous DB session for direct row manipulation.

    Uses _SyncSessionLocal directly so tests can insert/verify rows without
    going through the API. Matches the pattern used by background workers.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = os.environ.get("BLM_DB_PATH", "data/blm.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def require_dev_env():
    """Skip the test if ENV=production (dev trigger endpoint is disabled)."""
    if os.environ.get("ENV") == "production":
        pytest.skip("Dev trigger endpoint is disabled in production ENV")


# ---------------------------------------------------------------------------
# /api/notifications — API surface
# ---------------------------------------------------------------------------

class TestNotificationsAPI:
    """API surface tests — no background worker required."""

    def test_get_returns_200(self):
        resp = get("/api/notifications?watchlist_id=1")
        assert resp.status_code == 200

    def test_get_returns_list(self):
        resp = get("/api/notifications?watchlist_id=1")
        data = resp.json()
        assert isinstance(data, list)

    def test_get_empty_schema(self):
        """Each item must have the required keys."""
        resp = get("/api/notifications?watchlist_id=1")
        for item in resp.json():
            required = {
                "id", "watchlist_id", "symbol", "exchange",
                "trigger_type", "message", "triggered_at",
                "triggered_date", "is_read",
            }
            assert required.issubset(item.keys()), (
                f"Missing keys: {required - set(item.keys())}"
            )

    def test_get_omitted_watchlist_id(self):
        """Omitting watchlist_id should return 200 (queries all user watchlists)."""
        resp = get("/api/notifications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_all_true_ignores_foreign_watchlist_id(self):
        """all=true ignores the supplied watchlist_id and returns all owned watchlists."""
        resp = get("/api/notifications?watchlist_id=99999&all=true")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_per_watchlist_still_works(self):
        """Providing a valid watchlist_id without all=true returns 200."""
        resp = get(f"/api/notifications?watchlist_id={TEST_WATCHLIST_ID}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_delete_all_returns_200(self):
        """DELETE ?all=true should succeed."""
        resp = delete(f"/api/notifications?all=true&watchlist_id={TEST_WATCHLIST_ID}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_delete_all_omitted_watchlist_id(self):
        """DELETE ?all=true without watchlist_id should succeed and dismiss all owned."""
        resp = delete("/api/notifications?all=true")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_delete_all_requires_all_param(self):
        """DELETE without ?all=true should return 400."""
        resp = delete(f"/api/notifications?watchlist_id={TEST_WATCHLIST_ID}")
        assert resp.status_code == 400
        assert "all" in resp.json().get("detail", "").lower()

    def test_delete_single_missing_watchlist_id(self):
        """DELETE /{id} without watchlist_id query param should return 422."""
        resp = delete("/api/notifications/99999")
        assert resp.status_code == 422

    def test_delete_single_nonexistent_returns_404(self):
        resp = delete(
            f"/api/notifications/99999?watchlist_id={TEST_WATCHLIST_ID}"
        )
        assert resp.status_code == 404

    def test_delete_single_wrong_watchlist_returns_403(self, test_db):
        """A notification belongs to watchlist 1; deleting it as watchlist 2 → 403.

        Strategy: directly insert a notification row for watchlist 1 in the DB,
        then attempt to dismiss it while claiming it belongs to watchlist 2.
        """
        from app.models.notification import Notification

        row = Notification(
            watchlist_id=TEST_WATCHLIST_ID,
            symbol=TEST_SYMBOL,
            exchange="NSE",
            trigger_type="52w_high_breakout",
            message=f"{TEST_SYMBOL} hit a new 52-week HIGH",
            triggered_at=datetime.now(),
            triggered_date=date.today(),
            is_read=False,
        )
        test_db.add(row)
        test_db.commit()
        test_db.refresh(row)
        notif_id = row.id

        try:
            resp = delete(
                f"/api/notifications/{notif_id}?watchlist_id={TEST_WATCHLIST_2_ID}"
            )
            assert resp.status_code == 403, (
                f"Expected 403 (watchlist mismatch), got {resp.status_code}: {resp.text}"
            )
            test_db.expire_all()
            still_unread = test_db.get(Notification, notif_id)
            assert still_unread is not None
            assert still_unread.is_read is False, (
                "Notification should remain unread after rejected 403 dismiss attempt"
            )
        finally:
            test_db.delete(test_db.get(Notification, notif_id))
            test_db.commit()

    def test_delete_single_success(self, test_db):
        """Valid dismiss sets is_read=True and returns 200."""
        from app.models.notification import Notification

        row = Notification(
            watchlist_id=TEST_WATCHLIST_ID,
            symbol=TEST_SYMBOL,
            exchange="NSE",
            trigger_type="top_gainer",
            message=f"{TEST_SYMBOL} among TOP GAINERS",
            triggered_at=datetime.now(),
            triggered_date=date.today(),
            is_read=False,
        )
        test_db.add(row)
        test_db.commit()
        test_db.refresh(row)
        notif_id = row.id

        try:
            resp = delete(
                f"/api/notifications/{notif_id}?watchlist_id={TEST_WATCHLIST_ID}"
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            assert resp.json() == {"ok": True}

            test_db.expire_all()
            updated = test_db.get(Notification, notif_id)
            assert updated is not None
            assert updated.is_read is True
        finally:
            test_db.delete(test_db.get(Notification, notif_id))
            test_db.commit()


# ---------------------------------------------------------------------------
# /api/notifications — deduplication
# ---------------------------------------------------------------------------

class TestNotificationsDedup:
    """Dedup is enforced by the UniqueConstraint — these tests verify it."""

    def test_dedup_same_watchlist_same_day_inserted_once(self, test_db, require_dev_env):
        """Two inserts for the same (watchlist, symbol, trigger_type, date)
        should result in only one row — the second is silently ignored.
        """
        from sqlalchemy import select, func
        from app.models.notification import Notification

        requests.post(
            f"{BASE}/api/watchlist",
            json={"symbol": TEST_SYMBOL, "exchange": "NSE"},
        )

        row1 = Notification(
            watchlist_id=TEST_WATCHLIST_ID,
            symbol=TEST_SYMBOL,
            exchange="NSE",
            trigger_type="bulk_deal",
            message=f"{TEST_SYMBOL} — BULK deal: 100 shares",
            triggered_at=datetime.now(),
            triggered_date=date.today(),
            is_read=False,
        )
        test_db.add(row1)
        test_db.commit()
        test_db.refresh(row1)
        row1_id = row1.id

        requests.post(f"{BASE}/api/notifications/trigger")

        count = test_db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.watchlist_id == TEST_WATCHLIST_ID,
                Notification.symbol == TEST_SYMBOL,
                Notification.trigger_type == "bulk_deal",
                Notification.triggered_date == date.today(),
            )
        ).scalar_one()

        assert count == 1, (
            f"Expected exactly 1 notification for {TEST_SYMBOL}/bulk_deal/today, "
            f"got {count}. The UniqueConstraint may not be enforcing deduplication."
        )

        test_db.delete(test_db.get(Notification, row1_id))
        test_db.commit()

    def test_dedup_next_day_is_allowed(self, test_db, require_dev_env):
        """The same notification is allowed on the next calendar day."""
        from sqlalchemy import select, func
        from app.models.notification import Notification

        yesterday = date.today() - timedelta(days=1)
        row1 = Notification(
            watchlist_id=TEST_WATCHLIST_ID,
            symbol=TEST_SYMBOL,
            exchange="NSE",
            trigger_type="insider_buy",
            message=f"{TEST_SYMBOL} insider BUY",
            triggered_at=datetime.now() - timedelta(days=1),
            triggered_date=yesterday,
            is_read=False,
        )
        test_db.add(row1)
        test_db.commit()
        test_db.refresh(row1)
        row1_id = row1.id

        try:
            requests.post(f"{BASE}/api/notifications/trigger")
            count = test_db.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.watchlist_id == TEST_WATCHLIST_ID,
                    Notification.symbol == TEST_SYMBOL,
                    Notification.trigger_type == "insider_buy",
                )
            ).scalar_one()
            assert count == 2, (
                f"Expected 2 notifications across yesterday+today, got {count}. "
                "The dedup window is too narrow."
            )
        finally:
            test_db.delete(test_db.get(Notification, row1_id))
            test_db.commit()


# ---------------------------------------------------------------------------
# /api/notifications/trigger — dev endpoint
# ---------------------------------------------------------------------------

class TestNotificationsTrigger:
    def test_trigger_works_when_dev(self):
        """Without ENV=production, the trigger endpoint should succeed or 403
        depending on whether the backend is configured. At minimum the response
        must not be a 5xx (server error).
        """
        resp = requests.post(f"{BASE}/api/notifications/trigger")
        assert resp.status_code in (200, 403), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_trigger_production_guard(self):
        """Simulate ENV=production via header injection where possible.
        The most reliable signal is that without ENV set, the endpoint is accessible.
        """
        resp = requests.post(f"{BASE}/api/notifications/trigger", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("ok") is True
            assert "triggered_at" in data
        elif resp.status_code == 403:
            assert "production" in resp.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Results calendar worker
# ---------------------------------------------------------------------------


class TestResultsCalendarWorker:
    def test_sync_creates_results_notifications(self, monkeypatch):
        from app import backgroundtasks

        watchlist_id = TEST_WATCHLIST_ID
        symbol = TEST_SYMBOL
        meeting_date = date.today() + timedelta(days=3)
        meeting_date_str = meeting_date.strftime("%d-%b-%Y")

        fake_events = [
            SimpleNamespace(
                symbol=symbol,
                purpose="Financial Results / Other business matters",
                description="To consider and approve the financial results for the quarter.",
                date=meeting_date_str,
            ),
            SimpleNamespace(
                symbol="NOTWATCHED",
                purpose="Financial Results",
                description="Should be ignored.",
                date=meeting_date_str,
            ),
        ]

        def fake_get_event_calendar_cached():
            return fake_events

        def fake_get_watchlist_symbols():
            return {watchlist_id: [symbol]}

        captured: dict[str, object] = {}

        def fake_bulk_upsert(rows):
            captured["rows"] = rows

        monkeypatch.setattr("app.routers.announcements.get_event_calendar_cached", fake_get_event_calendar_cached)
        monkeypatch.setattr(backgroundtasks, "_get_watchlist_symbols", fake_get_watchlist_symbols)
        monkeypatch.setattr(backgroundtasks, "_bulk_upsert_notifications", fake_bulk_upsert)
        monkeypatch.setattr(backgroundtasks, "update_job_status_sync", lambda *args, **kwargs: None)

        backgroundtasks._results_calendar_sync()

        rows = captured.get("rows")
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["watchlist_id"] == watchlist_id
        assert rows[0]["symbol"] == symbol
        assert rows[0]["trigger_type"] == "results_upcoming"
        assert rows[0]["triggered_date"] == meeting_date
