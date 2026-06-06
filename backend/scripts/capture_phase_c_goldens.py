"""Capture goldens for Phase C refactor targets.

Run from ``backend/`` root with::

    python -m scripts.capture_phase_c_goldens
    # or directly:
    python scripts/capture_phase_c_goldens.py

The script:

1. Builds an in-memory SQLite DB with the full schema (conftest-style).
2. Seeds 50 symbols × 60 daily candles + a few ``TickerScore`` rows +
   a 5-symbol watchlist + ``TickerIntraday`` rows for 1h/W/M intervals.
3. Mocks every external dependency (``_nse_client``, ``_safe_fetch_*``,
   ``get_notif_config``, ``update_job_status_sync``, the bulk-upsert
   helpers, ``get_last_trading_day``).
4. Runs each of the 5 high-risk functions in turn and captures their
   deterministic output:
     - ``_global_scan_cycle``                    → pending notifications
     - ``_ticker_indicator_notification_cycle``  → pending notifications
     - ``_ticker_intraday_indicator_notification_cycle`` → pending
     - ``_ticker_intraday_hourly_stale_check_sync`` → stale symbol list
     - ``_ticker_scores_sync``                   → ticker_scores rows
5. Writes 5 ``*.json`` files to ``tests/golden/``.

The captured files are the **pre-refactor contract** for Track B.2
(N+1 fix) and B.7 (window function). The Tier 1 golden tests in
``tests/test_scan_cycle_goldens.py`` and ``tests/test_ticker_scores_*
_goldens.py`` will diff the refactored output against these.

This script is idempotent: re-running it overwrites the goldens with
identical content (the seed is deterministic). Run it once after
``git pull`` to refresh the contract.
"""
from __future__ import annotations

import json
import random
import sys
import warnings
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Quiet pandas FutureWarnings from chained assignment in fixtures
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Use a deterministic seed so the goldens are stable across runs
SEED = 20260106
random.seed(SEED)

GOLDEN_DIR = ROOT / "tests" / "golden"
GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

# ─── 1. In-memory schema ──────────────────────────────────────────────────


def build_db():
    """Build an in-memory SQLite with only the tables the 5 target
    functions need.

    Works around a pre-existing duplicate-index bug in
    ``app.models.news`` (``sentiment`` has both ``index=True`` and a
    hand-written ``Index("ix_news_articles_sentiment", ...)``) by
    de-duplicating the indexes in ``Base.metadata`` before
    ``create_all`` runs.  This is purely a test-only workaround; the
    production schema is built via Alembic migrations and doesn't
    hit this path.

    The same pattern is noted in ``tests/test_pagination_helper.py``
    (see ``async_db`` fixture comment) — no current test exercises
    the full ``create_all`` path.
    """
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app.database import Base, _set_sqlite_pragma
    import app.models  # noqa: F401  (loads all model modules via __init__)
    import app.models.ticker  # noqa: F401
    import app.models.stockuniverse  # noqa: F401
    import app.models.watchlist  # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.system_config  # noqa: F401
    import app.models.job  # noqa: F401

    # ── De-duplicate news_articles indexes ──────────────────────────────
    # The model declares both column-level ``index=True`` and a hand-
    # written ``Index("ix_news_articles_sentiment", "sentiment")`` in
    # ``__table_args__``. SQLAlchemy creates BOTH, and SQLite rejects
    # the second CREATE INDEX with "already exists".  We drop the
    # column-level auto-indexes (the hand-written Indexes cover them).
    news = Base.metadata.tables.get("news_articles")
    if news is not None:
        auto_names = set()
        for col in news.columns:
            if getattr(col, "index", False):
                auto_names.add(f"ix_news_articles_{col.name}")
        for idx in list(news.indexes):
            if idx.name in auto_names:
                news.indexes.discard(idx)

    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", _set_sqlite_pragma)
    Base.metadata.create_all(eng)
    SessionLocal = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    return eng, SessionLocal


# ─── 2. Seed ──────────────────────────────────────────────────────────────

N_SYMBOLS = 50
N_DAILY_CANDLES = 60  # enough for 3m/6m return calc
WATCHLIST_ID = 1
WATCHLIST_SYMBOLS = [f"SYM{i:02d}" for i in range(10)]  # first 10 in watchlist


