"""Watchlist + global notification helpers (Phase C.1, A.12 part 1).

This module owns the *sync* notification helpers that cycles call
every few minutes to produce alerts:

  - ``_get_watchlist_symbols`` — group watchlist rows by watchlist_id
  - ``_get_seen_today`` / ``_get_global_seen_today`` — dedupe set
    (avoid re-firing the same trigger within a single trading day)
  - ``_bulk_upsert_notifications`` / ``_bulk_upsert_global_notifications`` —
    single-batch insert with ``ON CONFLICT DO NOTHING`` on the
    unique (watchlist_id, symbol, trigger_type, triggered_date)
    constraint
  - ``get_notif_config`` — read ``notif.*`` thresholds from
    ``system_config`` with hardcoded fallbacks
  - ``_build_alerts`` — pure function that turns a single symbol +
    pre-fetched NSE data into a list of ``(trigger_type, message)``

The cycle functions that actually *use* these helpers (and the
surrounding pipeline / shutdown / sleep state) live in
``app.workers.cycles`` to keep this module pure (no global
worker state).

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).
"""
import logging
from datetime import datetime, date
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import _SyncSessionLocal
from app.models.notification import Notification, GlobalNotification
from app.models.system_config import SystemConfig
from app.models.watchlist import WatchlistItem
from app.services.data_sync.deal_significance import (
    DealRecord,
    _is_recent,
    _is_deal_significant,
)


logger = logging.getLogger(__name__)


NOTIFICATION_CHECK_INTERVAL = 5 * 60       # 5 minutes  (market hours)
AFTER_HOURS_INTERVAL = 30 * 60             # 30 minutes (outside market hours)
DAILY_NOTIFICATION_WINDOW_DAYS = 7          # lookback for deals and insider trades


def _get_watchlist_symbols() -> dict[int, list[str]]:
    """Return all watchlist items grouped by watchlist_id."""
    with _SyncSessionLocal() as session:
        result = session.execute(select(WatchlistItem.watchlist_id, WatchlistItem.symbol))
        rows = result.fetchall()
    grouped: dict[int, list[str]] = {}
    for wl_id, symbol in rows:
        grouped.setdefault(wl_id, []).append(symbol.upper())
    return grouped


def _get_seen_today() -> set[tuple[int, str, str]]:
    """Return {(watchlist_id, symbol, trigger_type)} for all unread notifications today."""
    today = datetime.now().date()
    with _SyncSessionLocal() as session:
        rows = session.execute(
            select(Notification.watchlist_id, Notification.symbol, Notification.trigger_type)
            .where(
                Notification.triggered_date == today,
                Notification.is_read == False,
            )
        )
        return {(r[0], r[1], r[2]) for r in rows}


def _bulk_upsert_notifications(rows: list[dict]) -> None:
    """Insert notification rows, skipping duplicates via UniqueConstraint.

    rows is a list of plain dicts keyed by column name — NOT ORM objects.
    Using ORM object __dict__ would include SQLAlchemy internal state keys,
    causing the insert to fail or behave unexpectedly.
    """
    if not rows:
        return
    with _SyncSessionLocal() as session:
        stmt = (
            sqlite_insert(Notification)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["watchlist_id", "symbol", "trigger_type", "triggered_date"]
            )
        )
        session.execute(stmt)
        session.commit()


def _get_global_seen_today() -> set[tuple[str, str]]:
    """Return {(symbol, trigger_type)} for all unread global notifications today."""
    today = datetime.now().date()
    with _SyncSessionLocal() as session:
        rows = session.execute(
            select(GlobalNotification.symbol, GlobalNotification.trigger_type)
            .where(
                GlobalNotification.triggered_date == today,
                GlobalNotification.is_read == False,
            )
        )
        return {(r[0], r[1]) for r in rows}


def _bulk_upsert_global_notifications(rows: list[dict]) -> None:
    """Insert global notification rows, skipping duplicates via UniqueConstraint."""
    if not rows:
        return
    with _SyncSessionLocal() as session:
        stmt = (
            sqlite_insert(GlobalNotification)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["symbol", "trigger_type", "triggered_date"]
            )
        )
        session.execute(stmt)
        session.commit()


