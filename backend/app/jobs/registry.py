"""Job registry for background task tracking."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

import threading


@dataclass
class JobDefinition:
    """Definition of a background job."""

    job_key: str
    name: str
    description: str
    category: str
    schedule_type: str
    interval_seconds: int | None = None
    cron_expression: str | None = None
    is_manual_only: bool = False
    callable: Callable[..., Any] | None = None
    is_async: bool = False


class JobRegistry:
    """Central registry for all background jobs."""

    _jobs: dict = {}
    _locks: dict = {}
    _running_jobs: set = set()
    _running_lock: threading.Lock = threading.Lock()

    @classmethod
    def register(cls, job: JobDefinition) -> None:
        """Register a job in the registry."""
        cls._jobs[job.job_key] = job
        cls._locks[job.job_key] = threading.Lock()

    @classmethod
    def get(cls, job_key: str) -> Optional[JobDefinition]:
        """Get job definition by job_key."""
        return cls._jobs.get(job_key)

    @classmethod
    def list_all(cls) -> list[JobDefinition]:
        """List all registered jobs."""
        return list(cls._jobs.values())

    @classmethod
    def get_by_name(cls, name: str) -> Optional[JobDefinition]:
        """Look up job by display name."""
        for job in cls._jobs.values():
            if job.name == name:
                return job
        return None

    @classmethod
    def is_running(cls, job_key: str) -> bool:
        """Check if a job is currently running."""
        with cls._running_lock:
            return job_key in cls._running_jobs

    @classmethod
    def set_running(cls, job_key: str, running: bool) -> None:
        """Mark a job as running or not running."""
        with cls._running_lock:
            if running:
                cls._running_jobs.add(job_key)
            else:
                cls._running_jobs.discard(job_key)

    @classmethod
    def get_lock(cls, job_key: str) -> Optional[threading.Lock]:
        """Get the lock for a specific job."""
        return cls._locks.get(job_key)
