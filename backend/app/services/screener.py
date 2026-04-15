"""Screener service with filtering, sorting, and caching."""

import json
import time
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, or_

from app.models.ticker import TickerDaily
from app.models.stockuniverse import StockUniverse
from app.database import _SyncSessionLocal
from app.services import returns as returns_service
from app.services import momentum as momentum_service


SCREENER_CACHE_TTL = 300
_screener_cache: dict = {"data": None, "timestamp": 0}


def _get_all_symbols_with_data() -> list[str]:
    """Get all symbols with at least some data."""
    with _SyncSessionLocal() as db:
        stmt = select(TickerDaily.symbol).distinct()
        return [s for s in db.execute(stmt).scalars().all()]


def _get_symbol_data(symbol: str) -> Optional[dict]:
    """Get comprehensive data for a symbol for screening."""
    with _SyncSessionLocal() as db:
        stmt = (
            select(TickerDaily)
            .where(TickerDaily.symbol == symbol)
            .order_by(TickerDaily.date.desc())
            .limit(252)
        )
        rows = list(db.execute(stmt).scalars().all())

    if not rows:
        return None

    rows_sorted = sorted(rows, key=lambda r: r.date)
    closes = [r.close for r in rows_sorted if r.close is not None]
    volumes = [r.volume for r in rows_sorted if r.volume is not None]
    opens = [r.open for r in rows_sorted if r.open is not None]
    highs = [r.high for r in rows_sorted if r.high is not None]
    lows = [r.low for r in rows_sorted if r.low is not None]

    if not closes or not opens or not volumes:
        return None

    current_close = closes[-1]
    current_open = opens[-1] if opens else current_close

    today_change = ((current_close - current_open) / current_open * 100) if current_open else 0

    returns = returns_service.get_returns(symbol)
    pos_52w = returns_service.get_52w_position(symbol)

    avg_vol_20 = sum(volumes[-21:-1]) / 20 if len(volumes) > 20 else 0
    volume_ratio = volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 0

    # Read indicators directly from the latest ticker_daily row (no extra DB round-trip)
    latest_row = rows_sorted[-1]
    ind = {
        "rsi_14":         latest_row.rsi_14,
        "macd":           latest_row.macd,
        "macd_signal":    latest_row.macd_signal,
        "macd_histogram": latest_row.macd_histogram,
        "bb_middle":      latest_row.bb_middle,
        "bb_upper":       latest_row.bb_upper,
        "bb_lower":       latest_row.bb_lower,
        "bb_width":       latest_row.bb_width,
        "bb_squeeze":     latest_row.bb_squeeze == "Y" if latest_row.bb_squeeze else False,
        "atr_14":         latest_row.atr_14,
        "atr_percent":    latest_row.atr_percent,
        "vwma_20":        latest_row.vwma_20,
        "hv_20":          latest_row.hv_20,
        "hv_60":          latest_row.hv_60,
        "sharpe_60":      latest_row.sharpe_60,
        "sharpe_126":     latest_row.sharpe_126,
    }

    with _SyncSessionLocal() as db:
        stock = db.execute(
            select(StockUniverse).where(StockUniverse.symbol == symbol)
        ).scalar_one_or_none()

    sector = None
    industry = None
    pe = None
    if stock:
        if stock.industry_info:
            try:
                info = json.loads(stock.industry_info) if isinstance(stock.industry_info, str) else stock.industry_info
                sector = info.get("sector")
                industry = info.get("basicIndustry")
            except (json.JSONDecodeError, TypeError):
                pass
        pe = stock.symbol_pe

    return {
        "symbol": symbol,
        "close": current_close,
        "change_today": today_change,
        "returns": returns,
        "pos_52w": pos_52w,
        "volume_ratio": volume_ratio,
        "indicators": ind,
        "sector": sector,
        "industry": industry,
        "pe": pe,
        "data_points": len(rows),
    }