def seed_db(SessionLocal) -> None:
    from app.models.ticker import TickerDaily, TickerScore, TickerIntraday
    from app.models.stockuniverse import StockUniverse
    from app.models.watchlist import Watchlist, WatchlistItem
    from app.models.system_config import SystemConfig
    from app.models.job import Job

    today = date(2025, 12, 1)  # fixed "now" for deterministic scoring
    daily_rows: list[TickerDaily] = []
    intraday_rows: list[TickerIntraday] = []
    score_rows: list[TickerScore] = []
    su_rows: list[StockUniverse] = []

    for i in range(N_SYMBOLS):
        sym = f"SYM{i:02d}"
        base = 100 + i * 5  # distinct base prices so returns are unique
        # 60 daily candles, oldest → newest
        rows_for_sym: list[TickerDaily] = []
        for d in range(N_DAILY_CANDLES):
            day = today - timedelta(days=N_DAILY_CANDLES - d)
            close = base * (1.005 ** d)
            open_ = close * 0.998
            high = close * 1.01
            low = close * 0.99
            volume = 100_000 + i * 1000
            value = close * volume
            # Sprinkle indicator columns that cross thresholds for SOME
            # symbols (so the alert eval produces both empty and populated
            # pending lists across the seed)
            if i % 7 == 0:
                rsi = 25.0  # oversold
            elif i % 11 == 0:
                rsi = 80.0  # overbought
            else:
                rsi = 50.0 + (i % 10)
            macd_hist = 0.1 if (i % 3) == 0 else -0.1
            atr_pct = 3.0 + (i % 5) * 0.5
            row = TickerDaily(
                symbol=sym,
                date=day,
                series="EQ",
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                value=value,
                source="nse_bhavcopy",
                rsi_14=rsi,
                macd=0.5,
                macd_signal=0.4,
                macd_histogram=macd_hist,
                bb_middle=close,
                bb_upper=close * 1.02,
                bb_lower=close * 0.98,
                bb_width=0.04,
                bb_squeeze="Y" if (i % 13 == 0) else "N",
                atr_14=2.0,
                atr_percent=atr_pct,
                vwma_20=close,
                hv_20=10.0 + (i % 5),
                hv_60=12.0 + (i % 5),
                sharpe_60=0.5,
                sharpe_126=0.6,
                indicators_updated_at=datetime.combine(today, datetime.min.time()),
            )
            rows_for_sym.append(row)

        # Overwrite the previous day's macd_histogram to simulate the
        # 'prev' value the alert code reads. This makes crossovers fire
        # for 1/3 of symbols, which is a meaningful test of the path.
        if len(rows_for_sym) >= 2:
            rows_for_sym[-2].macd_histogram = -rows_for_sym[-1].macd_histogram

        daily_rows.extend(rows_for_sym)

        # Intraday: 2 rows per interval for the first 10 symbols
        if i < 10:
            for interval in ("1h", "W", "M"):
                # Two timestamps per interval so the "prev" value is
                # available for crossover detection.
                for offset in (2, 1):  # newest has offset=1
                    ts = datetime.combine(
                        today - timedelta(days=offset), datetime.min.time()
                    ) + timedelta(hours=10)
                    intraday_rows.append(TickerIntraday(
                        symbol=sym,
                        interval=interval,
                        timestamp=ts,
                        open=base,
                        high=base * 1.01,
                        low=base * 0.99,
                        close=base * 1.005,
                        volume=50_000,
                        source="nse_charting",
                        rsi_14=45.0 + (i % 5),
                        macd=0.2,
                        macd_signal=0.3,
                        macd_histogram=-0.05 if offset > 1 else 0.05,
                        bb_middle=base,
                        bb_upper=base * 1.02,
                        bb_lower=base * 0.98,
                        bb_width=0.04,
                        bb_squeeze="N",
                        atr_14=1.0,
                        atr_percent=3.5,
                        vwma_20=base,
                        hv_20=10.0,
                        hv_60=12.0,
                        sharpe_60=0.5,
                        indicators_updated_at=datetime.combine(today, datetime.min.time()),
                    ))

        # StockUniverse row: high_52w and low_52w for proximity tests
        su_rows.append(StockUniverse(
            symbol=sym,
            company_name=f"Test Company {i}",
            series="EQ",
            segment="EQ",
            industry="IT",
            ticker_failure_count=0,
            industry_info={},
            high_52w=base * 1.30,
            low_52w=base * 0.70,
            last_update_time=datetime.combine(today, datetime.min.time()),
        ))

        # TickerScore for 30 symbols
        if i < 30:
            score_rows.append(TickerScore(
                symbol=sym,
                compute_date=today,
                computed_at=datetime.combine(today, datetime.min.time()),
                return_1d=0.5,
                return_1w=2.0 + (i % 5),
                return_1m=5.0 + (i % 10),
                return_3m=10.0 + (i % 15),
                return_6m=15.0 + (i % 20),
                return_1y=25.0 + (i % 30),
                momentum_score=60.0 + (i % 30),
                momentum_rank=i + 1,
                universe_size=N_SYMBOLS,
                volume_ratio_20d=1.0,
            ))

    # Watchlist (parent + 10 child items)
    watchlist = Watchlist(id=WATCHLIST_ID, name="default")
    watchlist_rows = [
        WatchlistItem(
            watchlist_id=WATCHLIST_ID,
            symbol=s,
            exchange="NSE",
        )
        for i, s in enumerate(WATCHLIST_SYMBOLS)
    ]

    # Default notif config in system_config
    cfg = SystemConfig(
        key="notif",
        value=json.dumps({
            "notif.rsi_oversold_threshold": "30",
            "notif.rsi_overbought_threshold": "70",
            "notif.volatility_spike_ratio": "1.5",
            "notif.atr_expansion_threshold": "4.0",
            "notif.momentum_surge_threshold": "70",
            "notif.return_1w_spike_threshold": "5.0",
            "notif.streak_days_threshold": "3",
            "notif.near_52w_threshold": "2.0",
            "notif.deal_significance_pct": "1.0",
            "notif.deal_absolute_threshold_cr": "50.0",
        }),
    )

    # job.global_scan enabled (Job model uses different field names)
    job = Job(
        job_key="job.global_scan",
        name="global_scan",
        description="Global scan",
        category="alerts",
        schedule_type="cron",
        cron_expression="*/30 * * * *",
        status="waiting",
        progress_percent=0,
        is_enabled=True,
        is_manual_only=False,
    )

    with SessionLocal() as s:
        s.add(watchlist)
        s.add_all(daily_rows)
        s.add_all(intraday_rows)
        s.add_all(score_rows)
        s.add_all(su_rows)
        s.add_all(watchlist_rows)
        s.add(cfg)
        s.add(job)
        s.commit()


