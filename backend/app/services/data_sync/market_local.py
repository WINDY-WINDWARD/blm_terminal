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

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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
                select(TickerScore.symbol, TickerScore.return_1d)
            )
        ).all()
        change_by_symbol: dict[str, float] = {
            sym: ret for sym, ret in score_rows if ret is not None
        }

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
            return {
                "market_cap": mcap_total if mcap_seen else None,
                "pe": (sum(pe_vals) / len(pe_vals)) if pe_vals else None,
                "advance": advance,
                "decline": decline,
                "sentiment": _breadth_sentiment(advance, decline),
                "earnings_yoy": (sum(yoy_vals) / len(yoy_vals)) if yoy_vals else None,
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

        # Bulk upsert categories
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
                    "last_updated": now,
                })
            insert_stmt = sqlite_insert(MarketCategory).values(values_list)
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["category_type", "slug"],
                set_={
                    "name": insert_stmt.excluded.name,
                    "url": insert_stmt.excluded.url,
                    "market_cap": insert_stmt.excluded.market_cap,
                    "pe": insert_stmt.excluded.pe,
                    "advance": insert_stmt.excluded.advance,
                    "decline": insert_stmt.excluded.decline,
                    "sentiment": insert_stmt.excluded.sentiment,
                    "earnings_yoy": insert_stmt.excluded.earnings_yoy,
                    "last_updated": insert_stmt.excluded.last_updated,
                },
            )
            await session.execute(stmt)

        # Bulk upsert stocks in batches
        BATCH = 500
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
            insert_stmt2 = sqlite_insert(MarketCategoryStock).values(vals)
            stmt2 = insert_stmt2.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "company_name": insert_stmt2.excluded.company_name,
                    "exchange": insert_stmt2.excluded.exchange,
                    "curr_price": insert_stmt2.excluded.curr_price,
                    "per_change": insert_stmt2.excluded.per_change,
                    "market_cap": insert_stmt2.excluded.market_cap,
                    "ttm_pe": insert_stmt2.excluded.ttm_pe,
                    "net_profit": insert_stmt2.excluded.net_profit,
                    "net_profit_yoy": insert_stmt2.excluded.net_profit_yoy,
                    "tech_trend": insert_stmt2.excluded.tech_trend,
                    "mc_url": insert_stmt2.excluded.mc_url,
                    "categories": insert_stmt2.excluded.categories,
                    "last_updated": insert_stmt2.excluded.last_updated,
                },
            )
            await session.execute(stmt2)

        await session.commit()
        logger.info("market_local_sync: upserted %d categories (%d industries + %d sectors) and %d stocks",
                    len(category_rows), len(industry_groups), len(sector_groups), len(stock_rows))


def _market_local_sync() -> None:
    """Sync wrapper called by orchestrator/scheduler (sync context)."""
    from app.backgroundtasks._runtime import _run_async

    try:
        logger.info("market_local_sync: starting (local aggregator)")
        _run_async(_refresh_market_data_local_async())
        logger.info("market_local_sync: complete")
    except Exception:
        logger.exception("market_local_sync: unhandled exception; will retry next cycle")
