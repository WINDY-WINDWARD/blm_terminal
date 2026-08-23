"""This router serves non-cached data directly from NSE India.

Performance optimizations (v1.3):
- Global semaphore (2 concurrent NSE requests) replaces single Lock
- Per-endpoint courtesy delay (no more global 2s gap between ANY calls)
- Request coalescing: simultaneous requests share one upstream call
- Circuit breaker with OPEN → HALF_OPEN → CLOSED recovery
- Shared snapshot cache: bulk/block/short deals from ONE NSE call
- Shared variations cache: top-gainers and top-losers each have their own
  cached payload (gainers vs loosers) with per-category derived results
- cachetools.TTLCache replaces dict-based TTL (auto-eviction, thread-safe)
"""

import logging
import os
from datetime import datetime
from functools import partial

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.marketcategory import MarketCategoryStock
from app.models.system_config import SystemConfig
from app.models.ticker import TickerDaily
from app.services.cache import nse_cache
from app.services.nse_rate_limiter import throttled_nse_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

_CHANGE_RANGES_TTL = 300.0
_SYMBOL_DATA_TTL = 60.0
_FIFTY_TWO_WEEK_TTL = 3 * 60 * 60.0
_VOLUME_GAINERS_TTL = 25 * 60.0


def _df_to_json_dict(df: pd.DataFrame) -> list[dict]:
    return df.replace({np.nan: None, pd.NA: None}).to_dict(orient="records")


def _clean_nan(obj):
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def _cache_response(data: object, cache_key: str, ttl: float) -> JSONResponse:
    nse_cache[cache_key] = data
    response = JSONResponse(content=_clean_nan(data))
    response.headers["Cache-Control"] = f"public, max-age={int(ttl)}"
    return response


def _json_response(data: object, ttl: float) -> JSONResponse:
    response = JSONResponse(content=_clean_nan(data))
    response.headers["Cache-Control"] = f"public, max-age={int(ttl)}"
    return response


async def _get_largedeal_snapshot_shared() -> dict:
    """Fetch largedeal snapshot once; derive bulk/block/short from it.

    Cached for 10 minutes so concurrent requests for bulk-deals:X,
    block-deals:X, and high-short-interest all share the same upstream fetch.
    Works in Phase 1 (sync nsepython via to_thread) and Phase 2 (async httpx).
    """
    cached = nse_cache.get("largedeal-snapshot")
    if cached is not None:
        logger.debug("Shared snapshot cache hit")
        return cached

    data = await throttled_nse_call(
        "nse",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key="largedeal-snapshot",
    )
    nse_cache["largedeal-snapshot"] = data
    return data


_MOVERS_VALID_CATEGORIES = frozenset({
    "NIFTY", "BANKNIFTY", "NIFTYNEXT50",
    "SecGtr20", "SecLwr20", "FOSec", "allSec",
})


async def _get_market_variations_shared(index: str) -> dict:
    """Fetch the full live-analysis-variations payload once; cache for reuse.

    Both top-gainers and top-losers share the same NSE URL conceptually (just
    differing by index=gainers vs index=loosers), so this helper caches the
    full categorised payload for each index.
    """
    cache_key = f"market-variations-{index}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        logger.debug("Market variations (%s) cache hit", index)
        return cached

    payload = await throttled_nse_call(
        "nse",
        partial(_active_client.get_market_variations, index),
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key=f"market-variations-{index}",
    )
    nse_cache[cache_key] = payload
    return payload


def _build_mover_response(rows: list[dict], ascending: bool, category: str = "allSec") -> list[dict]:
    """Sort, filter, and normalise variation rows for the frontend.

    The new API returns ``perChange`` (not ``pChange``). We alias both so
    existing consumers using ``pChange`` and new consumers using ``perChange``
    both work.

    Also renames ``ltp`` → ``close`` for backward compat with MoversWidget
    which reads ``lastPrice || close``.
    """
    df = pd.DataFrame(rows)
    if "perChange" not in df.columns and "pChange" in df.columns:
        df["perChange"] = pd.to_numeric(df["pChange"], errors="coerce")
    elif "perChange" in df.columns:
        df["perChange"] = pd.to_numeric(df["perChange"], errors="coerce")

    if df.empty or "perChange" not in df.columns or df["perChange"].isna().all():
        return []

    # Filter to equity series only for the allSec category
    if category == "allSec" and "series" in df.columns:
        df = df[df["series"] == "EQ"].copy()

    df["pChange"] = df["perChange"]
    df = df.dropna(subset=["pChange"])
    df = df.sort_values("pChange", ascending=ascending).head(20)

    # Normalise NaN / None before serialising
    data = df.replace({np.nan: None, pd.NA: None}).to_dict(orient="records")
    for row in data:
        if "ltp" in row and "close" not in row:
            row["close"] = row["ltp"]
    return data


