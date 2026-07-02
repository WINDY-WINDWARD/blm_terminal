import pytest
from datetime import datetime, timezone

from app.schemas.ai_picks import PickNote

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
