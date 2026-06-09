"""Pydantic schemas for the announcements endpoints (RSS + event calendar)."""

from pydantic import BaseModel


class EventCalendarItem(BaseModel):
    """Normalised event calendar entry from NSE (main board or SME).

    ``source`` distinguishes the two NSE endpoints (main vs SME) so the
    frontend can label entries if it needs to.
    """

    symbol: str
    company: str
    purpose: str
    description: str
    date: str          # "20-Apr-2026"
    source: str        # "main" | "sme"
    attachment: str | None = None
