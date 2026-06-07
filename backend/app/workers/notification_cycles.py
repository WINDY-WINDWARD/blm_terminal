"""Watchlist notification cycles (audit C.1, A.12 part 1, A.13).

Each function in this module is a *cycle callable* — a single
unit of work executed by a daemon worker thread (see
``app.workers.notifications.watchlist_notification_worker``)
on a cron schedule.  The daemons own the cron-sleep loop and
the first-run guard; the cycles contain the actual business
logic.

Cycles here:

  - ``_ticker_indicator_notification_cycle`` — evaluates 15
    technical triggers (RSI, MACD, Bollinger, ATR, volatility,
    momentum, returns, streaks, 52W proximity) per watchlist
    symbol using pre-computed ``TickerScore`` cache + latest
    ``TickerDaily`` row.
  - ``_ticker_intraday_indicator_notification_cycle`` — same
    triggers evaluated against 1h / W / M ``TickerIntraday``
    rows plus daily RSI for MTF alignment.
  - ``_notification_cycle_full`` — during market hours: 9
    triggers (52W, volume, top gainers/losers, deals, insider)
    for every watchlist symbol.
  - ``_notification_cycle_reduced`` — after hours: only deals
    + insider trades (market-hour triggers would all be empty).

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).
The ``_build_alerts`` helper used by the NSE cycles now lives in
``app.services.data_sync.notifications`` and is imported here.

A.13: ``_bg_impl._shutdown_event`` / ``_bg_impl._SyncSessionLocal``
replaced with direct canonical-home imports
(``app.backgroundtasks._runtime._shutdown_event``,
``app.database._SyncSessionLocal``).  Kept **lazy** (inside each
cycle function) so test ``mock.patch`` calls targeting these
helpers take effect at call time, and so we don't grow the module
top-level import surface.
"""
import logging
from datetime import datetime

from sqlalchemy import select

from app.services.data_sync import (
    cleanup as _cleanup_mod,
    deal_significance as _deal_sig_mod,
    insider_trades as _insider_trades_mod,
    nse_parsing as _nse_parsing_mod,
    notifications as _notifications_mod,
)


logger = logging.getLogger(__name__)


