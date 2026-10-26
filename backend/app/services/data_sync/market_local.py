"""Local market data sync — builds sectors/industries from local warehouse tables.

Replaces the remote MoneyControl scrape (mc_market_fetcher) with a pure-local
aggregation. Grouping comes from StockUniverse:

  - industry              -> Industry name (e.g. "Bank - Private")
  - industry_info         -> JSON with description/sector (e.g. {"description": "Banks"})

Metrics come from the local warehouse (no network):

  - per-stock % change    -> TickerScore.return_1d (percent units), falling back
                             to the last-two TickerDaily closes
  - per-stock price       -> TickerScreenerSnapshot.last_close
  - per-stock market cap  -> StockUniverse.market_cap_cr (NSE tradeInfo,
                             refreshed by the nightly universe sync), then
                             TickerScreenerSnapshot.market_cap, then stored
  - per-stock PE          -> TickerScreenerSnapshot.pe, falling back to
                             StockUniverse.symbol_pe

Category aggregates: market_cap = sum of member caps; pe = mean of member PEs;
advance/decline = count of members with per_change > 0 / < 0; sentiment is
derived from breadth. earnings_yoy has no local source and stays NULL.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, insert, select

from app.database import _SyncSessionLocal  # noqa: F401 — used by scheduler fallback
from app.models.marketcategory import MarketCategory, MarketCategoryStock
from app.models.stockuniverse import StockUniverse
from app.models.ticker import TickerDaily, TickerScore, TickerScreenerSnapshot

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TO_SLUG_CACHE: dict[str, str] = {}


def _to_slug(name: str) -> str:
    if name in _TO_SLUG_CACHE:
        return _TO_SLUG_CACHE[name]
    slug = _SLUG_RE.sub("-", name.lower().strip()).strip("-")
    _TO_SLUG_CACHE[name] = slug or "unknown"
    return _TO_SLUG_CACHE[name]


def _breadth_sentiment(advance: int, decline: int) -> str | None:
    total = advance + decline
    if total == 0:
        return None
    ratio = advance / total
    if ratio >= 0.65:
        return "Very Bullish"
    if ratio >= 0.55:
        return "Bullish"
    if ratio <= 0.35:
        return "Very Bearish"
    if ratio <= 0.45:
        return "Bearish"
    return "Neutral"


def _cap_weighted_return(pairs: list[tuple[float | None, float | None]]) -> float | None:
    valid_returns: list[float] = []
    weighted_sum = 0.0
    mcap_sum = 0.0

    for ret, mcap in pairs:
        if ret is None:
            continue
        valid_returns.append(ret)
        if mcap is not None and mcap > 0:
            weighted_sum += mcap * ret
            mcap_sum += mcap

    if not valid_returns:
        return None

    if mcap_sum > 0:
        return weighted_sum / mcap_sum

    return sum(valid_returns) / len(valid_returns)


async def _refresh_market_data_local_async() -> None:
    """Build market_categories + market_category_stocks purely from local DB."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # Load universe
        rows = (await session.execute(select(StockUniverse))).scalars().all()
        if not rows:
            logger.warning("market_local_sync: stock_universe empty — skipping")
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        symbols = [r.symbol for r in rows]

        # Per-stock metrics: screener snapshot (price / mcap / pe)
        snap_rows = (
            await session.execute(select(TickerScreenerSnapshot))
        ).scalars().all()
        snap_by_symbol: dict[str, TickerScreenerSnapshot] = {s.symbol: s for s in snap_rows}

        # Per-stock % change: precomputed 1d returns (percent units)
        score_rows = (
            await session.execute(
                select(
                    TickerScore.symbol,
                    TickerScore.return_1d,
                    TickerScore.return_1w,
                    TickerScore.return_1m,
                    TickerScore.return_6m,
                )
            )
        ).all()
        change_by_symbol: dict[str, float] = {
            sym: ret for sym, ret, _w, _m, _6m in score_rows if ret is not None
        }
        period_returns: dict[str, dict[str, float]] = {}
        for sym, _1d, ret_1w, ret_1m, ret_6m in score_rows:
            periods: dict[str, float] = {}
            if ret_1w is not None:
                periods["1w"] = ret_1w
            if ret_1m is not None:
                periods["1m"] = ret_1m
            if ret_6m is not None:
                periods["6m"] = ret_6m
            if periods:
                period_returns[sym] = periods

        # Previously stored fundamentals (written by the fundamentals
        # backfill worker). These must be preserved — the rows below are
        # rebuilt from snapshot/universe on every run, so re-read them here
        # instead of overwriting with NULL.
        stored_fundamentals: dict[str, dict[str, Any]] = {}
        try:
            for sym, mcap, np_, np_yoy in (
                await session.execute(
                    select(
                        MarketCategoryStock.symbol,
                        MarketCategoryStock.market_cap,
                        MarketCategoryStock.net_profit,
                        MarketCategoryStock.net_profit_yoy,
                    )
                )
            ).all():
                stored_fundamentals[sym] = {
                    "market_cap": mcap,
                    "net_profit": np_,
                    "net_profit_yoy": np_yoy,
                }
        except Exception:
            logger.debug("market_local_sync: stored-fundamentals read failed", exc_info=True)

        # Fallback for symbols without a score row: last-two daily closes.
        missing = [s for s in symbols if s not in change_by_symbol]
        if missing:
            try:
                rn = func.row_number().over(
                    partition_by=TickerDaily.symbol,
                    order_by=TickerDaily.date.desc(),
                ).label("rn")
                sub = (
                    select(
                        TickerDaily.symbol,
                        TickerDaily.close,
                        rn,
                    )
                    .where(TickerDaily.symbol.in_(missing))
                    .subquery()
                )
                recent = (
                    await session.execute(
                        select(sub.c.symbol, sub.c.close).where(sub.c.rn <= 2)
                    )
                ).all()
                closes: dict[str, list[float]] = defaultdict(list)
                for sym, close in recent:
                    if close:
                        closes[sym].append(close)
                for sym, pair in closes.items():
                    if len(pair) == 2 and pair[1]:
                        change_by_symbol[sym] = ((pair[0] - pair[1]) / pair[1]) * 100
            except Exception:
                logger.debug("market_local_sync: daily-close fallback failed", exc_info=True)

        # Group
        industry_groups: dict[str, list[StockUniverse]] = defaultdict(list)
        sector_groups: dict[str, list[StockUniverse]] = defaultdict(list)

        for r in rows:
            ind = (r.industry or "Unknown").strip()
            industry_groups[ind].append(r)

            # Sector derived from industry_info description
            sector = "Unknown"
            try:
                if isinstance(r.industry_info, dict):
                    sector = (r.industry_info.get("description") or r.industry_info.get("sector") or sector).strip()
            except Exception:
                pass
            if not sector:
                sector = "Unknown"
            sector_groups[sector].append(r)

        symbol_to_row = {r.symbol: r for r in rows}

        def _member_mcap(sym: str) -> float | None:
            uni = symbol_to_row.get(sym)
            if uni is not None and uni.market_cap_cr:
                return uni.market_cap_cr
            snap = snap_by_symbol.get(sym)
            if snap is not None and snap.market_cap is not None:
                return snap.market_cap
            stored = stored_fundamentals.get(sym)
            if stored is not None:
                return stored.get("market_cap")
            return None

        def _member_np_yoy(sym: str) -> float | None:
            stored = stored_fundamentals.get(sym)
            if stored is not None:
                return stored.get("net_profit_yoy")
            return None

        def _aggregate(members: list[StockUniverse]) -> dict[str, Any]:
            advance = 0
            decline = 0
            mcap_total = 0.0
            mcap_seen = False
            pe_vals: list[float] = []
            yoy_vals: list[float] = []
            pairs_1d: list[tuple[float | None, float | None]] = []
            pairs_1w: list[tuple[float | None, float | None]] = []
            pairs_1m: list[tuple[float | None, float | None]] = []
            pairs_6m: list[tuple[float | None, float | None]] = []
            for m in members:
                chg = change_by_symbol.get(m.symbol)
                if chg is not None:
                    if chg > 0:
                        advance += 1
                    elif chg < 0:
                        decline += 1
                mcap = _member_mcap(m.symbol)
                if mcap is not None:
                    mcap_total += mcap
                    mcap_seen = True
                snap = snap_by_symbol.get(m.symbol)
                pe = (snap.pe if snap is not None and snap.pe is not None else m.symbol_pe)
                if pe is not None:
                    pe_vals.append(pe)
                yoy = _member_np_yoy(m.symbol)
                if yoy is not None:
                    yoy_vals.append(yoy)
                pairs_1d.append((chg, mcap))
                rets = period_returns.get(m.symbol, {})
                pairs_1w.append((rets.get("1w"), mcap))
                pairs_1m.append((rets.get("1m"), mcap))
                pairs_6m.append((rets.get("6m"), mcap))
            return {
                "market_cap": mcap_total if mcap_seen else None,
                "pe": (sum(pe_vals) / len(pe_vals)) if pe_vals else None,
                "advance": advance,
                "decline": decline,
                "sentiment": _breadth_sentiment(advance, decline),
                "earnings_yoy": (sum(yoy_vals) / len(yoy_vals)) if yoy_vals else None,
                "return_1d": _cap_weighted_return(pairs_1d),
                "return_1w": _cap_weighted_return(pairs_1w),
                "return_1m": _cap_weighted_return(pairs_1m),
                "return_6m": _cap_weighted_return(pairs_6m),
            }

        # Build category rows
        category_rows: list[tuple[str, dict[str, Any]]] = []
        for ind, members in industry_groups.items():
            category_rows.append(("industry", {
                "slug": _to_slug(ind),
                "name": ind,
                "url": None,
                **_aggregate(members),
            }))
        for sec, members in sector_groups.items():
            category_rows.append(("sector", {
                "slug": _to_slug(sec),
                "name": sec,
                "url": None,
                **_aggregate(members),
            }))

        # Merge stock -> categories mapping
        stock_categories: dict[str, list[dict[str, str]]] = defaultdict(list)
        for ind in industry_groups:
            slug = _to_slug(ind)
            for r in industry_groups[ind]:
                stock_categories[r.symbol].append({"type": "industry", "slug": slug})
        for sec in sector_groups:
            slug = _to_slug(sec)
            for r in sector_groups[sec]:
                stock_categories[r.symbol].append({"type": "sector", "slug": slug})

        # Prepare MarketCategoryStock rows with real local metrics.
        # Fundamentals (market_cap / net_profit / net_profit_yoy) written by
        # the fundamentals backfill worker are preserved when this run has
        # no fresher value for them.
        stock_rows: list[dict[str, Any]] = []
        for sym, cats in stock_categories.items():
            r = symbol_to_row[sym]
            snap = snap_by_symbol.get(sym)
            stored = stored_fundamentals.get(sym) or {}
            mcap = _member_mcap(sym)
            stock_rows.append({
                "symbol": sym,
                "company_name": r.company_name,
                "exchange": r.series or "NSE",
                "curr_price": snap.last_close if snap is not None else None,
                "per_change": change_by_symbol.get(sym),
                "market_cap": mcap,
                "ttm_pe": (
                    snap.pe if snap is not None and snap.pe is not None
                    else r.symbol_pe
                ),
                "net_profit": stored.get("net_profit"),
                "net_profit_yoy": stored.get("net_profit_yoy"),
                "tech_trend": None,
                "mc_url": r.mc_url,
                "categories": cats,
            })

        # Persist categories with delete-then-insert (no ON CONFLICT arbiter
        # needed, so DBs missing a unique index still sync). Committed
        # independently of stocks so one failure can't zero both tables.
        cats_upserted = 0
        if category_rows:
            values_list = []
            for cat_type, data in category_rows:
                values_list.append({
                    "category_type": cat_type,
                    "slug": data["slug"],
                    "name": data["name"],
                    "url": data.get("url"),
                    "market_cap": data.get("market_cap"),
                    "pe": data.get("pe"),
                    "advance": data.get("advance"),
                    "decline": data.get("decline"),
                    "sentiment": data.get("sentiment"),
                    "earnings_yoy": data.get("earnings_yoy"),
                    "return_1d": data.get("return_1d"),
                    "return_1w": data.get("return_1w"),
                    "return_1m": data.get("return_1m"),
                    "return_6m": data.get("return_6m"),
                    "last_updated": now,
                })
            # Distinct raw names can slug-collide (UNIQUE(category_type,
            # slug)); the old ON CONFLICT upsert absorbed that, plain INSERT
            # does not — dedupe, last wins.
            deduped: dict[tuple[str, str], dict[str, Any]] = {}
            for v in values_list:
                deduped[(v["category_type"], v["slug"])] = v
            if len(deduped) != len(values_list):
                seen: set[tuple[str, str]] = set()
                dupes: list[str] = []
                for v in values_list:
                    k = (v["category_type"], v["slug"])
                    if k in seen:
                        dupes.append(f"{v['category_type']}/{v['name']}")
                    seen.add(k)
                logger.warning("market_local_sync: dropped %d slug-colliding category rows "
                               "(last wins; dropped members keep orphan refs): %s",
                               len(dupes), dupes[:5])
                values_list = list(deduped.values())
            try:
                await session.execute(delete(MarketCategory))
                await session.execute(insert(MarketCategory).values(values_list))
                await session.commit()
                cats_upserted = len(category_rows)
            except Exception:
                await session.rollback()
                logger.exception("market_local_sync: categories replace failed; continuing with stocks")

        # Persist stocks in batches with delete-then-insert per batch, keyed
        # by symbol. No ON CONFLICT arbiter needed (old DBs lack
        # uq_market_stock_symbol). Each batch commits independently and a
        # failing batch logs its range and continues with the next.
        BATCH = 500
        stocks_upserted = 0
        for i in range(0, len(stock_rows), BATCH):
            chunk = stock_rows[i:i+BATCH]
            vals = []
            for row in chunk:
                vals.append({
                    "symbol": row["symbol"],
                    "company_name": row["company_name"],
                    "exchange": row.get("exchange"),
                    "curr_price": row.get("curr_price"),
                    "per_change": row.get("per_change"),
                    "market_cap": row.get("market_cap"),
                    "ttm_pe": row.get("ttm_pe"),
                    "net_profit": row.get("net_profit"),
                    "net_profit_yoy": row.get("net_profit_yoy"),
                    "tech_trend": row.get("tech_trend"),
                    "mc_url": row.get("mc_url"),
                    "categories": row.get("categories", []),
                    "last_updated": now,
                })
            try:
                # Same slug-collision insurance as categories: dedupe by
                # symbol within the batch (last wins) so one dup row can't
                # fail the batch against uq_market_stock_symbol.
                seen: dict[str, dict[str, Any]] = {}
                for v in vals:
                    seen[v["symbol"]] = v
                if len(seen) != len(vals):
                    logger.debug("market_local_sync: dropped %d duplicate-symbol rows in batch",
                                 len(vals) - len(seen))
                    vals = list(seen.values())
                await session.execute(
                    delete(MarketCategoryStock).where(
                        MarketCategoryStock.symbol.in_([v["symbol"] for v in vals])
                    )
                )
                await session.execute(insert(MarketCategoryStock).values(vals))
                await session.commit()
                stocks_upserted += len(vals)
            except Exception:
                await session.rollback()
                logger.exception(
                    "market_local_sync: stocks batch rows %d-%d failed; continuing",
                    i, i + len(chunk),
                )

        logger.info("market_local_sync: replaced %d categories (%d industries + %d sectors) and %d stocks",
                    cats_upserted, len(industry_groups), len(sector_groups), stocks_upserted)


def _market_local_sync() -> None:
    """Sync wrapper called by orchestrator/scheduler (sync context)."""
    from app.backgroundtasks._runtime import _run_async

    try:
        logger.info("market_local_sync: starting (local aggregator)")
        _run_async(_refresh_market_data_local_async())
        logger.info("market_local_sync: complete")
    except Exception:
        logger.exception("market_local_sync: unhandled exception; will retry next cycle")
