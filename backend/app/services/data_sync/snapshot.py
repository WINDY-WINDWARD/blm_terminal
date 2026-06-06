"""Screener snapshot sync core (audit C.1, A.11).

Extracted from ``app/backgroundtasks/_impl.py``.

Public function:
- ``_screener_snapshot_sync()`` — Build/refresh
  ``ticker_screener_snapshot`` from in-memory 252d daily data plus
  2 supplementary queries (latest 1h/W/M intraday +
  stock_universe).  Called from ``_ticker_scores_sync()`` right
  after the ``ticker_scores`` upsert.  Snapshot is one row per
  symbol with all screener fields denormalized.  TQL→SQL queries
  read this table via INNER JOIN with ``ticker_scores``.

The phase-B constant ``_INTRADAY_COLS`` is co-located here so
both the column list and the function that consumes it move as a
unit.

NOTE: We import ``logger``, ``_SyncSessionLocal`` and
``update_job_status_sync`` lazily inside the function body to avoid
a circular import: ``app.backgroundtasks._impl`` re-exports us at
the bottom of its own module, so a top-level import from ``_impl``
here would deadlock the import machinery.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.stockuniverse import StockUniverse
from app.models.ticker import TickerIntraday, TickerScreenerSnapshot


# Phase B: fields to copy from latest 1h/W/M ticker_intraday row into snapshot.
# Each value is (snapshot_column_name, intraday_column_name).
_INTRADAY_COLS: list[tuple[str, str]] = [
    ("intraday_close", "close"),
    ("rsi", "rsi_14"),
    ("macd", "macd"),
    ("macd_signal", "macd_signal"),
    ("macd_histogram", "macd_histogram"),
    ("bb_middle", "bb_middle"),
    ("bb_upper", "bb_upper"),
    ("bb_lower", "bb_lower"),
    ("bb_width", "bb_width"),
    ("bb_squeeze", "bb_squeeze"),
    ("atr", "atr_14"),
    ("atr_percent", "atr_percent"),
    ("vwma_20", "vwma_20"),
    ("hv_20", "hv_20"),
    ("hv_60", "hv_60"),
    ("sharpe_60", "sharpe_60"),
    ("sharpe_126", "sharpe_126"),
]


def _screener_snapshot_sync(
    daily_df: pd.DataFrame,
    today_date: date,
    now: datetime,
) -> None:
    """Build/refresh ticker_screener_snapshot from in-memory 252d daily data
    plus 2 supplementary queries (latest 1h/W/M intraday + stock_universe).

    Called from _ticker_scores_sync() right after the ticker_scores upsert.
    Snapshot is one row per symbol with all screener fields denormalized.
    TQL→SQL queries read this table via INNER JOIN with ticker_scores.
    """
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _SyncSessionLocal = _bg_impl._SyncSessionLocal
    update_job_status_sync = _bg_impl.update_job_status_sync

    update_job_status_sync(
        "job.ticker_scores", "running", progress=95,
        message="Building screener snapshot...",
    )

    # 1. Reduce 252d window to the latest row per symbol
    daily_df_sorted = daily_df.sort_values(["symbol", "date"], ascending=[True, False])
    latest_per_sym = daily_df_sorted.groupby("symbol", as_index=False).first()

    # 2. Compute 52w high/low from the same 252d window (per symbol)
    def _agg_52w(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "high_52w": g["high"].max(),
            "low_52w": g["low"].min(),
        })

    # SQLite + SQLAlchemy return date columns as ISO strings via raw execute();
    # convert to Python date objects so the snapshot upsert doesn't fail with
    # "SQLite Date type only accepts Python Date objects as input".
    if len(latest_per_sym) > 0 and not isinstance(latest_per_sym["date"].iloc[0], date):
        latest_per_sym["date"] = pd.to_datetime(latest_per_sym["date"]).dt.date
    w52 = (
        daily_df_sorted.groupby("symbol", as_index=False)
        .apply(_agg_52w, include_groups=False)
        .reset_index(drop=True)
    )
    latest_per_sym = latest_per_sym.merge(w52, on="symbol", how="left")
    last_close = latest_per_sym["close"].astype(float)
    latest_per_sym["pct_from_52w_high"] = (
        (last_close - latest_per_sym["high_52w"]) / latest_per_sym["high_52w"] * 100
    )
    latest_per_sym["pct_from_52w_low"] = (
        (last_close - latest_per_sym["low_52w"]) / latest_per_sym["low_52w"] * 100
    )
    latest_per_sym["pct_from_52w_high"] = latest_per_sym["pct_from_52w_high"].round(2)
    latest_per_sym["pct_from_52w_low"] = latest_per_sym["pct_from_52w_low"].round(2)

    # 3. Latest 1h/W/M from ticker_intraday — one query per interval
    symbols = latest_per_sym["symbol"].tolist()
    intraday_latest: dict[tuple[str, str], dict] = {}
    # Map source column name → ORM attribute for SELECT
    intraday_attr_map = {
        "close": TickerIntraday.close,
        "rsi_14": TickerIntraday.rsi_14,
        "macd": TickerIntraday.macd,
        "macd_signal": TickerIntraday.macd_signal,
        "macd_histogram": TickerIntraday.macd_histogram,
        "bb_middle": TickerIntraday.bb_middle,
        "bb_upper": TickerIntraday.bb_upper,
        "bb_lower": TickerIntraday.bb_lower,
        "bb_width": TickerIntraday.bb_width,
        "bb_squeeze": TickerIntraday.bb_squeeze,
        "atr_14": TickerIntraday.atr_14,
        "atr_percent": TickerIntraday.atr_percent,
        "vwma_20": TickerIntraday.vwma_20,
        "hv_20": TickerIntraday.hv_20,
        "hv_60": TickerIntraday.hv_60,
        "sharpe_60": TickerIntraday.sharpe_60,
        "sharpe_126": TickerIntraday.sharpe_126,
    }
    intraday_value_cols = [c[1] for c in _INTRADAY_COLS]
    with _SyncSessionLocal() as db:
        for iv in ("1h", "W", "M"):
            stmt = (
                select(TickerIntraday.symbol, *[intraday_attr_map[c] for c in intraday_value_cols])
                .where(TickerIntraday.symbol.in_(symbols))
                .where(TickerIntraday.interval == iv)
                .order_by(TickerIntraday.symbol, TickerIntraday.timestamp.desc())
            )
            # Reduce to latest per symbol (rows already sorted desc)
            seen: set[str] = set()
            for row in db.execute(stmt).all():
                sym = row[0]
                if sym in seen:
                    continue
                seen.add(sym)
                rec = dict(zip(intraday_value_cols, row[1:]))
                intraday_latest[(sym, iv)] = rec

    # 4. Sector/industry/PE/market_cap/fair_value from stock_universe
    universe_meta: dict[str, dict] = {}
    with _SyncSessionLocal() as db:
        stmt = select(
            StockUniverse.symbol,
            StockUniverse.symbol_pe,
            StockUniverse.industry,
            StockUniverse.fair_value,
            StockUniverse.high_52w,
            StockUniverse.low_52w,
        ).where(StockUniverse.symbol.in_(symbols))
        for sym, pe, industry, fv, h52, l52 in db.execute(stmt).all():
            # industry field stores the description (e.g. "Banks", "IT - Software");
            # treat it as the sector for TQL Sector filtering (legacy behavior).
            universe_meta[sym] = {
                "pe": pe,
                "sector": industry,  # TQL "Sector" maps to industry description
                "industry": industry,
                "fair_value": fv,
            }

    # 5. Assemble snapshot rows
    snapshot_rows: list[dict] = []
    for _, r in latest_per_sym.iterrows():
        sym = r["symbol"]
        meta = universe_meta.get(sym, {})

        row: dict = {
            "symbol": sym,
            "last_date": r["date"],
            "compute_date": today_date,
            "computed_at": now,
            "last_close": float(r["close"]),
            "last_volume": int(r["volume"]),
            "last_open": float(r["open"]),
            "last_high": float(r["high"]),
            "last_low": float(r["low"]),
            # 1d indicators (sourced from TickerDaily)
            "rsi_1d": r["rsi_14"],
            "macd_1d": r["macd"],
            "macd_signal_1d": r["macd_signal"],
            "macd_histogram_1d": r["macd_histogram"],
            "bb_middle_1d": r["bb_middle"],
            "bb_upper_1d": r["bb_upper"],
            "bb_lower_1d": r["bb_lower"],
            "bb_width_1d": r["bb_width"],
            "bb_squeeze_1d": r["bb_squeeze"],
            "atr_1d": r["atr_14"],
            "atr_percent_1d": r["atr_percent"],
            "vwma_20_1d": r["vwma_20"],
            "hv_20": r["hv_20"],
            "hv_60": r["hv_60"],
            "sharpe_60": r["sharpe_60"],
            "sharpe_126": r["sharpe_126"],
            "high_52w": r["high_52w"],
            "low_52w": r["low_52w"],
            "pct_from_52w_high": r["pct_from_52w_high"],
            "pct_from_52w_low": r["pct_from_52w_low"],
            "sector": meta.get("sector"),
            "industry": meta.get("industry"),
            "pe": meta.get("pe"),
            "market_cap": None,  # Not in stock_universe; reserved for future
            "fair_value": meta.get("fair_value"),
        }

        # Add 1h/W/M intraday columns
        for iv in ("1h", "W", "M"):
            iv_row = intraday_latest.get((sym, iv), {})
            for snap_col, src_col in _INTRADAY_COLS:
                row[f"{snap_col}_{iv}"] = iv_row.get(src_col)

        snapshot_rows.append(row)

    # 6. Bulk upsert (ON CONFLICT(symbol) DO UPDATE)
    set_dict = {col: sqlite_insert(TickerScreenerSnapshot).excluded[col] for col in [
        "last_date", "compute_date", "computed_at",
        "last_close", "last_volume", "last_open", "last_high", "last_low",
        "rsi_1d", "macd_1d", "macd_signal_1d", "macd_histogram_1d",
        "bb_middle_1d", "bb_upper_1d", "bb_lower_1d", "bb_width_1d",
        "bb_squeeze_1d", "atr_1d", "atr_percent_1d", "vwma_20_1d",
        "hv_20", "hv_60", "sharpe_60", "sharpe_126",
        "high_52w", "low_52w", "pct_from_52w_high", "pct_from_52w_low",
        "sector", "industry", "pe", "market_cap", "fair_value",
        "intraday_close_1h", "rsi_1h", "macd_1h", "macd_signal_1h",
        "macd_histogram_1h", "bb_middle_1h", "bb_upper_1h", "bb_lower_1h",
        "bb_width_1h", "bb_squeeze_1h", "atr_1h", "atr_percent_1h",
        "vwma_20_1h", "hv_20_1h", "hv_60_1h", "sharpe_60_1h", "sharpe_126_1h",
        "intraday_close_W", "rsi_W", "macd_W", "macd_signal_W",
        "macd_histogram_W", "bb_middle_W", "bb_upper_W", "bb_lower_W",
        "bb_width_W", "bb_squeeze_W", "atr_W", "atr_percent_W",
        "vwma_20_W", "hv_20_W", "hv_60_W", "sharpe_60_W", "sharpe_126_W",
        "intraday_close_M", "rsi_M", "macd_M", "macd_signal_M",
        "macd_histogram_M", "bb_middle_M", "bb_upper_M", "bb_lower_M",
        "bb_width_M", "bb_squeeze_M", "atr_M", "atr_percent_M",
        "vwma_20_M", "hv_20_M", "hv_60_M", "sharpe_60_M", "sharpe_126_M",
    ]}
    with _SyncSessionLocal() as db:
        ins = sqlite_insert(TickerScreenerSnapshot).values(snapshot_rows)
        ins = ins.on_conflict_do_update(
            index_elements=["symbol"],
            set_=set_dict,
        )
        db.execute(ins)
        db.commit()
    logger.info(
        "screener_snapshot_sync: wrote %d rows to ticker_screener_snapshot",
        len(snapshot_rows),
    )
