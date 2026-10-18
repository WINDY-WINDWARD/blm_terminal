"""Regression coverage for the hourly intraday worker startup gate."""

from __future__ import annotations

import threading

from app.backgroundtasks import _runtime
from app.workers.data import ticker_intraday_hourly_update_worker


def test_hourly_worker_waits_for_stock_universe_before_first_run(monkeypatch) -> None:
    universe_done = threading.Event()
    hourly_done = threading.Event()
    shutdown = threading.Event()
    wait_calls: list[tuple[threading.Event, str, str]] = []
    runs: list[list[str]] = []
    statuses: list[tuple[str, str]] = []

    monkeypatch.setattr(_runtime, "_is_job_enabled", lambda _key: True)
    monkeypatch.setattr(_runtime, "_is_first_run", lambda _name: True)
    monkeypatch.setattr(_runtime, "_startup_stock_universe_done", universe_done)
    monkeypatch.setattr(_runtime, "_startup_ticker_hourly_done", hourly_done)
    monkeypatch.setattr(_runtime, "_shutdown_event", shutdown)
    monkeypatch.setattr(_runtime, "_set_first_run_complete", lambda _name: None)
    monkeypatch.setattr(_runtime, "_report_job_waiting", lambda *_args, **_kwargs: 3600)
    monkeypatch.setattr(_runtime, "_sleep_interruptible", lambda _seconds: True)

    def fake_wait(event: threading.Event, name: str, job_key: str) -> bool:
        wait_calls.append((event, name, job_key))
        return False

    monkeypatch.setattr(_runtime, "_wait_for_startup_event", fake_wait)

    import app.jobs.runner as runner
    import app.services.data_sync.intraday as intraday

    monkeypatch.setattr(
        runner,
        "update_job_status_sync",
        lambda job_key, status, **_kwargs: statuses.append((job_key, status)),
    )
    monkeypatch.setattr(intraday, "_ticker_intraday_update_sync", lambda series: runs.append(series))

    ticker_intraday_hourly_update_worker()

    assert wait_calls == [(
        universe_done,
        "stock_universe",
        "job.ticker_intraday_hourly_update",
    )]
    assert runs == [["1h"]]
    assert hourly_done.is_set()
    assert ("job.ticker_intraday_hourly_update", "running") in statuses
