"""Ticker scores sync core (audit C.1, A.7, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public function:
- ``_ticker_scores_sync()`` — single bulk window-function query
  for the last 252 daily candles per symbol, computes
  1d/1w/1m/3m/6m/1y returns + 20d volume ratio + momentum
  score/rank via percentile-rank, then upserts to
  ``ticker_scores``.  After the upsert, builds the screener
  snapshot via ``_screener_snapshot_sync`` (Phase B).  Triggered
  by ``_ticker_daily_update_sync()`` after bhavcopy/fallback.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import gc
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


logger = logging.getLogger(__name__)


def _ticker_scores_sync() -> None:
    """Compute and cache multi-period returns + momentum scores for all symbols.

    Single bulk query loads last 252 candles for ALL symbols using a window function,
    then computes all returns in-memory. Upserts to ticker_scores table.
    Triggered by _ticker_daily_update_sync() after bhavcopy/fallback.
    """
    from app.backgroundtasks._runtime import _shutdown_event
    from app.database import _SyncSessionLocal
    from app.jobs.runner import update_job_status_sync
    from app.models.ticker import TickerDaily, TickerScore
    from app.services.data_sync.snapshot import _screener_snapshot_sync

    try:
        logger.info("ticker_scores_sync: starting")
        now = datetime.now()
        today_date = now.date()

        update_job_status_sync("job.ticker_scores", "running", progress=5, message="Querying symbols with 60+ days of data...")
        with _SyncSessionLocal() as db:
            stmt = db.execute(
                select(TickerDaily.symbol, func.count(TickerDaily.id).label("cnt"))
                .group_by(TickerDaily.symbol)
                .having(func.count(TickerDaily.id) >= 60)
            )
            symbols_with_data = [row[0] for row in stmt.fetchall()]

        universe_size = len(symbols_with_data)
        if universe_size == 0:
            logger.warning("ticker_scores_sync: no symbols with 60+ days of data, skipping")
            return

        logger.info("ticker_scores_sync: loading last 252 candles for %d symbols", universe_size)
        update_job_status_sync("job.ticker_scores", "running", progress=10, message=f"Loading candle data for {universe_size} symbols...")

        with _SyncSessionLocal() as db:
            rn_col = func.row_number().over(
                partition_by=TickerDaily.symbol,
                order_by=TickerDaily.date.desc(),
            ).label("rn")
            ranked_cte = (
                select(TickerDaily, rn_col)
                .where(TickerDaily.symbol.in_(symbols_with_data))
                .cte("_ranked")
            )
            from sqlalchemy.orm import aliased
            RankedTD = aliased(TickerDaily, ranked_cte)
            raw = db.execute(
                select(RankedTD)
                .where(ranked_cte.c.rn <= 253)
                .order_by(RankedTD.symbol, RankedTD.date.desc())
            )
            all_rows = list(raw.scalars().all())

        if not all_rows:
            logger.warning("ticker_scores_sync: no ticker_daily rows found")
            return

        df = pd.DataFrame([
            {
                "symbol": r.symbol,
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "rsi_14": r.rsi_14,
                "macd": r.macd,
                "macd_signal": r.macd_signal,
                "macd_histogram": r.macd_histogram,
                "bb_middle": r.bb_middle,
                "bb_upper": r.bb_upper,
                "bb_lower": r.bb_lower,
                "bb_width": r.bb_width,
                "bb_squeeze": r.bb_squeeze,
                "atr_14": r.atr_14,
                "atr_percent": r.atr_percent,
                "vwma_20": r.vwma_20,
                "hv_20": r.hv_20,
                "hv_60": r.hv_60,
                "sharpe_60": r.sharpe_60,
                "sharpe_126": r.sharpe_126,
            }
            for r in all_rows
        ])

        TRADING_DAYS = {"1d": 1, "1w": 5, "1m": 20, "3m": 60, "6m": 120, "1y": 252}

        def calc_return(group_df: pd.DataFrame, days: int) -> Optional[float]:
            if len(group_df) < days + 1:
                return None
            sorted_df = group_df.sort_values("date")
            start_price = sorted_df.iloc[-days - 1]["close"]
            end_price = sorted_df.iloc[-1]["close"]
            if start_price is None or end_price is None or start_price == 0:
                return None
            return ((end_price - start_price) / start_price) * 100

        results: list[dict] = []
        symbols = df["symbol"].unique()
        total = len(symbols)

        for idx, symbol in enumerate(symbols):
            if _shutdown_event.is_set():
                logger.info("ticker_scores_sync: shutdown requested, stopping at %d/%d", idx, total)
                break

            if idx > 0 and idx % 100 == 0:
                logger.info("ticker_scores_sync: progress %d/%d symbols", idx, total)
                # Scale idx from 10% → 70% across the return-computation loop
                progress = 10 + int((idx / total) * 60)
                update_job_status_sync(
                    "job.ticker_scores", "running", progress=progress,
                    message=f"Computing returns: {idx}/{total} symbols",
                )

            sym_df = df[df["symbol"] == symbol].sort_values("date")

            ret_1d = calc_return(sym_df, TRADING_DAYS["1d"])
            ret_1w = calc_return(sym_df, TRADING_DAYS["1w"])
            ret_1m = calc_return(sym_df, TRADING_DAYS["1m"])
            ret_3m = calc_return(sym_df, TRADING_DAYS["3m"])
            ret_6m = calc_return(sym_df, TRADING_DAYS["6m"])
            ret_1y = calc_return(sym_df, TRADING_DAYS["1y"])

            if len(sym_df) >= 21:
                vol_20 = sym_df.tail(21)["volume"].iloc[:-1].mean()
                current_vol = sym_df.iloc[-1]["volume"]
                volume_ratio_20d = current_vol / vol_20 if vol_20 and vol_20 > 0 else None
            else:
                volume_ratio_20d = None

            results.append({
                "symbol": symbol,
                "compute_date": today_date,
                "computed_at": now,
                "return_1d": ret_1d,
                "return_1w": ret_1w,
                "return_1m": ret_1m,
                "return_3m": ret_3m,
                "return_6m": ret_6m,
                "return_1y": ret_1y,
                "volume_ratio_20d": volume_ratio_20d,
            })

        logger.info("ticker_scores_sync: computed returns for %d symbols, computing momentum", len(results))
        update_job_status_sync("job.ticker_scores", "running", progress=75, message=f"Computing momentum scores for {len(results)} symbols...")

        valid_3m = {r["symbol"]: r["return_3m"] for r in results if r["return_3m"] is not None}
        valid_6m = {r["symbol"]: r["return_6m"] for r in results if r["return_6m"] is not None}
        valid_vol = {r["symbol"]: r["volume_ratio_20d"] for r in results if r["volume_ratio_20d"] is not None}

        values_3m = list(valid_3m.values())
        values_6m = list(valid_6m.values())
        values_vol = list(valid_vol.values())

        def percentile_rank(value: Optional[float], all_vals: list[float]) -> float:
            if value is None or not all_vals:
                return 50.0
            sorted_vals = sorted(all_vals)
            rank = sum(1 for v in sorted_vals if v < value)
            return (rank / len(sorted_vals)) * 100

        scores: list[tuple[str, float]] = []
        for r in results:
            sym = r["symbol"]
            r_3m = r["return_3m"]
            r_6m = r["return_6m"]
            r_vol = r["volume_ratio_20d"]

            rank_3m = percentile_rank(r_3m, values_3m)
            rank_6m = percentile_rank(r_6m, values_6m)
            rank_vol = percentile_rank(r_vol, values_vol)

            score = 0.30 * rank_3m + 0.30 * rank_6m + 0.20 * rank_vol
            r["momentum_score"] = round(score, 1)
            scores.append((sym, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        rank_map = {sym: idx + 1 for idx, (sym, _) in enumerate(scores)}

        for r in results:
            r["momentum_rank"] = rank_map.get(r["symbol"])
            r["universe_size"] = universe_size

        logger.info("ticker_scores_sync: upserting %d rows to ticker_scores", len(results))
        update_job_status_sync("job.ticker_scores", "running", progress=90, message=f"Upserting {len(results)} scores to DB...")

        with _SyncSessionLocal() as db:
            insert_stmt = sqlite_insert(TickerScore).values(results)
            insert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "compute_date": insert_stmt.excluded.compute_date,
                    "computed_at": insert_stmt.excluded.computed_at,
                    "return_1d": insert_stmt.excluded.return_1d,
                    "return_1w": insert_stmt.excluded.return_1w,
                    "return_1m": insert_stmt.excluded.return_1m,
                    "return_3m": insert_stmt.excluded.return_3m,
                    "return_6m": insert_stmt.excluded.return_6m,
                    "return_1y": insert_stmt.excluded.return_1y,
                    "momentum_score": insert_stmt.excluded.momentum_score,
                    "momentum_rank": insert_stmt.excluded.momentum_rank,
                    "universe_size": insert_stmt.excluded.universe_size,
                    "volume_ratio_20d": insert_stmt.excluded.volume_ratio_20d,
                },
            )
            db.execute(insert_stmt)
            db.commit()
            gc.collect()

        # Phase B: also write pre-computed screener snapshot so TQL→SQL
        # queries are O(1) reads against a small denormalized table instead
        # of window-function scans over ticker_daily/ticker_intraday.
        try:
            _screener_snapshot_sync(df, today_date, now)
            gc.collect()
        except Exception:
            logger.exception("ticker_scores_sync: screener snapshot failed (non-fatal)")

        logger.info("ticker_scores_sync: complete, cached %d symbols", len(results))
        update_job_status_sync("job.ticker_scores", "waiting", progress=100, message=f"Cached {len(results)} symbols")

    except Exception:
        logger.exception("ticker_scores_sync: unhandled exception")
