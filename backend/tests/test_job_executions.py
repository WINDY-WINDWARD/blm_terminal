import pytest
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.models.job import JobExecution
from app.routers.jobs import list_job_executions, get_job_execution, _format_execution


def test_format_execution():
    exc = JobExecution(
        id=1,
        job_key="job.ai_picks_morning",
        name="ai_picks_morning",
        category="analytics",
        triggered_by="manual",
        status="completed",
        progress_percent=100,
        progress_message="Done",
        started_at=datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, 5, 8, 1, 30, tzinfo=timezone.utc),
        duration_seconds=90.0,
        error=None,
        log_lines=json.dumps([{"timestamp": "2026-10-05T08:00:00Z", "message": "Started", "level": "info"}]),
    )
    formatted = _format_execution(exc)
    assert formatted.id == 1
    assert formatted.job_key == "job.ai_picks_morning"
    assert formatted.status == "completed"
    assert len(formatted.log_lines) == 1
    assert formatted.log_lines[0]["message"] == "Started"


@pytest.mark.asyncio
async def test_list_job_executions():
    db = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 1

    exc = JobExecution(
        id=10,
        job_key="job.ai_picks_morning",
        name="ai_picks_morning",
        category="analytics",
        triggered_by="manual",
        status="running",
        progress_percent=50,
        progress_message="Loop 2: Verifier agent validating proposed picks...",
        started_at=datetime.now(timezone.utc),
        log_lines="[]",
    )
    mock_rows_result = MagicMock()
    mock_rows_result.scalars.return_value.all.return_value = [exc]

    db.execute.side_effect = [mock_count_result, mock_rows_result]

    res = await list_job_executions(job_key="job.ai_picks_morning", limit=10, offset=0, db=db)
    assert res.total == 1
    assert len(res.executions) == 1
    assert res.executions[0].id == 10
    assert res.executions[0].status == "running"
    assert res.executions[0].progress_percent == 50


@pytest.mark.asyncio
async def test_get_job_execution_not_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await get_job_execution(execution_id=9999, db=db)
    assert exc_info.value.status_code == 404