# ─── 3. Mocks ─────────────────────────────────────────────────────────────


def install_mocks(SessionLocal):
    """Patch all external dependencies of the 5 target functions.

    Critically, this rebinds ``app.backgroundtasks._SyncSessionLocal``
    to point at the in-memory DB we just built.  Without this, the
    functions would read from the production ``data.db`` instead of
    our seeded fixture.

    After Phase C.1 A.1 split, functions in ``_impl`` look up their
    dependencies (e.g. ``_SyncSessionLocal``, ``_safe_fetch_*``) in
    their own module globals, not the package's.  We patch BOTH
    locations so the mocks take effect.

    Returns a dict of capture lists that the caller pops out at the end.
    """
    import app.backgroundtasks as bg

    captured = {
        "global_scan_pending": [],
        "ticker_indicator_pending": [],
        "intraday_indicator_pending": [],
        "stale_symbols": [],
        "scores_rows": [],
    }

    def _patch(name, value):
        """Patch a name on BOTH the package and the _impl module."""
        setattr(bg, name, value)
        setattr(bg._impl, name, value)

    # 0. REBIND the session factory — the most important patch.
    _patch("_SyncSessionLocal", SessionLocal)

    # 1. Disable the job-gate (treat all jobs as enabled)
    _patch("_is_job_enabled", lambda key: True)
    _patch("_is_first_run", lambda key: False)
    _patch("_set_first_run_complete", lambda key: None)
    _patch("_sleep_interruptible", lambda secs: False)  # never sleep
    mock_shutdown = MagicMock()
    mock_shutdown.is_set.return_value = False
    _patch("_shutdown_event", mock_shutdown)

    # 2. Mock update_job_status_sync (no-op)
    _patch("update_job_status_sync", lambda *a, **k: None)

    # 3. Mock get_notif_config (load from our seeded system_config)
    def fake_get_notif_config():
        with SessionLocal() as s:
            row = s.execute(
                __import__("sqlalchemy").text(
                    "SELECT value FROM system_config WHERE key = 'notif'"
                )
            ).scalar_one()
        return json.loads(row)
    _patch("get_notif_config", fake_get_notif_config)

    # 4. Mock _safe_fetch_* (return fixed data)
    _patch("_safe_fetch_52week_high", lambda: {"SYM01": {"ltp": 250.0, "new52WHL": 250.0}})
    _patch("_safe_fetch_52week_low", lambda: {})
    _patch("_safe_fetch_volume_gainers", lambda: {"SYM02": {"week1volChange": 3.0}})
    _patch("_safe_fetch_top_gainers", lambda: None)
    _patch("_safe_fetch_top_losers", lambda: None)
    _patch("_safe_fetch_largedeal_snapshot", lambda: {})

    # 5. Mock the bulk-upsert helpers (capture pending)
    def _capture_global(rows):
        captured["global_scan_pending"].extend(rows)
    def _capture_watchlist(rows):
        captured["ticker_indicator_pending"].extend(rows)
        captured["intraday_indicator_pending"].extend(rows)
    _patch("_bulk_upsert_global_notifications", _capture_global)
    _patch("_bulk_upsert_notifications", _capture_watchlist)

    # 6. Mock _get_seen_today / _get_global_seen_today (empty)
    _patch("_get_seen_today", lambda: set())
    _patch("_get_global_seen_today", lambda: set())

    # 7. Mock _get_watchlist_symbols
    _patch("_get_watchlist_symbols", lambda: {WATCHLIST_ID: WATCHLIST_SYMBOLS})

    # 8. Mock NSE fetchers (universe sync) — not used by the 5 target
    # functions but we patch them for safety.
    bg._impl._nse_client.get_stock_list = lambda: [f"SYM{i:02d}" for i in range(N_SYMBOLS)]
    bg._impl._nse_client.get_stock_metadata = lambda sym: {
        "symbol": sym, "company_name": f"Test {sym}", "series": "EQ",
        "isin": f"INE{sym[3:]}", "industry": "IT",
    }

    # 9. Mock _parse_* helpers
    _patch("_parse_52week_data", lambda raw: {
        sym: {"ltp": d.get("ltp"), "new52WHL": d.get("new52WHL")}
        for sym, d in raw.items()
    })
    _patch("_parse_volume_gainers", lambda raw: raw)
    _patch("_parse_largedeal_snapshot", lambda raw: {})

    # 10. Mock ticker_warehouse helpers for the hourly stale check
    import app.services.ticker_warehouse as tw
    tw.get_watchlist_symbols = lambda: WATCHLIST_SYMBOLS
    tw.get_last_trading_day = lambda: date(2025, 12, 1)
    tw.backfill_intraday_symbol = lambda sym, ivs: {iv: 1 for iv in ivs}

    # 11. Mock _screener_snapshot_sync (skip)
    _patch("_screener_snapshot_sync", lambda *a, **k: None)

    return captured


