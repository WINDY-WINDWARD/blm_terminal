import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from app.schemas.ai_picks import PickNote
from app.workers.ai_picks_worker import _calculate_business_days_elapsed
from app.routers.ai_picks import trigger_picks_run

def test_calculate_business_days_elapsed():
    """Test fully elapsed business days calculation."""
    mon_evening = datetime(2026, 8, 3, 15, 59, tzinfo=timezone.utc)
    wed_morning = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
    thu_morning = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)

    # Mon evening to Wed morning has only 1 fully elapsed business day (Tue)
    assert _calculate_business_days_elapsed(mon_evening, wed_morning) == 1
    # Mon evening to Thu morning has 2 fully elapsed business days (Tue, Wed)
    assert _calculate_business_days_elapsed(mon_evening, thu_morning) == 2

def test_pick_note_structured_fields():
    """Test structured fields in PickNote schema."""
    note = PickNote(
        timestamp=datetime.now(timezone.utc),
        note="Raw note",
        model="gpt-4o",
        verdict="BULLISH",
        technical="Good technicals",
        fundamental="Good fundamentals",
        catalyst="Earnings report",
        risk="High risk",
        action="BUY"
    )
    assert note.verdict == "BULLISH"
    assert note.action == "BUY"
    
    # Also works without them
    note_basic = PickNote(
        timestamp=datetime.now(timezone.utc),
        note="Just a note",
        model="gpt-4o"
    )
    assert note_basic.verdict is None


@pytest.mark.asyncio
async def test_trigger_picks_invalid_mode():
    admin = MagicMock()
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await trigger_picks_run(mode="unknown_mode", force=False, admin=admin, db=db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_trigger_picks_gated_15_mins():
    admin = MagicMock()
    db = AsyncMock()
    recent_job = MagicMock()
    recent_job.status = "idle"
    # triggered 5 minutes ago
    recent_job.last_triggered_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    with patch("app.routers.ai_picks.get_job_status", AsyncMock(return_value=recent_job)):
        res = await trigger_picks_run(mode="morning", force=False, admin=admin, db=db)
        assert res.ok is False
        assert res.gated is True
        assert "15-min cooldown" in res.message


@pytest.mark.asyncio
async def test_trigger_picks_running():
    admin = MagicMock()
    db = AsyncMock()
    running_job = MagicMock()
    running_job.status = "running"
    running_job.last_triggered_at = None

    with patch("app.routers.ai_picks.get_job_status", AsyncMock(return_value=running_job)):
        res = await trigger_picks_run(mode="morning", force=False, admin=admin, db=db)
        assert res.ok is False
        assert res.gated is True
        assert "currently in progress" in res.message


@pytest.mark.asyncio
async def test_trigger_picks_success():
    admin = MagicMock()
    db = AsyncMock()
    idle_job = MagicMock()
    idle_job.status = "idle"
    idle_job.last_triggered_at = datetime.now(timezone.utc) - timedelta(minutes=20)

    with patch("app.routers.ai_picks.get_job_status", AsyncMock(return_value=idle_job)), \
         patch("app.routers.ai_picks.trigger_job", AsyncMock(return_value={"ok": True})):
        res = await trigger_picks_run(mode="morning", force=False, admin=admin, db=db)
        assert res.ok is True
        assert res.gated is False
        assert "Successfully triggered Hunter (Morning)" in res.message