def _apply_filters(symbol_data: list[dict], filters: dict) -> list[dict]:
    """Apply filter criteria to symbol data."""
    results = []

    for data in symbol_data:
        if data is None:
            continue

        returns = data.get("returns", {})
        pos_52w = data.get("pos_52w", {})
        pos_ath = data.get("pos_ath", {})
        ind = data.get("indicators", {})
        volume_ratio = data.get("volume_ratio", 0)

        if "pct_change_today_min" in filters:
            val = data.get("change_today")
            if val is None or val < filters["pct_change_today_min"]:
                continue

        if "pct_change_today_max" in filters:
            val = data.get("change_today")
            if val is None or val > filters["pct_change_today_max"]:
                continue

        if "pct_change_1w_min" in filters:
            val = returns.get("1w")
            if val is None or val < filters["pct_change_1w_min"]:
                continue

        if "pct_change_1w_max" in filters:
            val = returns.get("1w")
            if val is None or val > filters["pct_change_1w_max"]:
                continue

        if "pct_change_1m_min" in filters:
            val = returns.get("1m")
            if val is None or val < filters["pct_change_1m_min"]:
                continue

        if "pct_change_1m_max" in filters:
            val = returns.get("1m")
            if val is None or val > filters["pct_change_1m_max"]:
                continue

        if "pct_change_3m_min" in filters:
            val = returns.get("3m")
            if val is None or val < filters["pct_change_3m_min"]:
                continue

        if "pct_change_3m_max" in filters:
            val = returns.get("3m")
            if val is None or val > filters["pct_change_3m_max"]:
                continue

        if "pct_change_6m_min" in filters:
            val = returns.get("6m")
            if val is None or val < filters["pct_change_6m_min"]:
                continue

        if "pct_change_6m_max" in filters:
            val = returns.get("6m")
            if val is None or val > filters["pct_change_6m_max"]:
                continue

        if "pct_change_1y_min" in filters:
            val = returns.get("1y")
            if val is None or val < filters["pct_change_1y_min"]:
                continue

        if "pct_change_1y_max" in filters:
            val = returns.get("1y")
            if val is None or val > filters["pct_change_1y_max"]:
                continue

        if "volume_ratio_min" in filters:
            if volume_ratio is None or volume_ratio < filters["volume_ratio_min"]:
                continue

        if "volume_ratio_max" in filters:
            if volume_ratio is None or volume_ratio > filters["volume_ratio_max"]:
                continue

        if "pct_from_52w_high_min" in filters:
            pct = pos_52w.get("pct_from_52w_high")
            if pct is None or pct < filters["pct_from_52w_high_min"]:
                continue

        if "pct_from_52w_high_max" in filters:
            pct = pos_52w.get("pct_from_52w_high", 0)
            if pct > filters["pct_from_52w_high_max"]:
                continue

        if "pct_from_52w_low_min" in filters:
            pct = pos_52w.get("pct_from_52w_low", 0)
            if pct < filters["pct_from_52w_low_min"]:
                continue

        if "pct_from_52w_low_max" in filters:
            pct = pos_52w.get("pct_from_52w_low", 0)
            if pct > filters["pct_from_52w_low_max"]:
                continue

        if "is_52w_high" in filters:
            if filters["is_52w_high"] and not pos_52w.get("is_52w_high"):
                continue
            if not filters["is_52w_high"] and pos_52w.get("is_52w_high"):
                continue

        if "is_52w_low" in filters:
            if filters["is_52w_low"] and not pos_52w.get("is_52w_low"):
                continue
            if not filters["is_52w_low"] and pos_52w.get("is_52w_low"):
                continue

        if "atr_pct_max" in filters:
            atr_pct = ind.get("atr_percent")
            if atr_pct is None or atr_pct > filters["atr_pct_max"]:
                continue

        if "atr_pct_min" in filters:
            atr_pct = ind.get("atr_percent")
            if atr_pct is None or atr_pct < filters["atr_pct_min"]:
                continue

        if "rsi_min" in filters:
            rsi = ind.get("rsi_14")
            if rsi is None or rsi < filters["rsi_min"]:
                continue

        if "rsi_max" in filters:
            rsi = ind.get("rsi_14")
            if rsi is None or rsi > filters["rsi_max"]:
                continue

        if "bb_squeeze" in filters:
            squeeze = ind.get("bb_squeeze", False)
            if filters["bb_squeeze"] and not squeeze:
                continue

        if "pe_min" in filters:
            pe = data.get("pe")
            if pe is None or pe < filters["pe_min"]:
                continue

        if "pe_max" in filters:
            pe = data.get("pe")
            if pe is None or pe > filters["pe_max"]:
                continue

        if "sector" in filters:
            if data.get("sector") != filters["sector"]:
                continue

        if "industry" in filters:
            ind_str = data.get("industry") or ""
            if filters["industry"].lower() not in ind_str.lower():
                continue

        if "above_sma50" in filters:
            sma = ind.get("bb_middle")
            close = data.get("close")
            if sma is None or close is None:
                continue
            is_above = close > sma
            if filters["above_sma50"] and not is_above:
                continue
            if not filters["above_sma50"] and is_above:
                continue

        if "momentum_score_min" in filters:
            m = momentum_service.get_momentum_score(symbol)
            score = m.get("score")
            if score is None or score < filters["momentum_score_min"]:
                continue
            data["momentum_score"] = score

        if "min_data_points" in filters:
            if data.get("data_points", 0) < filters["min_data_points"]:
                continue

        results.append(data)

    return results