@router.get("/top-gainers", summary="Top gainers on NSE", response_class=JSONResponse)
async def top_gainers(category: str = Query(default="allSec")) -> JSONResponse:
    """Get today's top-gaining NSE equities for a given category.

    Categories: NIFTY (Nifty 50), BANKNIFTY (Bank Nifty), NIFTYNEXT50 (Nifty
    Next 50), SecGtr20 (Securities > Rs 20), SecLwr20 (Securities < Rs 20),
    FOSec (F&O Securities), allSec (All Securities, default).
    """
    safe_cat = category if category in _MOVERS_VALID_CATEGORIES else "allSec"
    cache_key = f"top-gainers:{safe_cat}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, 60.0)

    payload = await _get_market_variations_shared("gainers")
    rows = payload.get(safe_cat, payload.get("allSec", {})).get("data", [])
    data = _build_mover_response(rows, ascending=False, category=safe_cat)
    return _cache_response(_clean_nan(data), cache_key, 60.0)


@router.get("/top-losers", summary="Top losers on NSE", response_class=JSONResponse)
async def top_losers(category: str = Query(default="allSec")) -> JSONResponse:
    """Get today's top-losing NSE equities for a given category.

    Same categories as top-gainers.
    """
    safe_cat = category if category in _MOVERS_VALID_CATEGORIES else "allSec"
    cache_key = f"top-losers:{safe_cat}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, 60.0)

    payload = await _get_market_variations_shared("loosers")
    rows = payload.get(safe_cat, payload.get("allSec", {})).get("data", [])
    data = _build_mover_response(rows, ascending=True, category=safe_cat)
    return _cache_response(_clean_nan(data), cache_key, 60.0)


@router.get("/movers-categories", summary="Available categories for top-gainers/top-losers", response_class=JSONResponse)
async def movers_categories() -> JSONResponse:
    """Return the list of category keys and labels supported by the variations API."""
    cached = nse_cache.get("movers-categories")
    if cached is not None:
        return _json_response(cached, 86400.0)

    payload = await _get_market_variations_shared("gainers")
    legends = payload.get("legends", [])
    categories = [
        {"key": key, "label": label}
        for key, label in legends
    ]
    return _cache_response(categories, "movers-categories", 86400.0)


@router.get("/bulk-deals/{symbol}", summary="Bulk deals for a specific stock symbol on NSE", response_class=JSONResponse)
async def bulk_deals(symbol: str) -> JSONResponse:
    cache_key = f"bulk-deals:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, 600.0)

    snapshot = await _get_largedeal_snapshot_shared()
    rows = [
        r for r in snapshot.get("BULK_DEALS_DATA", [])
        if r.get("symbol", "").upper() == symbol.upper()
    ]
    return _cache_response(rows, cache_key, 600.0)


@router.get("/block-deals/{symbol}", summary="Block deals for a specific stock symbol on NSE", response_class=JSONResponse)
async def block_deals(symbol: str) -> JSONResponse:
    cache_key = f"block-deals:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, 600.0)

    snapshot = await _get_largedeal_snapshot_shared()
    rows = [
        r for r in snapshot.get("BLOCK_DEALS_DATA", [])
        if r.get("symbol", "").upper() == symbol.upper()
    ]
    return _cache_response(rows, cache_key, 600.0)


@router.get("/high-short-interest", summary="Stocks with high short interest on NSE", response_class=JSONResponse)
async def high_short_interest() -> JSONResponse:
    cached = nse_cache.get("high-short-interest")
    if cached is not None:
        return _json_response(cached, 600.0)

    snapshot = await _get_largedeal_snapshot_shared()
    data = snapshot.get("SHORT_DEALS_DATA", [])
    return _cache_response(data, "high-short-interest", 600.0)


