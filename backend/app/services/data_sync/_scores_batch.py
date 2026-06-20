"""Per-batch helper for ticker scores sync."""
from __future__ import annotations

import gc
import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.database import _SyncSessionLocal
from app.models.ticker import TickerDaily
from app.services.data_sync.snapshot import _screener_snapshot_sync

logger = logging.getLogger(__name__)

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

def _process_symbol_batch(batch_symbols: list[str], today_date: date, now: datetime) -> dict[str, dict]:
    per_symbol = {}
    with _SyncSessionLocal() as db:
        rn_col = func.row_number().over(
            partition_by=TickerDaily.symbol,
            order_by=TickerDaily.date.desc(),
        ).label("rn")
        ranked_cte = (
            select(TickerDaily, rn_col)
            .where(TickerDaily.symbol.in_(batch_symbols))
            .cte("_ranked")
        )
        RankedTD = aliased(TickerDaily, ranked_cte)
        raw = db.execute(
            select(RankedTD)
            .where(ranked_cte.c.rn <= 253)
            .order_by(RankedTD.symbol, RankedTD.date.desc())
        )
        
        records = []
        for r in raw.scalars().yield_per(2000):
            records.append({
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
            })

    if not records:
        return {}

    batch_df = pd.DataFrame(records)

    for symbol in batch_df["symbol"].unique():
        sym_df = batch_df[batch_df["symbol"] == symbol].sort_values("date")

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

        per_symbol[symbol] = {
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
        }

    try:
        _screener_snapshot_sync(batch_df, today_date, now, skip_progress_update=True)
    except Exception:
        logger.exception("ticker_scores_sync: screener snapshot failed (non-fatal)")

    del batch_df, records
    gc.collect()

    return per_symbol
