"""Breakout snapshots router — exposes repeat-breakout data for the frontend."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.breakout_snapshot import BreakoutSnapshot


router = APIRouter(prefix="/breakouts", tags=["breakouts"])


class RepeatedBreakoutItem(BaseModel):
    symbol: str
    breakout_type: str
    appearances: int
    window_days: int
    last_seen: date


@router.get("/repeated", response_model=list[RepeatedBreakoutItem])
async def get_repeated_breakouts(
    window_days: int = Query(10, ge=1, le=30),
    min_days: int = Query(2, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Return symbols that appeared in breakout lists >= min_days times within the window."""
    cutoff = date.today() - timedelta(days=window_days)

    result = await db.execute(
        text(
            "SELECT symbol, breakout_type, COUNT(DISTINCT snapshot_date) AS cnt, "
            "MAX(snapshot_date) AS last_seen "
            "FROM breakout_snapshots "
            "WHERE snapshot_date >= :cutoff "
            "GROUP BY symbol, breakout_type "
            "HAVING cnt >= :min_days "
            "ORDER BY cnt DESC, symbol ASC"
        ),
        {"cutoff": cutoff, "min_days": min_days},
    )
    rows = result.fetchall()

    return [
        RepeatedBreakoutItem(
            symbol=row[0],
            breakout_type=row[1],
            appearances=row[2],
            window_days=window_days,
            last_seen=row[3],
        )
        for row in rows
    ]
