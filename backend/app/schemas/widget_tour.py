"""Pydantic schemas for widget tour endpoints."""

from pydantic import BaseModel, ConfigDict, Field

PANEL_COMMANDS: tuple[str, ...] = (
    "TOP",
    "POS",
    "ORDER",
    "COMPANY",
    "CHART",
    "WATCH",
    "LARGEDEALS",
    "BREAKOUTS",
    "NEWS",
    "ANALYSIS",
    "NOTIF",
    "ANNC",
    "SCAN",
    "SCREENER",
    "DOCS",
    "AI",
    "PORTFOLIO",
    "ADMIN",
    "PICKS",
)

PANEL_COMMAND_SET: frozenset[str] = frozenset(PANEL_COMMANDS)


class WidgetTourMarkSeen(BaseModel):
    """Input payload to mark a widget tour as seen."""

    command: str = Field(..., min_length=1, max_length=32)

    model_config = ConfigDict(populate_by_name=True)


class WidgetTourResponse(BaseModel):
    """Output payload after marking a tour as seen."""

    command: str
    seen_at: int

    model_config = ConfigDict(populate_by_name=True)


class WidgetToursResponse(BaseModel):
    """Output payload listing all seen widget tours."""

    seen: dict[str, int]

    model_config = ConfigDict(populate_by_name=True)