def _ticker_indicator_notification_cycle() -> None:
    """Generate indicator-based notifications for all watchlist symbols.

    Evaluates all 15 technical trigger types (RSI, MACD, Bollinger, ATR,
    volatility, momentum, returns, streaks, 52W proximity) against the latest
    stored ticker_daily indicator columns.

    Momentum and 1W return alerts are read from the pre-computed `ticker_scores`
    cache (populated by Stage 4 `_ticker_scores_sync`), NOT from
    `get_momentum_score`/`get_returns`. Those services do O(universe_size) work
    per call, which previously caused the per-symbol loop to hang for hours when
    invoked across the 65-symbol watchlist.
    """
    from app.backgroundtasks._runtime import _shutdown_event
    from app.database import _SyncSessionLocal
    from app.models.ticker import TickerDaily, TickerScore
    from app.models.stockuniverse import StockUniverse

    try:
        logger.info("ticker_indicator_notification_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = _notifications_mod.get_notif_config()
        rsi_oversold_thr   = float(cfg["notif.rsi_oversold_threshold"])
        rsi_overbought_thr = float(cfg["notif.rsi_overbought_threshold"])
        vol_spike_ratio    = float(cfg["notif.volatility_spike_ratio"])
        atr_exp_thr        = float(cfg["notif.atr_expansion_threshold"])
        momentum_thr       = float(cfg["notif.momentum_surge_threshold"])
        return_1w_thr      = float(cfg["notif.return_1w_spike_threshold"])
        streak_thr         = int(cfg["notif.streak_days_threshold"])
        near52w_thr        = float(cfg["notif.near_52w_threshold"])

        symbols_by_watchlist = _notifications_mod._get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("ticker_indicator_notification_cycle: watchlist is empty, skipping")
            return

        all_symbols = list({s for wl_symbols in symbols_by_watchlist.values() for s in wl_symbols})
        total_symbols = len(all_symbols)
        logger.info("ticker_indicator_notification_cycle: starting for %d symbols in %d watchlists",
                    total_symbols, len(symbols_by_watchlist))

        # Load TickerScore cache once for the whole cycle. Stage 4
        # `_ticker_scores_sync` pre-computes momentum_score and return_1w for
        # every symbol; reading from this cache keeps the cycle O(watchlist)
        # instead of O(watchlist × universe).
        scores_cache: dict[str, TickerScore] = {}
        try:
            with _SyncSessionLocal() as db:
                rows = db.execute(
                    select(TickerScore).where(TickerScore.compute_date == today_date)
                )
                for row in rows.scalars():
                    scores_cache[row.symbol] = row
            logger.info("ticker_indicator_notification_cycle: loaded %d ticker_scores from cache",
                        len(scores_cache))
        except Exception as e:
            logger.warning("ticker_indicator_notification_cycle: failed to load ticker_scores: %s", e)

        seen_today = _notifications_mod._get_seen_today()
        pending: list[dict] = []
        processed = 0
        alerts_generated = 0

        for symbol in all_symbols:
            if _shutdown_event.is_set():
                logger.info("ticker_indicator_notification_cycle: shutdown requested, stopping at %d/%d symbols",
                            processed, total_symbols)
                return

            processed += 1
            if processed % 20 == 0 or processed == 1:
                logger.info("ticker_indicator_notification_cycle: progress %d/%d symbols (%.0f%%)",
                            processed, total_symbols, processed / total_symbols * 100)

            try:
                with _SyncSessionLocal() as db:
                    # Last 10 candles for streak + indicator comparison
                    rows = list(
                        db.execute(
                            select(TickerDaily)
                            .where(TickerDaily.symbol == symbol)
                            .order_by(TickerDaily.date.desc())
                            .limit(10)
                        ).scalars()
                    )
                    su_row = db.execute(
                        select(StockUniverse).where(StockUniverse.symbol == symbol)
                    ).scalar_one_or_none()

                if not rows or len(rows) < 2:
                    continue

                rows_asc = list(reversed(rows))  # oldest → newest
                latest = rows_asc[-1]
                prev   = rows_asc[-2]

                # --- consecutive day streak (close vs open) ---
                up_streak = 0
                dn_streak = 0
                for r in reversed(rows_asc):
                    if r.close is None or r.open is None:
                        break
                    if r.close > r.open:
                        if dn_streak > 0:
                            break
                        up_streak += 1
                    elif r.close < r.open:
                        if up_streak > 0:
                            break
                        dn_streak += 1
                    else:
                        break  # flat day breaks streak

                # --- 52W proximity ---
                pct_from_52w_high: float | None = None
                pct_from_52w_low:  float | None = None
                if su_row and su_row.high_52w and su_row.low_52w and latest.close:
                    if su_row.high_52w > 0:
                        pct_from_52w_high = (latest.close - su_row.high_52w) / su_row.high_52w * 100
                    if su_row.low_52w > 0:
                        pct_from_52w_low  = (latest.close - su_row.low_52w) / su_row.low_52w  * 100

                # --- momentum and return_1w from pre-computed TickerScore cache ---
                # Avoid get_momentum_score/get_returns: those are O(universe_size)
                # per call and were the root cause of the Stage 3 hang.
                ts = scores_cache.get(symbol)
                momentum_score = ts.momentum_score if ts else None
                return_1w      = ts.return_1w      if ts else None

                # --- build alerts per watchlist that contains this symbol ---
                for wl_id, wl_symbols in symbols_by_watchlist.items():
                    if symbol not in wl_symbols:
                        continue

                    alerts: list[tuple[str, str]] = []

                    # RSI
                    if latest.rsi_14 is not None:
                        if latest.rsi_14 < rsi_oversold_thr:
                            alerts.append(("rsi_oversold",
                                f"{symbol} RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
                        elif latest.rsi_14 > rsi_overbought_thr:
                            alerts.append(("rsi_overbought",
                                f"{symbol} RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

                    # MACD crossover (requires 2 rows with stored histograms)
                    if latest.macd_histogram is not None and prev.macd_histogram is not None:
                        if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
                            alerts.append(("macd_bullish_cross",
                                f"{symbol} MACD bullish crossover "
                                f"({prev.macd_histogram:.4f} → {latest.macd_histogram:.4f})"))
                        elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
                            alerts.append(("macd_bearish_cross",
                                f"{symbol} MACD bearish crossover "
                                f"({prev.macd_histogram:.4f} → {latest.macd_histogram:.4f})"))

                    # Bollinger Bands
                    if latest.bb_squeeze == "Y":
                        alerts.append(("bb_squeeze_alert",
                            f"{symbol} Bollinger Band squeeze detected (bb_width={latest.bb_width})"))
                    if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
                        alerts.append(("bb_upper_break",
                            f"{symbol} close ₹{latest.close} broke above BB upper ₹{latest.bb_upper}"))
                    if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
                        alerts.append(("bb_lower_break",
                            f"{symbol} close ₹{latest.close} broke below BB lower ₹{latest.bb_lower}"))

                    # Volatility
                    if (latest.hv_20 is not None and latest.hv_60 is not None
                            and latest.hv_60 > 0
                            and latest.hv_20 > latest.hv_60 * vol_spike_ratio):
                        alerts.append(("volatility_spike",
                            f"{symbol} HV20 {latest.hv_20:.1f}% > {vol_spike_ratio}× HV60 {latest.hv_60:.1f}%"))
                    if latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
                        alerts.append(("atr_expansion",
                            f"{symbol} ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

                    # Momentum / returns (read from TickerScore cache)
                    if momentum_score is not None and momentum_score > momentum_thr:
                        alerts.append(("momentum_surge",
                            f"{symbol} momentum score {momentum_score:.1f} > {momentum_thr}"))
                    if return_1w is not None and return_1w > return_1w_thr:
                        alerts.append(("return_1w_spike",
                            f"{symbol} 1W return {return_1w:+.1f}% > {return_1w_thr}%"))

                    # Streaks
                    if up_streak >= streak_thr:
                        alerts.append(("streak_up_5d",
                            f"{symbol} up {up_streak} consecutive days"))
                    if dn_streak >= streak_thr:
                        alerts.append(("streak_down_5d",
                            f"{symbol} down {dn_streak} consecutive days"))

                    # 52W proximity
                    if pct_from_52w_high is not None and -near52w_thr <= pct_from_52w_high <= 0:
                        alerts.append(("near_52w_high",
                            f"{symbol} within {near52w_thr}% of 52W high ({pct_from_52w_high:+.1f}%)"))
                    if pct_from_52w_low is not None and 0 <= pct_from_52w_low <= near52w_thr:
                        alerts.append(("near_52w_low",
                            f"{symbol} within {near52w_thr}% of 52W low ({pct_from_52w_low:+.1f}%)"))

                    for trigger_type, message in alerts:
                        key = (wl_id, symbol, trigger_type)
                        if key in seen_today:
                            continue
                        seen_today.add(key)
                        pending.append({
                            "watchlist_id":   wl_id,
                            "symbol":         symbol,
                            "exchange":       "NSE",
                            "trigger_type":   trigger_type,
                            "message":        message,
                            "triggered_at":   now,
                            "triggered_date": today_date,
                            "is_read":        False,
                        })
                        alerts_generated += 1

            except Exception:
                logger.exception(f"ticker_indicator_notification_cycle: failed for {symbol}")

        if pending:
            _notifications_mod._bulk_upsert_notifications(pending)
            logger.info(
                "ticker_indicator_notification_cycle: processed %d symbols, generated %d notifications, upserted %d",
                processed, alerts_generated, len(pending)
            )
        else:
            logger.info("ticker_indicator_notification_cycle: processed %d symbols, no new notifications", processed)

    except Exception:
        logger.exception("ticker_indicator_notification_cycle: unhandled exception")


def _ticker_intraday_indicator_notification_cycle() -> None:
    """Generate indicator-based notifications for watchlist symbols using intraday data.

    Evaluates RSI, MACD, Bollinger, ATR, and MTF alignment triggers against
    the latest stored ticker_intraday indicator columns for 1h, W, and M.
    """
    from app.models.ticker import TickerIntraday, TickerDaily
    from app.models.stockuniverse import StockUniverse

    try:
        logger.info("ticker_intraday_indicator_notification_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = _notifications_mod.get_notif_config()
        rsi_oversold_thr   = float(cfg.get("notif.rsi_oversold_threshold", "30.0"))
        rsi_overbought_thr = float(cfg.get("notif.rsi_overbought_threshold", "70.0"))
        atr_exp_thr        = float(cfg.get("notif.atr_expansion_threshold", "4.0"))

        symbols_by_watchlist = _notifications_mod._get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("ticker_intraday_indicator_notification_cycle: watchlist empty, skipping")
            return

        all_symbols = list({s for wl_symbols in symbols_by_watchlist.values() for s in wl_symbols})
        total_symbols = len(all_symbols)

        seen_today = _notifications_mod._get_seen_today()
        pending: list[dict] = []
        processed = 0
        alerts_generated = 0

        for symbol in all_symbols:
            if _shutdown_event.is_set():
                return

            processed += 1
            if processed % 20 == 0 or processed == 1:
                logger.info("ticker_intraday_indicator_notification_cycle: progress %d/%d", processed, total_symbols)

            try:
                # Load latest 2 rows per interval for crossover detection
                intraday_rows: dict[str, list] = {}
                with _SyncSessionLocal() as db:
                    for interval in ("1h", "W", "M"):
                        rows = list(
                            db.execute(
                                select(TickerIntraday)
                                .where(TickerIntraday.symbol == symbol)
                                .where(TickerIntraday.interval == interval)
                                .order_by(TickerIntraday.timestamp.desc())
                                .limit(2)
                            ).scalars()
                        )
                        if rows:
                            intraday_rows[interval] = list(reversed(rows))  # oldest → newest

                    su_row = db.execute(
                        select(StockUniverse).where(StockUniverse.symbol == symbol)
                    ).scalar_one_or_none()

                if not intraday_rows:
                    continue

                # Build per-watchlist alerts
                for wl_id, wl_symbols in symbols_by_watchlist.items():
                    if symbol not in wl_symbols:
                        continue

                    alerts: list[tuple[str, str]] = []

                    for interval, rows in intraday_rows.items():
                        if len(rows) < 1:
                            continue
                        latest = rows[-1]
                        prev = rows[-2] if len(rows) >= 2 else None
                        sfx = f"_{interval}"

                        # RSI
                        if latest.rsi_14 is not None:
                            if latest.rsi_14 < rsi_oversold_thr:
                                alerts.append((f"rsi_oversold{sfx}",
                                    f"{symbol} [{interval}] RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
                            elif latest.rsi_14 > rsi_overbought_thr:
                                alerts.append((f"rsi_overbought{sfx}",
                                    f"{symbol} [{interval}] RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

                        # MACD crossover
                        if prev and latest.macd_histogram is not None and prev.macd_histogram is not None:
                            if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
                                alerts.append((f"macd_bullish_cross{sfx}",
                                    f"{symbol} [{interval}] MACD bullish crossover"))
                            elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
                                alerts.append((f"macd_bearish_cross{sfx}",
                                    f"{symbol} [{interval}] MACD bearish crossover"))

                        # Bollinger Bands
                        if latest.bb_squeeze == "Y":
                            alerts.append((f"bb_squeeze_alert{sfx}",
                                f"{symbol} [{interval}] BB squeeze (width={latest.bb_width})"))
                        if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
                            alerts.append((f"bb_upper_break{sfx}",
                                f"{symbol} [{interval}] close > BB upper"))
                        if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
                            alerts.append((f"bb_lower_break{sfx}",
                                f"{symbol} [{interval}] close < BB lower"))

                        # ATR expansion (1h only — meaningful for intraday)
                        if interval == "1h" and latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
                            alerts.append((f"atr_expansion{sfx}",
                                f"{symbol} [1h] ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

                    # MTF alignment (daily + weekly + monthly RSI all same direction)
                    daily_rsi = None
                    weekly_rsi = None
                    monthly_rsi = None
                    if "1h" in intraday_rows:
                        # 1h is not used for MTF; use daily from ticker_daily if available
                        with _SyncSessionLocal() as db:
                            daily_row = db.execute(
                                select(TickerDaily.rsi_14)
                                .where(TickerDaily.symbol == symbol)
                                .order_by(TickerDaily.date.desc())
                                .limit(1)
                            ).scalar_one_or_none()
                            daily_rsi = daily_row
                    if "W" in intraday_rows:
                        weekly_rsi = intraday_rows["W"][-1].rsi_14
                    if "M" in intraday_rows:
                        monthly_rsi = intraday_rows["M"][-1].rsi_14

                    if daily_rsi is not None and weekly_rsi is not None and monthly_rsi is not None:
                        if daily_rsi > 50 and weekly_rsi > 50 and monthly_rsi > 50:
                            alerts.append(("mtf_bullish_alignment",
                                f"{symbol} MTF bullish: D={daily_rsi:.1f} W={weekly_rsi:.1f} M={monthly_rsi:.1f} all > 50"))
                        elif daily_rsi < 50 and weekly_rsi < 50 and monthly_rsi < 50:
                            alerts.append(("mtf_bearish_alignment",
                                f"{symbol} MTF bearish: D={daily_rsi:.1f} W={weekly_rsi:.1f} M={monthly_rsi:.1f} all < 50"))

                    for trigger_type, message in alerts:
                        key = (wl_id, symbol, trigger_type)
                        if key in seen_today:
                            continue
                        seen_today.add(key)
                        pending.append({
                            "watchlist_id":   wl_id,
                            "symbol":         symbol,
                            "exchange":       "NSE",
                            "trigger_type":   trigger_type,
                            "message":        message,
                            "triggered_at":   now,
                            "triggered_date": today_date,
                            "is_read":        False,
                        })
                        alerts_generated += 1

            except Exception:
                logger.exception("ticker_intraday_indicator_notification_cycle: failed for %s", symbol)

        if pending:
            _notifications_mod._bulk_upsert_notifications(pending)
            logger.info(
                "ticker_intraday_indicator_notification_cycle: processed %d symbols, generated %d notifications, upserted %d",
                processed, alerts_generated, len(pending)
            )
        else:
            logger.info("ticker_intraday_indicator_notification_cycle: processed %d symbols, no new notifications", processed)

    except Exception:
        logger.exception("ticker_intraday_indicator_notification_cycle: unhandled exception")


def _notification_cycle_full() -> None:
    """Full cycle: check all 9 trigger types. Called in a worker thread."""
    from app.backgroundtasks._runtime import _shutdown_event

    try:
        logger.info("notification_cycle_full: starting")
        now = datetime.now()
        today_date = now.date()

        symbols_by_watchlist = _notifications_mod._get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("notification_cycle_full: watchlist is empty, skipping")
            return

        seen_today = _notifications_mod._get_seen_today()
        pending: list[dict] = []

        # Fetch NSE data with error handling
        high52_raw = _nse_parsing_mod._safe_fetch_52week_high()
        low52_raw = _nse_parsing_mod._safe_fetch_52week_low()
        vol_raw = _nse_parsing_mod._safe_fetch_volume_gainers()
        gainers_df = _nse_parsing_mod._safe_fetch_top_gainers()
        losers_df = _nse_parsing_mod._safe_fetch_top_losers()
        deals_raw = _nse_parsing_mod._safe_fetch_largedeal_snapshot()

        # Parse raw data
        high52_data = _nse_parsing_mod._parse_52week_data(high52_raw)
        low52_data = _nse_parsing_mod._parse_52week_data(low52_raw)
        vol_data = _nse_parsing_mod._parse_volume_gainers(vol_raw)
        deals = _deal_sig_mod._parse_largedeal_snapshot(deals_raw)

        # Read deal significance thresholds
        cfg = _notifications_mod.get_notif_config()
        deal_sig_pct = float(cfg["notif.deal_significance_pct"])
        deal_abs_cr  = float(cfg["notif.deal_absolute_threshold_cr"])

        # Pre-fetch deal significance data (single DB round-trip)
        deal_symbols = set(deals.keys())
        deal_mkt_caps = _deal_sig_mod._fetch_deal_market_caps(deal_symbols)
        short_deals   = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px = _deal_sig_mod._fetch_short_deal_close_prices(short_deals)

        # Cache insider trades per symbol
        insider_cache: dict[str, list[dict]] = {}

        for wl_id, symbols in symbols_by_watchlist.items():
            for symbol in symbols:
                # Get insider trades for this symbol (cached)
                if symbol not in insider_cache:
                    insider_cache[symbol] = _insider_trades_mod._fetch_insider_trades_cached(symbol)

                # Build all alerts for this symbol
                alerts = _notifications_mod._build_alerts(
                    symbol=symbol,
                    high52_data=high52_data,
                    low52_data=low52_data,
                    vol_data=vol_data,
                    gainers_df=gainers_df,
                    losers_df=losers_df,
                    deals_by_symbol=deals,
                    insider_trades=insider_cache[symbol],
                    deal_significance_pct=deal_sig_pct,
                    deal_absolute_threshold_cr=deal_abs_cr,
                    deal_market_caps_cr=deal_mkt_caps,
                    deal_short_prices=deal_short_px,
                )

                # Add to pending if not seen today
                for trigger_type, message in alerts:
                    key = (wl_id, symbol, trigger_type)
                    if key in seen_today:
                        continue
                    seen_today.add(key)
                    pending.append({
                        "watchlist_id": wl_id,
                        "symbol": symbol,
                        "exchange": "NSE",
                        "trigger_type": trigger_type,
                        "message": message,
                        "triggered_at": now,
                        "triggered_date": today_date,
                        "is_read": False,
                    })

                if _shutdown_event.is_set():
                    return

        if pending:
            _notifications_mod._bulk_upsert_notifications(pending)
            logger.info("notification_cycle_full: upserted %d notifications", len(pending))
        else:
            logger.info("notification_cycle_full: no new notifications")

        _cleanup_mod._run_cleanup_if_due()
    except Exception:
        logger.exception("notification_cycle_full: unhandled exception")


def _notification_cycle_reduced() -> None:
    """Reduced cycle: deals + insider only. Outside market hours."""
    from app.backgroundtasks._runtime import _shutdown_event

    try:
        logger.info("notification_cycle_reduced: starting")
        now = datetime.now()
        today_date = now.date()

        symbols_by_watchlist = _notifications_mod._get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("notification_cycle_reduced: watchlist is empty, skipping")
            return

        seen_today = _notifications_mod._get_seen_today()
        pending: list[dict] = []

        # Only fetch deals (market-hour triggers omitted)
        deals_raw = _nse_parsing_mod._safe_fetch_largedeal_snapshot()
        deals = _deal_sig_mod._parse_largedeal_snapshot(deals_raw)

        # Read deal significance thresholds
        cfg = _notifications_mod.get_notif_config()
        deal_sig_pct = float(cfg["notif.deal_significance_pct"])
        deal_abs_cr  = float(cfg["notif.deal_absolute_threshold_cr"])

        # Pre-fetch deal significance data
        deal_symbols  = set(deals.keys())
        deal_mkt_caps = _deal_sig_mod._fetch_deal_market_caps(deal_symbols)
        short_deals   = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px = _deal_sig_mod._fetch_short_deal_close_prices(short_deals)

        insider_cache: dict[str, list[dict]] = {}

        for wl_id, symbols in symbols_by_watchlist.items():
            for symbol in symbols:
                # Get insider trades for this symbol (cached)
                if symbol not in insider_cache:
                    insider_cache[symbol] = _insider_trades_mod._fetch_insider_trades_cached(symbol)

                # Build alerts (only deals + insider)
                alerts = _notifications_mod._build_alerts(
                    symbol=symbol,
                    deals_by_symbol=deals,
                    insider_trades=insider_cache[symbol],
                    deal_significance_pct=deal_sig_pct,
                    deal_absolute_threshold_cr=deal_abs_cr,
                    deal_market_caps_cr=deal_mkt_caps,
                    deal_short_prices=deal_short_px,
                )

                # Add to pending if not seen today
                for trigger_type, message in alerts:
                    key = (wl_id, symbol, trigger_type)
                    if key in seen_today:
                        continue
                    seen_today.add(key)
                    pending.append({
                        "watchlist_id": wl_id,
                        "symbol": symbol,
                        "exchange": "NSE",
                        "trigger_type": trigger_type,
                        "message": message,
                        "triggered_at": now,
                        "triggered_date": today_date,
                        "is_read": False,
                    })

                if _shutdown_event.is_set():
                    return

        if pending:
            _notifications_mod._bulk_upsert_notifications(pending)
            logger.info("notification_cycle_reduced: upserted %d notifications", len(pending))
        _cleanup_mod._run_cleanup_if_due()
    except Exception:
        logger.exception("notification_cycle_reduced: unhandled exception")
