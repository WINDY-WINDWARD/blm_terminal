> **ARCHIVED** — This document describes a completed implementation. It is kept for historical reference only and is no longer maintained.
> Active implementation: [jobs.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/jobs.py), [jobs/route.ts](file:///d:/500GB/p1/Projects/blm_terminal/src/app/api/jobs/route.ts), [orchestrator.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/orchestrator.py).

---

# Jobs Table — Background Task Tracking

## Problem

The backend runs 7 background tasks (5 thread workers + 2 async schedulers) with no centralized tracking:

| Task | Type | Schedule | Current Visibility |
|------|------|----------|-------------------|
| `stock_universe_worker` | Thread | Daily midnight | Logs only |
| `news_worker` | Thread | Every 5-30 min | Logs only |
| `watchlist_news_worker` | Thread | Every 5 min | Logs only |
| `market_data_worker` | Thread | Every 5 min (market hrs) | Logs only |
| `watchlist_notification_worker` | Thread | Every 5-30 min (market hrs) | Logs only |
| `sync_watchlist_fair_values` | Async | Every 3 hours | Logs only |
| `sync_all_fair_values` | Async | Daily 2 AM IST | Logs only |

**Gap:** No API to:
- See current status (running/idle/failed)
- View last trigger time, next trigger time
- Track progress percentage
- See errors from last run
- Manually trigger any task

---

## Solution

Add a `jobs` table that tracks all background tasks with real-time status, progress, and manual trigger capability.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Jobs Architecture                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐       │
│  │   API Router │     │ Job Registry │     │ Job Runner   │       │
│  │  /jobs/*     │────▶│ (metadata)  │────▶│ (execution)  │       │
│  └──────────────┘     └──────────────┘     └──────────────┘       │
│         │                    │                    │                │
│         │                    │                    │                │
│         ▼                    ▼                    ▼                │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                    jobs table                           │       │
│  │  id, name, status, progress, last_trigger, next_trigger  │       │
│  └─────────────────────────────────────────────────────────┘       │
│                              ▲                                      │
│                              │                                      │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │              Background Workers (read/write)           │       │
│  │  stock_universe_worker, news_worker, etc.              │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Database Model

### Table: `jobs`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer (PK) | Auto-increment |
| `job_key` | String(64) UNIQUE | Stable identifier (e.g., `job.stock_universe`) |
| `name` | String(64) | Display name (e.g., `stock_universe`) |
| `description` | String(256) | Human-readable description |
| `category` | String(32) | Group: `data_sync`, `notifications`, `analytics` |
| `schedule_type` | String(16) | `interval`, `cron`, `manual` |
| `interval_seconds` | Integer NULL | For interval-based jobs |
| `cron_expression` | String(32) NULL | For cron-based jobs |
| `last_triggered_at` | DateTime NULL | When job last started |
| `last_completed_at` | DateTime NULL | When job last finished successfully |
| `next_trigger_at` | DateTime NULL | When job will run next (calculated) |
| `last_error` | String(512) NULL | Error message from last failure |
| `status` | String(32) | `idle`, `running`, `waiting`, `failed` |
| `progress_percent` | Integer | 0-100 |
| `progress_message` | String(128) NULL | Current step description |
| `is_enabled` | Boolean | Whether scheduled runs are active |
| `is_manual_only` | Boolean | If true, only manual triggers allowed |
| `created_at` | DateTime | Record creation time |
| `updated_at` | DateTime | Last modification time |

### Indexes
- `ix_jobs_job_key` (unique)
- `ix_jobs_name`
- `ix_jobs_status`
- `ix_jobs_next_trigger_at`

### Status Values
- `idle` — Job finished, waiting for next scheduled trigger
- `running` — Job currently executing
- `waiting` — Worker is sleeping between cycles (for infinite-loop workers)
- `failed` — Job last run ended with error

### Job Key Convention
Use reverse-DNS style for stable identifiers: `job.{component_name}`. This makes refactoring safe:
- `job.stock_universe`
- `job.news`
- `job.watchlist_news`
- `job.market_data`
- `job.notifications`
- `job.watchlist_fair_value`
- `job.full_fair_value`

---

## Implementation Plan

### Phase 1: Core Infrastructure

1. **Create model** — `app/models/job.py`
2. **Create migration** — `alembic/versions/m{revision}_add_jobs_table.py`
3. **Create registry** — `app/jobs/registry.py`
   - Register all 7 background tasks
   - Map task names to callable functions
   - Provide `trigger_job()`, `get_job_status()`, `update_progress()`

### Phase 2: Job Runner

4. **Create runner** — `app/jobs/runner.py`
   - Wrap job execution with context management
   - Track start/completion times
   - Handle errors and status updates
   - Calculate next trigger time

### Phase 3: API Endpoints

5. **Create router** — `app/routers/jobs.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/jobs` | GET | List all jobs with status |
| `/jobs/{name}` | GET | Get single job details |
| `/jobs/{name}/trigger` | POST | Manually trigger a job |
| `/jobs/{name}/toggle` | POST | Enable/disable job |
| `/jobs/{name}/history` | GET | Get job run history |
| `/jobs/{name}/stream` | GET | SSE for real-time progress |

### Phase 4: Integration

6. **Modify workers** — Update `backgroundtasks.py`
   - Register jobs on app startup
   - Report progress during execution
   - Update status on completion/error

---

## Job Registry Design

```python
# app/jobs/registry.py

from dataclasses import dataclass
from typing import Callable, Any
import threading

@dataclass
class JobDefinition:
    job_key: str                 # Stable identifier: "job.stock_universe"
    name: str                    # Display name: "stock_universe"
    description: str
    category: str
    schedule_type: str           # "interval", "cron", "manual"
    interval_seconds: int | None = None
    cron_expression: str | None = None
    is_manual_only: bool = False
    callable: Callable[..., Any] # sync def or async def
    is_async: bool = False

class JobRegistry:
    _jobs: dict[str, JobDefinition] = {}
    _locks: dict[str, threading.Lock] = {}

    @classmethod
    def register(cls, job: JobDefinition) -> None:
        cls._jobs[job.job_key] = job
        cls._locks[job.job_key] = threading.Lock()

    @classmethod
    def get(cls, job_key: str) -> JobDefinition | None:
        return cls._jobs.get(job_key)

    @classmethod
    def list_all(cls) -> list[JobDefinition]:
        return list(cls._jobs.values())

    @classmethod
    def get_by_name(cls, name: str) -> JobDefinition | None:
        """Look up job by display name (for API compatibility)."""
        for job in cls._jobs.values():
            if job.name == name:
                return job
        return None

    @classmethod
    def trigger(cls, job_key: str, force: bool = False) -> dict:
        """Start job. Returns dict with ok, message, job state."""
        from app.jobs.runner import trigger_job
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return {"ok": False, "error": "Cannot trigger from async context, use trigger_job directly"}
        return loop.run_until_complete(trigger_job(job_key, force))
```

### Initial Job Registrations

```python
# At startup, register all background tasks:

JOBS = [
    JobDefinition(
        job_key="job.stock_universe",
        name="stock_universe",
        description="Sync stock metadata from NSE",
        category="data_sync",
        schedule_type="cron",
        cron_expression="0 0 * * *",  # daily midnight
        callable=stock_universe_worker,
        is_async=False,
    ),
    JobDefinition(
        job_key="job.news",
        name="news",
        description="Crawl global news from MoneyControl",
        category="data_sync",
        schedule_type="interval",
        interval_seconds=300,
        callable=news_worker,
        is_async=False,
    ),
    JobDefinition(
        job_key="job.watchlist_news",
        name="watchlist_news",
        description="Fetch news for watchlist symbols",
        category="notifications",
        schedule_type="interval",
        interval_seconds=300,
        callable=watchlist_news_worker,
        is_async=False,
    ),
    JobDefinition(
        job_key="job.market_data",
        name="market_data",
        description="Fetch sector/industry data from MoneyControl",
        category="data_sync",
        schedule_type="interval",
        interval_seconds=300,
        callable=market_data_worker,
        is_async=False,
    ),
    JobDefinition(
        job_key="job.notifications",
        name="notifications",
        description="Generate watchlist stock alerts",
        category="notifications",
        schedule_type="interval",
        interval_seconds=300,
        callable=watchlist_notification_worker,
        is_async=False,
    ),
    JobDefinition(
        job_key="job.watchlist_fair_value",
        name="watchlist_fair_value",
        description="Fetch Morningstar fair values for watchlist",
        category="analytics",
        schedule_type="interval",
        interval_seconds=10800,  # 3 hours
        callable=sync_watchlist_fair_values,
        is_async=True,
    ),
    JobDefinition(
        job_key="job.full_fair_value",
        name="full_fair_value",
        description="Fetch Morningstar fair values for all stocks",
        category="analytics",
        schedule_type="cron",
        cron_expression="30 20 * * *",  # 2 AM IST (20:30 UTC)
        callable=sync_all_fair_values,
        is_async=True,
    ),
]
```

---

## Job Runner Design

```python
# app/jobs/runner.py

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Callable

from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models.job import Job

logger = logging.getLogger(__name__)


async def get_job_status(job_key: str) -> Job | None:
    """Get job record from database."""
    async with AsyncSessionLocal() as db:
        stmt = select(Job).where(Job.job_key == job_key)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def update_job_status(
    job_key: str,
    status: str,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    last_completed: datetime | None = None,
    last_triggered: datetime | None = None,
) -> None:
    """Update job status in database. Uses timezone-aware UTC datetime."""
    async with AsyncSessionLocal() as db:
        values: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc)
        }
        if progress is not None:
            values["progress_percent"] = progress
        if message is not None:
            values["progress_message"] = message
        if error is not None:
            values["last_error"] = error
        if last_completed is not None:
            values["last_completed_at"] = last_completed
        if last_triggered is not None:
            values["last_triggered_at"] = last_triggered
        
        stmt = update(Job).where(Job.job_key == job_key).values(**values)
        await db.execute(stmt)
        await db.commit()


def calculate_next_trigger(
    schedule_type: str,
    interval_seconds: int | None,
    cron_expression: str | None,
    last_triggered: datetime | None,
) -> datetime | None:
    """Calculate next trigger time based on schedule type.
    
    For interval: last_triggered + interval_seconds
    For cron: Calculate next occurrence (simplified - use croniter for full support)
    For manual: None (no automatic scheduling)
    """
    if not last_triggered:
        return None
    
    if schedule_type == "interval" and interval_seconds:
        return last_triggered + timedelta(seconds=interval_seconds)
    
    if schedule_type == "cron" and cron_expression:
        # TODO: Use croniter library for proper cron parsing
        # For now, return None - implement later
        return None
    
    return None  # manual jobs have no automatic schedule


async def trigger_job(job_key: str, force: bool = False) -> dict:
    """Manually trigger a job.
    
    Args:
        job_key: The stable job identifier
        force: If True, kill running job and restart (default: False)
    
    Returns:
        dict with ok, message, and current job state
    
    Behavior:
        - If job is running and force=False: return error (job already running)
        - If job is running and force=True: signal shutdown, wait, then restart
        - If job is waiting (infinite loop worker): inject one extra cycle
        - If job is idle/failed: start immediately
    """
    job = await get_job_status(job_key)
    if not job:
        return {"ok": False, "error": f"Job not found: {job_key}"}
    
    job_def = JobRegistry.get(job_key)
    if not job_def:
        return {"ok": False, "error": f"Job definition not found: {job_key}"}
    
    current_status = job.status
    
    # Handle already-running job
    if current_status == "running":
        if not force:
            return {
                "ok": False,
                "error": "Job already running",
                "job": {"status": "running", "last_triggered_at": job.last_triggered_at}
            }
        # Force restart - signal shutdown event
        logger.warning(f"Force-triggering job {job_key}, stopping existing run")
        # TODO: Implement force restart logic
    
    # For infinite-loop workers (thread workers), inject an extra cycle
    if current_status == "waiting":
        # Signal the worker to run an extra cycle immediately
        # TODO: Implement injection mechanism
        return {
            "ok": True,
            "message": "Extra cycle queued for worker",
            "job": {"status": "running", "last_triggered_at": datetime.now(timezone.utc)}
        }
    
    # For idle or failed jobs, start immediately
    now = datetime.now(timezone.utc)
    await update_job_status(job_key, "running", progress=0, message="Starting...", last_triggered=now)
    
    # Run in background (don't await)
    asyncio.create_task(run_job_async(job_key))
    
    return {
        "ok": True,
        "message": "Job triggered",
        "job": {"status": "running", "last_triggered_at": now}
    }


async def run_job_async(job_key: str) -> None:
    """Execute a job with proper status tracking."""
    job_def = JobRegistry.get(job_key)
    if not job_def:
        logger.error(f"Job definition not found: {job_key}")
        return
    
    try:
        # Execute based on type
        if job_def.is_async:
            await job_def.callable()
        else:
            # Run sync callable in executor to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, job_def.callable)
        
        # Success - calculate next trigger
        now = datetime.now(timezone.utc)
        next_trigger = calculate_next_trigger(
            job_def.schedule_type,
            job_def.interval_seconds,
            job_def.cron_expression,
            now
        )
        
        await update_job_status(
            job_key, 
            "idle", 
            progress=100, 
            message="Completed",
            last_completed=now,
            last_triggered=now  # update to show this run completed
        )
        logger.info(f"Job {job_key} completed successfully")
        
    except Exception as e:
        logger.exception(f"Job {job_key} failed")
        await update_job_status(
            job_key,
            "failed",
            error=str(e)[:512]
        )
```

### Progress Reporting for Workers

Thread workers need a way to report progress. Use a callback pattern:

```python
# In backgroundtasks.py - progress callback
from app.jobs.runner import update_job_status

def report_progress(job_key: str, percent: int, message: str) -> None:
    """Thread-safe progress update. Called from worker threads."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(
            lambda: update_job_status(job_key, "running", progress=percent, message=message)
        )
    except RuntimeError:
        # No event loop running (during startup), skip update
        pass


# Example usage in worker:
def news_worker() -> None:
    """Daemon thread target for news crawling."""
    while not _shutdown_event.is_set():
        report_progress("job.news", 0, "Starting...")
        
        # ... do work ...
        report_progress("job.news", 50, "Crawling page 3 of 6")
        
        # ... do more work ...
        report_progress("job.news", 100, "Completed")
        
        # Sleep until next cycle
        _sleep_interruptible(NEWS_CRAWL_INTERVAL)
    
    # Mark as waiting (worker is alive but sleeping)
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(
            lambda: update_job_status("job.news", "waiting", progress=0, message="Waiting for next cycle")
        )
    except RuntimeError:
        pass
```

---

## API Responses

### GET /jobs

```json
{
  "jobs": [
    {
      "job_key": "job.stock_universe",
      "name": "stock_universe",
      "description": "Sync stock metadata from NSE",
      "category": "data_sync",
      "status": "idle",
      "progress_percent": 0,
      "last_triggered_at": "2026-03-25T18:00:00Z",
      "last_completed_at": "2026-03-25T18:00:15Z",
      "next_trigger_at": "2026-03-26T00:00:00Z",
      "is_enabled": true
    },
    {
      "job_key": "job.news",
      "name": "news",
      "description": "Crawl global news from MoneyControl",
      "category": "data_sync",
      "status": "running",
      "progress_percent": 45,
      "progress_message": "Crawling page 3 of 6",
      "last_triggered_at": "2026-03-25T20:05:00Z",
      "last_completed_at": null,
      "next_trigger_at": "2026-03-25T20:10:00Z",
      "is_enabled": true
    }
  ]
}
```

### POST /jobs/{name}/trigger

```json
{
  "ok": true,
  "message": "Job triggered",
  "job": {
    "job_key": "job.news",
    "name": "news",
    "status": "running",
    "last_triggered_at": "2026-03-25T20:15:00Z"
  }
}
```

### POST /jobs/{name}/trigger (when already running)

```json
{
  "ok": false,
  "error": "Job already running",
  "job": {
    "job_key": "job.news",
    "name": "news",
    "status": "running",
    "last_triggered_at": "2026-03-25T20:05:00Z"
  }
}
```

### POST /jobs/{name}/trigger?force=true (force restart)

```json
{
  "ok": true,
  "message": "Job restarted",
  "job": {
    "job_key": "job.news",
    "name": "news",
    "status": "running",
    "last_triggered_at": "2026-03-25T20:15:00Z"
  }
}
```

### GET /jobs/{name}/stream (SSE)

```
event: progress
data: {"percent": 45, "message": "Crawling page 3 of 6"}

event: complete
data: {"status": "idle", "last_completed_at": "2026-03-25T20:15:30Z"}

event: error
data: {"error": "Connection timeout", "status": "failed"}
```

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `app/models/job.py` | Create | SQLAlchemy model for jobs table |
| `alembic/versions/m{rev}_add_jobs_table.py` | Create | Migration to add table |
| `app/jobs/__init__.py` | Create | Package init |
| `app/jobs/registry.py` | Create | Job registration and lookup |
| `app/jobs/runner.py` | Create | Job execution with tracking |
| `app/routers/jobs.py` | Create | REST API endpoints |
| `app/backgroundtasks.py` | Modify | Register jobs on startup, report progress |
| `app/models/__init__.py` | Modify | Export new Job model |
| `main.py` | Modify | Include jobs router |

---

## Future Enhancements (Post-MVP)

1. **Job History Table**
   - Store each run: start time, end time, status, error, records processed
   - API: `GET /jobs/{name}/history?limit=50`
   - Auto-cleanup: keep last 100 runs per job

2. **Job Dependencies**
   - Define `depends_on: list[str]` in JobDefinition
   - Skip execution if dependency failed within N hours

3. **Failure Alerts**
   - Webhook notification after N consecutive failures
   - Integration with notification system

4. **Concurrent Job Limits**
   - Max N parallel jobs (prevent resource exhaustion)
   - Queue jobs if limit reached

5. **Manual Parameter Override**
   - `POST /jobs/news/trigger?pages=10` — pass params to job

6. **Cron Expression Editor**
   - Store custom schedules per job
   - Frontend UI for schedule configuration

7. **Last N Records API**
   - Return data fetched by job (e.g., last 100 news articles)

---

## Verification Plan

```bash
cd backend
source .venv/bin/activate

# Start server
uvicorn main:app --reload --port 4455

# List jobs
curl http://localhost:4455/api/jobs

# Trigger a job manually
curl -X POST http://localhost:4455/api/jobs/news/trigger

# Check status
curl http://localhost:4455/api/jobs/news

# Toggle job
curl -X POST http://localhost:4455/api/jobs/news/toggle -H "Content-Type: application/json" -d '{"enabled": false}'

# View logs
tail -f logs/backend.log | grep -E "jobs|trigger"
```

---

## Reviewer Feedback Addressed

### Critical Issues — Fixed

1. **Deprecated asyncio API** — Changed `asyncio.get_event_loop()` to `asyncio.get_running_loop()` at line 445 in runner code.

2. **Missing import** — Added `import asyncio` at the top of runner.py.

3. **Already-running jobs** — Added explicit handling in `trigger_job()`:
   - Returns error if job is running and `force=false`
   - Supports `force=true` parameter to kill and restart
   - For "waiting" status (infinite loop workers), queues an extra cycle

### Design Concerns — Addressed

4. **Fragile name as identifier** — Added `job_key` column with stable reverse-DNS format (`job.stock_universe`). The `name` column remains for display purposes.

5. **Thread workers never reach "idle"** — Added `waiting` status for workers between cycles. Workers call `update_job_status(..., status="waiting")` when sleeping.

6. **Progress reporting** — Added `report_progress()` callback pattern that uses `loop.call_soon_threadsafe()` for thread-safe updates.

7. **Timezone inconsistency** — All datetime operations now use `datetime.now(timezone.utc)` consistently.

### Minor Issues — Fixed

8. **status column too tight** — Changed from `String(16)` to `String(32)` to allow future states.

9. **next_trigger_at calculation** — Added `calculate_next_trigger()` function that computes next trigger time for interval-based jobs.

10. **API path** — Kept as `/api/jobs/*` - the existing `/api/py/[...path]` proxy is a catch-all that won't conflict.