def _sort_results(results: list[dict], sort_by: str, order: str) -> list[dict]:
    """Sort results by specified field."""
    reverse = order == "desc"

    def safe_get(value):
        if value is None:
            return 0
        return value

    sort_key_map = {
        "symbol": lambda x: x.get("symbol", ""),
        "close": lambda x: safe_get(x.get("close")),
        "change_today": lambda x: safe_get(x.get("change_today")),
        "pct_change_1w": lambda x: safe_get(x.get("returns", {}).get("1w")),
        "pct_change_1m": lambda x: safe_get(x.get("returns", {}).get("1m")),
        "pct_change_3m": lambda x: safe_get(x.get("returns", {}).get("3m")),
        "pct_change_6m": lambda x: safe_get(x.get("returns", {}).get("6m")),
        "pct_change_1y": lambda x: safe_get(x.get("returns", {}).get("1y")),
        "volume_ratio": lambda x: safe_get(x.get("volume_ratio")),
        "pct_from_52w_high": lambda x: safe_get(x.get("pos_52w", {}).get("pct_from_52w_high")),
        "pct_from_52w_low": lambda x: safe_get(x.get("pos_52w", {}).get("pct_from_52w_low")),
        "atr_percent": lambda x: safe_get(x.get("indicators", {}).get("atr_percent")),
        "rsi": lambda x: safe_get(x.get("indicators", {}).get("rsi_14")),
        "momentum_score": lambda x: safe_get(x.get("momentum_score")),
    }

    sort_key = sort_key_map.get(sort_by, lambda x: x.get("symbol", ""))
    results.sort(key=sort_key, reverse=reverse)

    return results


def run_screener(
    filters: Optional[dict] = None,
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
    use_cache: bool = True,
) -> dict:
    """
    Run screener with given filters.

    Args:
        filters: Dict of filter criteria
        sort_by: Field to sort by
        order: asc or desc
        limit: Max results
        use_cache: Whether to use cached data (for performance)

    Returns:
        Dict with count and results
    """
    global _screener_cache

    if filters is None:
        filters = {}

    cache_key = json.dumps(filters, sort_keys=True)

    current_time = time.time()
    if use_cache and _screener_cache["data"] is not None:
        if current_time - _screener_cache["timestamp"] < SCREENER_CACHE_TTL:
            all_data = _screener_cache["data"]
        else:
            all_data = None
    else:
        all_data = None

    if all_data is None:
        symbols = _get_all_symbols_with_data()
        all_data = [_get_symbol_data(s) for s in symbols]
        _screener_cache = {"data": all_data, "timestamp": current_time}

    filtered = _apply_filters(all_data, filters)
    sorted_results = _sort_results(filtered, sort_by, order)

    results = sorted_results[:limit]

    return {
        "count": len(filtered),
        "returned": len(results),
        "filters_applied": list(filters.keys()),
        "results": results,
    }


def invalidate_cache() -> None:
    """Invalidate the screener cache."""
    global _screener_cache
    _screener_cache = {"data": None, "timestamp": 0}


def get_screener_options() -> dict:
    """Get available filter options for the screener."""
    symbols = _get_all_symbols_with_data()

    sectors = set()
    industries = set()
    pes = []

    for symbol in symbols[:100]:
        data = _get_symbol_data(symbol)
        if data:
            if data.get("sector"):
                sectors.add(data["sector"])
            if data.get("industry"):
                industries.add(data["industry"])
            pe = data.get("pe")
            if pe and pe > 0:
                pes.append(pe)

    return {
        "sectors": sorted(list(sectors))[:20],
        "sample_industries": sorted(list(industries))[:20],
        "pe_range": {"min": min(pes), "max": max(pes)} if pes else None,
    }