def get_notif_config() -> dict:
    """Read notif.* threshold values from system_config with hardcoded fallbacks."""
    DEFAULTS: dict = {
        "notif.rsi_oversold_threshold":        30.0,
        "notif.rsi_overbought_threshold":      70.0,
        "notif.volatility_spike_ratio":         1.5,
        "notif.atr_expansion_threshold":        4.0,
        "notif.momentum_surge_threshold":      70.0,
        "notif.return_1w_spike_threshold":     10.0,
        "notif.streak_days_threshold":          5.0,
        "notif.near_52w_threshold":             3.0,
        # Deal significance thresholds
        "notif.deal_significance_pct":          0.05,
        "notif.deal_absolute_threshold_cr":     2.0,
    }
    try:
        with _SyncSessionLocal() as db:
            rows = db.execute(
                select(SystemConfig.key, SystemConfig.value)
                .where(SystemConfig.key.like("notif.%"))
            ).fetchall()
            db_vals: dict = {row[0]: row[1] for row in rows}
    except Exception:
        logger.warning("get_notif_config: failed to read system_config, using defaults")
        db_vals = {}

    config: dict = {}
    for key, default in DEFAULTS.items():
        raw = db_vals.get(key)
        if raw is not None:
            try:
                config[key] = type(default)(raw)
            except (ValueError, TypeError):
                config[key] = default
        else:
            config[key] = default
    return config


def _build_alerts(
    symbol: str,
    high52_data: dict | None = None,
    low52_data: dict | None = None,
    vol_data: dict | None = None,
    gainers_df: pd.DataFrame | None = None,
    losers_df: pd.DataFrame | None = None,
    deals_by_symbol: dict[str, list[DealRecord]] | None = None,
    insider_trades: list[dict] | None = None,
    deal_significance_pct: float = 0.05,
    deal_absolute_threshold_cr: float = 2.0,
    deal_market_caps_cr: dict[str, float] | None = None,
    deal_short_prices: dict[str, dict[str, float]] | None = None,
) -> list[tuple[str, str]]:
    """Build list of (trigger_type, message) tuples for a symbol."""
    alerts: list[tuple[str, str]] = []

    # 52-week high/low
    if high52_data and symbol in high52_data:
        row = high52_data[symbol]
        price = row.get("ltp") or row.get("new52WHL") or "—"
        alerts.append(("52w_high_breakout", f"{symbol} hit a new 52-week HIGH @ ₹{price}"))

    if low52_data and symbol in low52_data:
        row = low52_data[symbol]
        price = row.get("ltp") or row.get("new52WHL") or "—"
        alerts.append(("52w_low_breakout", f"{symbol} hit a new 52-week LOW @ ₹{price}"))

    # Volume breakout
    if vol_data and symbol in vol_data:
        ratio = vol_data[symbol].get("week1volChange", 0)
        alerts.append(("volume_breakout", f"{symbol} showing volume breakout ({ratio:+.0f}x avg)"))

    # Top gainers/losers (DataFrame)
    def _row_pchg(row) -> float:
        """Read % change from either pChange (legacy) or perChange (new API)."""
        return getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0

    if gainers_df is not None:
        for row in gainers_df.itertuples():
            if row.symbol == symbol:
                pchg = _row_pchg(row)
                if pchg:
                    alerts.append(("top_gainer", f"{symbol} among TOP GAINERS ({pchg:+.1f}%)"))
                break

    if losers_df is not None:
        for row in losers_df.itertuples():
            if row.symbol == symbol:
                pchg = _row_pchg(row)
                if pchg:
                    alerts.append(("top_loser", f"{symbol} among TOP LOSERS ({pchg:+.1f}%)"))
                break

    # Deals (bulk/block/short) — O(1) lookup via pre-indexed dict.
    # Only fire for trades whose value is significant relative to market cap.
    if deals_by_symbol and symbol in deals_by_symbol:
        _mkt_caps = deal_market_caps_cr or {}
        _short_px = deal_short_prices or {}
        for deal in deals_by_symbol[symbol]:
            if not _is_recent(deal.date, DAILY_NOTIFICATION_WINDOW_DAYS):
                continue
            is_sig, trade_val_cr = _is_deal_significant(
                deal, _short_px, _mkt_caps,
                deal_significance_pct, deal_absolute_threshold_cr,
            )
            if not is_sig:
                continue
            val_str = f" = ₹{trade_val_cr:.1f} Cr" if trade_val_cr > 0 else ""
            alerts.append((
                f"{deal.deal_type}_deal",
                f"{symbol} — {deal.deal_type} deal: {deal.qty:,} shares @ ₹{deal.watp}{val_str}",
            ))

    # Insider trades (from screener.in)
    if insider_trades:
        for trade in insider_trades:
            # trade is a dict with "direction": "up"/"down"
            direction = (trade.get("direction") or "").lower()
            if direction == "up":
                t_type = "insider_buy"
            elif direction == "down":
                t_type = "insider_sell"
            else:
                t_type = f"insider_{direction}" if direction else "insider_unknown"

            person = trade.get("person", "Unknown")
            qty = trade.get("quantity", 0)
            alerts.append((
                t_type,
                f"{symbol} insider {direction}: {person} {direction} {qty:,} shares"
            ))

    return alerts