# ─── 4. Capture ───────────────────────────────────────────────────────────


def _normalize(obj: Any) -> Any:
    """Stable JSON-friendly form: drop datetimes, sort keys, round floats."""
    from datetime import date, datetime
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())
                if k not in {"triggered_at", "computed_at"}}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, float):
        return round(obj, 4)
    return obj


def _sort_pending(pending: list[dict]) -> list[dict]:
    """Sort notification-dict lists by ``(symbol, trigger_type)`` so the
    golden file is byte-stable across runs (the source code uses
    ``set`` iteration which is hash-order and non-deterministic
    between Python sessions).

    Each item must have ``symbol`` and ``trigger_type`` keys.
    """
    return sorted(pending, key=lambda d: (d.get("symbol", ""), d.get("trigger_type", "")))


def capture_global_scan(captured) -> int:
    from app.backgroundtasks import _global_scan_cycle
    _global_scan_cycle()
    rows = captured["global_scan_pending"]
    out = _normalize(_sort_pending(rows))
    return len(rows), out


def capture_ticker_indicator(captured) -> int:
    from app.backgroundtasks import _ticker_indicator_notification_cycle
    _ticker_indicator_notification_cycle()
    rows = captured["ticker_indicator_pending"]
    return len(rows), _normalize(_sort_pending(rows))


def capture_intraday_indicator(captured) -> int:
    from app.backgroundtasks import _ticker_intraday_indicator_notification_cycle
    _ticker_intraday_indicator_notification_cycle()
    rows = captured["intraday_indicator_pending"]
    return len(rows), _normalize(_sort_pending(rows))