@router.get("/largedeal-snapshot", summary="Full largedeal snapshot (bulk/short/block) from NSE — filtered by deal significance", response_class=JSONResponse)
async def largedeal_snapshot(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Return today's bulk/block/short deals filtered to only significant trades.

    A deal is significant when its trade value (qty × price) meets one of:
      - trade_value >= notif.deal_significance_pct × market_cap  (preferred)
      - trade_value >= notif.deal_absolute_threshold_cr Rs Cr    (fallback when
        market cap is unavailable)

    Short deals carry no watp from NSE; their price is resolved from TickerDaily.
    Each returned deal is enriched with a ``trade_value_cr`` field.

    The filtered result is cached using a threshold-keyed cache key so that
    changing the thresholds in SettingsWidget produces a fresh result immediately.
    """
    # 1. Read significance thresholds from system_config
    cfg_rows = await db.execute(
        select(SystemConfig.key, SystemConfig.value).where(
            SystemConfig.key.in_([
                "notif.deal_significance_pct",
                "notif.deal_absolute_threshold_cr",
            ])
        )
    )
    cfg_map = {r[0]: r[1] for r in cfg_rows.fetchall()}
    try:
        sig_pct = float(cfg_map.get("notif.deal_significance_pct") or "0.05")
    except (TypeError, ValueError):
        sig_pct = 0.05
    try:
        abs_cr = float(cfg_map.get("notif.deal_absolute_threshold_cr") or "2.0")
    except (TypeError, ValueError):
        abs_cr = 2.0

    # 2. Check threshold-keyed cache (changing thresholds produces a new key)
    filter_cache_key = f"largedeal-filtered:{sig_pct}:{abs_cr}"
    cached = nse_cache.get(filter_cache_key)
    if cached is not None:
        return _json_response(cached, 600.0)

    # 3. Fetch raw NSE snapshot (shared 10-min cache with bulk/block per-symbol routes)
    raw = await _get_largedeal_snapshot_shared()

    # 4. Collect all deal symbols and short-deal (symbol, date) pairs for DB lookups
    all_deal_symbols: set[str] = set()
    short_pairs: list[tuple[str, object]] = []  # (symbol, date)
    for list_key, is_short in [
        ("BULK_DEALS_DATA", False),
        ("BLOCK_DEALS_DATA", False),
        ("SHORT_DEALS_DATA", True),
    ]:
        for item in raw.get(list_key, []):
            sym = (item.get("symbol") or "").upper()
            if not sym:
                continue
            all_deal_symbols.add(sym)
            if is_short:
                date_str = item.get("date") or ""
                try:
                    d = datetime.strptime(date_str, "%d-%b-%Y").date()
                    short_pairs.append((sym, d))
                except (ValueError, AttributeError):
                    pass

    # 5. Bulk-fetch market caps (Rs Cr) for all deal symbols
    mkt_rows = await db.execute(
        select(MarketCategoryStock.symbol, MarketCategoryStock.market_cap).where(
            MarketCategoryStock.symbol.in_(all_deal_symbols)
        )
    )
    market_caps_cr: dict[str, float] = {
        r[0]: float(r[1]) for r in mkt_rows.fetchall() if r[1] is not None
    }

    # 6. Fetch close prices for short deals (no watp available from NSE)
    #    Single batch query instead of one query per (symbol, date) pair.
    short_close: dict[str, dict[str, float]] = {}
    if short_pairs:
        unique_pairs = list({(sym, d) for sym, d in short_pairs})
        batch_cond = or_(*(
            and_(TickerDaily.symbol == sym, TickerDaily.date == d)
            for sym, d in unique_pairs
        ))
        close_rows = await db.execute(
            select(TickerDaily.symbol, TickerDaily.date, TickerDaily.close)
            .where(batch_cond)
        )
        for sym_val, date_val, close_val in close_rows.fetchall():
            if close_val is not None:
                # date_val may be a date object or an ISO string depending on driver
                if hasattr(date_val, "strftime"):
                    nse_date_str = date_val.strftime("%d-%b-%Y")
                else:
                    nse_date_str = datetime.strptime(str(date_val), "%Y-%m-%d").strftime("%d-%b-%Y")
                short_close.setdefault(sym_val, {})[nse_date_str] = float(close_val)

    # 7. Helper: compute trade value in Rs Cr for a raw NSE deal dict
    def _trade_value_cr(item: dict, is_short: bool) -> float:
        sym = (item.get("symbol") or "").upper()
        try:
            qty = int(str(item.get("qty") or 0).replace(",", ""))
        except (ValueError, TypeError):
            return 0.0
        if is_short:
            date_str = item.get("date") or ""
            price = short_close.get(sym, {}).get(date_str, 0.0)
        else:
            try:
                price = float(str(item.get("watp") or 0).replace(",", ""))
            except (ValueError, TypeError):
                price = 0.0
        if price <= 0 or qty <= 0:
            return 0.0
        return (qty * price) / 1e7

    # 8. Helper: decide whether a deal is significant
    def _significant(item: dict, tv_cr: float) -> bool:
        if tv_cr <= 0:
            return False
        sym = (item.get("symbol") or "").upper()
        mkt = market_caps_cr.get(sym)
        if mkt and mkt > 0:
            return (tv_cr / mkt) >= sig_pct
        return tv_cr >= abs_cr

    # 9. Filter each deal list and annotate with trade_value_cr
    filtered: dict = {
        "as_on_date": raw.get("as_on_date"),
        "_filter": {
            "significance_pct": sig_pct,
            "significance_abs_cr": abs_cr,
            "description": (
                f"Only deals where trade_value >= {sig_pct*100:.2f}% of market cap "
                f"OR trade_value >= Rs {abs_cr:.1f} Cr are included"
            ),
        },
    }
    total_counts: dict[str, int] = {}
    kept_counts: dict[str, int] = {}
    for list_key, is_short in [
        ("BULK_DEALS_DATA", False),
        ("BLOCK_DEALS_DATA", False),
        ("SHORT_DEALS_DATA", True),
    ]:
        raw_list = raw.get(list_key, [])
        total_counts[list_key] = len(raw_list)
        kept: list[dict] = []
        for item in raw_list:
            tv_cr = _trade_value_cr(item, is_short)
            if _significant(item, tv_cr):
                enriched = dict(item)
                enriched["trade_value_cr"] = round(tv_cr, 2)
                kept.append(enriched)
        kept_counts[list_key] = len(kept)
        filtered[list_key] = kept

    filtered["_filter"]["counts"] = {
        k: {"total": total_counts[k], "kept": kept_counts[k]}
        for k in total_counts
    }

    return _cache_response(_clean_nan(filtered), filter_cache_key, 600.0)


@router.get("/change-ranges/{symbol}", summary="Percentage changes over multiple timeframes for a symbol", response_class=JSONResponse)
async def change_ranges(symbol: str) -> JSONResponse:
    cache_key = f"change-ranges:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, _CHANGE_RANGES_TTL)

    data = await throttled_nse_call(
        "nse",
        partial(_active_client.get_change_ranges, symbol.upper()),
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key=f"change-ranges:{symbol.upper()}",
    )
    return _cache_response(_clean_nan(data), cache_key, _CHANGE_RANGES_TTL)


@router.get("/symbol-data/{symbol}", summary="Live symbol data from NSE (getSymbolData)", response_class=JSONResponse)
async def symbol_data(symbol: str) -> JSONResponse:
    cache_key = f"symbol-data:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, _SYMBOL_DATA_TTL)

    data = await throttled_nse_call(
        "nse",
        partial(_active_client.get_symbol_data, symbol.upper()),
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key=f"symbol-data:{symbol.upper()}",
    )
    return _cache_response(_clean_nan(data), cache_key, _SYMBOL_DATA_TTL)


@router.get("/52week-low", summary="52-week low stocks snapshot from NSE", response_class=JSONResponse)
async def fifty_two_week_low() -> JSONResponse:
    cached = nse_cache.get("52week-low")
    if cached is not None:
        return _json_response(cached, _FIFTY_TWO_WEEK_TTL)

    data = await throttled_nse_call(
        "nse",
        _active_client.get_52week_low_stocks,
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key="52week-low",
    )
    return _cache_response(_clean_nan(data), "52week-low", _FIFTY_TWO_WEEK_TTL)


@router.get("/52week-high", summary="52-week high stocks snapshot from NSE", response_class=JSONResponse)
async def fifty_two_week_high() -> JSONResponse:
    cached = nse_cache.get("52week-high")
    if cached is not None:
        return _json_response(cached, _FIFTY_TWO_WEEK_TTL)

    data = await throttled_nse_call(
        "nse",
        _active_client.get_52week_high_stocks,
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key="52week-high",
    )
    return _cache_response(_clean_nan(data), "52week-high", _FIFTY_TWO_WEEK_TTL)


@router.get("/volume-gainers", summary="Volume gainers snapshot from NSE", response_class=JSONResponse)
async def volume_gainers() -> JSONResponse:
    cached = nse_cache.get("volume-gainers")
    if cached is not None:
        return _json_response(cached, _VOLUME_GAINERS_TTL)

    data = await throttled_nse_call(
        "nse",
        _active_client.get_volume_gainers,
        is_async_fn=USE_ASYNC_NSE,
        coalesce_key="volume-gainers",
    )
    return _cache_response(_clean_nan(data), "volume-gainers", _VOLUME_GAINERS_TTL)
