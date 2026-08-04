import pytest
from datetime import datetime, timezone

from app.schemas.ai_picks import PickNote
from app.workers.ai_picks_worker import _calculate_business_days_elapsed

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