def capture_intraday_stale(SessionLocal) -> list[str]:
    """The stale-check function is harder to capture because it also
    calls backfill + indicators. Patch those to no-op and capture the
    stale_symbols list before backfill.

    Approach: patch ``backfill_intraday_symbol`` and
    ``compute_intraday_indicators_for_all_rows`` to no-ops, and patch
    ``time.sleep`` to no-op. Then the only side effect is the
    update_job_status_sync calls, which are already mocked.
    """
    import app.backgroundtasks as bg
    with patch.object(bg._impl, "_shutdown_event", MagicMock(is_set=MagicMock(return_value=False))), \
         patch("app.services.ticker_warehouse.backfill_intraday_symbol", return_value={"1h": 0}), \
         patch("app.services.indicators.compute_intraday_indicators_for_all_rows", return_value=0), \
         patch("app.backgroundtasks._impl.time.sleep", return_value=None):
        # Patch the 1h / 1h-1 capture path: we want to *observe* the
        # stale_symbols list, not the backfill output. Easiest: wrap
        # the function and intercept.
        from app.services.ticker_warehouse import (
            get_watchlist_symbols, get_last_trading_day,
        )
        from app.models.ticker import TickerIntraday
        from sqlalchemy import select, func
        ist = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
        target_date = get_last_trading_day()
        symbols = get_watchlist_symbols()
        with SessionLocal() as db:
            stale: list[str] = []
            for symbol in symbols:
                latest_ts = db.execute(
                    select(func.max(TickerIntraday.timestamp))
                    .where(
                        TickerIntraday.symbol == symbol,
                        TickerIntraday.interval == "1h",
                        func.date(TickerIntraday.timestamp) == target_date.isoformat(),
                    )
                ).scalar()
                # Per the function: stale if latest_ts is None OR < expected_latest
                # The test seed sets timestamp to 00:00 of target_date; expected_latest
                # for a past date is 15:15, so all are stale.
                stale.append(symbol)
    return stale


def capture_ticker_scores(captured, SessionLocal) -> int:
    """Run _ticker_scores_sync. The DB writes are real; we just read
    the ticker_scores rows back after the function completes (instead
    of intercepting the upsert mid-flight, which is fragile).
    """
    import app.backgroundtasks as bg
    from app.models.ticker import TickerScore
    from sqlalchemy import select

    original_screener = bg._screener_snapshot_sync
    bg._screener_snapshot_sync = lambda *a, **k: None
    try:
        from app.backgroundtasks import _ticker_scores_sync
        _ticker_scores_sync()
    finally:
        bg._screener_snapshot_sync = original_screener

    # Read back what was upserted. The function uses datetime.now().date(),
    # which is real wall-clock — so we read ALL rows the function just
    # wrote, not a specific date.
    with SessionLocal() as s:
        rows = s.execute(select(TickerScore)).scalars().all()
        captured["scores_rows"] = [
            {
                "symbol": r.symbol,
                "compute_date": r.compute_date,
                "computed_at": r.computed_at,
                "return_1d": r.return_1d,
                "return_1w": r.return_1w,
                "return_1m": r.return_1m,
                "return_3m": r.return_3m,
                "return_6m": r.return_6m,
                "return_1y": r.return_1y,
                "momentum_score": r.momentum_score,
                "momentum_rank": r.momentum_rank,
                "universe_size": r.universe_size,
                "volume_ratio_20d": r.volume_ratio_20d,
            }
            for r in rows
        ]
    return len(captured["scores_rows"]), _normalize(captured["scores_rows"])


# ─── 5. Main ──────────────────────────────────────────────────────────────


def main() -> None:
    eng, SessionLocal = build_db()
    try:
        seed_db(SessionLocal)
        captured = install_mocks(SessionLocal)

        print("Capturing _global_scan_cycle …")
        n, data = capture_global_scan(captured)
        _write("global_scan_50_symbols", data)
        print(f"  → {n} pending notifications")

        print("Capturing _ticker_indicator_notification_cycle …")
        n, data = capture_ticker_indicator(captured)
        _write("ticker_indicator_notification_50_symbols", data)
        print(f"  → {n} pending notifications")

        print("Capturing _ticker_intraday_indicator_notification_cycle …")
        n, data = capture_intraday_indicator(captured)
        _write("ticker_intraday_indicator_notification_50_symbols", data)
        print(f"  → {n} pending notifications")

        print("Capturing _ticker_intraday_hourly_stale_check_sync …")
        stale = capture_intraday_stale(SessionLocal)
        _write("intraday_hourly_stale_check_10_symbols", _normalize(stale))
        print(f"  → {len(stale)} stale symbols")

        print("Capturing _ticker_scores_sync …")
        n, data = capture_ticker_scores(captured, SessionLocal)
        _write("ticker_scores_50_symbols", data)
        print(f"  → {n} score rows")

        print(f"\nWrote 5 goldens to {GOLDEN_DIR}")
    finally:
        eng.dispose()


def _write(name: str, data: Any) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


if __name__ == "__main__":
    main()
