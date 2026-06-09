"""Deal-significance helpers for bulk/block/short NSE deals (Phase C.1, A.12 part 1).

This module owns the ``DealRecord`` dataclass and the surrounding
machinery used by notification cycles to decide whether a deal is
significant enough to alert on:

  - ``_coerce_int`` / ``_coerce_float`` / ``_is_recent`` — small
    NSE-format normalization helpers.
  - ``_parse_largedeal_snapshot`` — converts a raw NSE
    largedeal-snapshot payload into ``{symbol: [DealRecord, ...]}``.
  - ``_fetch_deal_market_caps`` / ``_fetch_short_deal_close_prices`` —
    bulk DB lookups required by ``_is_deal_significant``.
  - ``_is_deal_significant`` — applies the
    ``trade_value / market_cap >= pct`` heuristic with a Cr-absolute
    fallback.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select

from app.database import _SyncSessionLocal


logger = logging.getLogger(__name__)


@dataclass
class DealRecord:
    """Normalized deal record from NSE largedeal snapshot."""
    symbol: str
    deal_type: str       # "bulk", "block", "short"
    date: str            # raw date string from NSE (e.g., "12-Mar-2026")
    qty: int             # coerced from string
    watp: float          # coerced from string/null
    client_name: str | None
    buy_sell: str | None


def _coerce_int(val) -> int:
    """Coerce string/None to int safely."""
    if val is None:
        return 0
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _coerce_float(val) -> float:
    """Coerce string/None to float safely."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _is_recent(date_str: str | None, days: int) -> bool:
    """Check if a date string is within the last N days.

    Args:
        date_str: Date in NSE format "12-Mar-2026", or None
        days: Number of days to look back
    Returns:
        True if date is within the last `days` days, False otherwise
    """
    if not date_str:
        return False
    try:
        dt = datetime.strptime(date_str, "%d-%b-%Y").date()
        today = date.today()
        if dt > today:
            return False
        return (today - dt).days <= days
    except ValueError:
        logger.warning("Unparseable date: %s", date_str)
        return False


def _parse_largedeal_snapshot(snapshot: dict) -> dict[str, list[DealRecord]]:
    """Parse largedeal snapshot into dict of {symbol: [DealRecord, ...]}."""
    deals_by_symbol: dict[str, list[DealRecord]] = {}

    # Process bulk deals
    for item in snapshot.get("BULK_DEALS_DATA", []):
        if item.get("symbol"):
            symbol = item["symbol"].upper()
            deal = DealRecord(
                symbol=symbol,
                deal_type="bulk",
                date=item.get("date", ""),
                qty=_coerce_int(item.get("qty")),
                watp=_coerce_float(item.get("watp")),
                client_name=item.get("clientName"),
                buy_sell=item.get("buySell"),
            )
            deals_by_symbol.setdefault(symbol, []).append(deal)

    # Process block deals
    for item in snapshot.get("BLOCK_DEALS_DATA", []):
        if item.get("symbol"):
            symbol = item["symbol"].upper()
            deal = DealRecord(
                symbol=symbol,
                deal_type="block",
                date=item.get("date", ""),
                qty=_coerce_int(item.get("qty")),
                watp=_coerce_float(item.get("watp")),
                client_name=item.get("clientName"),
                buy_sell=item.get("buySell"),
            )
            deals_by_symbol.setdefault(symbol, []).append(deal)

    # Process short deals (short-selling, NOT insider trades)
    for item in snapshot.get("SHORT_DEALS_DATA", []):
        if item.get("symbol"):
            symbol = item["symbol"].upper()
            deal = DealRecord(
                symbol=symbol,
                deal_type="short",
                date=item.get("date", ""),
                qty=_coerce_int(item.get("qty")),
                watp=_coerce_float(item.get("watp")),
                client_name=item.get("clientName"),
                buy_sell=item.get("buySell"),
            )
            deals_by_symbol.setdefault(symbol, []).append(deal)

    return deals_by_symbol


def _fetch_deal_market_caps(symbols: set[str]) -> dict[str, float]:
    """Bulk-fetch market caps (Rs Cr) for deal symbols from MarketCategoryStock."""
    from app.models.marketcategory import MarketCategoryStock
    if not symbols:
        return {}
    try:
        with _SyncSessionLocal() as db:
            rows = db.execute(
                select(MarketCategoryStock.symbol, MarketCategoryStock.market_cap)
                .where(MarketCategoryStock.symbol.in_(symbols))
            ).fetchall()
        return {row[0]: float(row[1]) for row in rows if row[1] is not None}
    except Exception:
        logger.warning("_fetch_deal_market_caps: DB query failed, returning empty dict")
        return {}


def _fetch_short_deal_close_prices(
    short_deals: list["DealRecord"],
) -> dict[str, dict[str, float]]:
    """Fetch closing prices for short deals (which carry no watp) from TickerDaily.

    Returns: {symbol: {date_str: close_price}} where date_str is the original
    NSE format "12-Mar-2026".
    """
    from sqlalchemy import tuple_ as sa_tuple
    from app.models.ticker import TickerDaily

    pairs: list[tuple[str, date]] = []
    for deal in short_deals:
        if deal.deal_type != "short" or not deal.date:
            continue
        try:
            d = datetime.strptime(deal.date, "%d-%b-%Y").date()
            pairs.append((deal.symbol, d))
        except (ValueError, AttributeError):
            pass

    if not pairs:
        return {}

    try:
        result: dict[str, dict[str, float]] = {}
        unique_pairs = list({(sym, d) for sym, d in pairs})
        with _SyncSessionLocal() as db:
            rows = db.execute(
                select(TickerDaily.symbol, TickerDaily.date, TickerDaily.close).where(
                    sa_tuple(TickerDaily.symbol, TickerDaily.date).in_(unique_pairs)
                )
            ).all()
        for symbol, d, close in rows:
            if close is not None:
                date_str = d.strftime("%d-%b-%Y")
                result.setdefault(symbol, {})[date_str] = float(close)
        return result
    except Exception:
        logger.warning("_fetch_short_deal_close_prices: DB query failed")
        return {}


def _is_deal_significant(
    deal: "DealRecord",
    short_close_prices: dict[str, dict[str, float]],
    market_caps_cr: dict[str, float],
    significance_pct: float,
    absolute_threshold_cr: float,
) -> tuple[bool, float]:
    """Check whether a deal is significant enough to generate an alert.

    Significance is defined as:
      trade_value >= significance_pct * market_cap
    with a fallback of trade_value >= absolute_threshold_cr (Rs Cr) when the
    market cap is unknown.

    Short deals carry no watp from NSE — their price is resolved from TickerDaily.

    Returns:
        (is_significant, trade_value_cr)
    """
    if deal.deal_type == "short":
        price = short_close_prices.get(deal.symbol, {}).get(deal.date, 0.0)
    else:
        price = deal.watp

    if price <= 0 or deal.qty <= 0:
        return False, 0.0

    trade_value_cr = (deal.qty * price) / 1e7  # Rs → Rs Cr

    market_cap_cr = market_caps_cr.get(deal.symbol)
    if market_cap_cr and market_cap_cr > 0:
        is_sig = (trade_value_cr / market_cap_cr) >= significance_pct
    else:
        is_sig = trade_value_cr >= absolute_threshold_cr

    return is_sig, trade_value_cr
