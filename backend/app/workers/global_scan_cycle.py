"""Global NSE scan cycle (audit C.1, A.12 part 1, A.13).

Single cycle callable: ``_global_scan_cycle`` — scans all NSE
stocks (not just watchlist) for technical and market alerts.  Runs
on a ``*/30 * * * *`` cron via the ``global_scan_worker`` daemon
in ``app.workers.notifications``.

Unlike the watchlist cycles (in
``app.workers.notification_cycles``), this cycle fires alerts into
the ``global_notifications`` table, which is consumed by the
global NSE scan feed on the frontend.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).

A.13: migrated ``_bg_impl`` references to canonical imports.

Helper symbols from the new data_sync modules are imported lazily inside
the cycle function so test ``mock.patch`` calls targeting the original
modules take effect at call time.
"""
import logging
from datetime import datetime

from sqlalchemy import select

from app.services.data_sync import (
    deal_significance as _deal_sig_mod,
    nse_parsing as _nse_parsing_mod,
    notifications as _notifications_mod,
)


logger = logging.getLogger(__name__)


GLOBAL_SCAN_BATCH_SIZE = 100
GLOBAL_SCAN_DELAY = 1.0


def _global_scan_cycle() -> None:
    """Generate alerts for all NSE stocks with indicator data.

    Scans all symbols in ticker_daily (not just watchlist), evaluates:
    - Technical indicators (RSI, MACD, Bollinger, ATR, volatility, streaks, 52W proximity)
    - Live NSE triggers (52W high/low, volume breakout, top gainer/loser)
    - Deal triggers (bulk/block/short deals)
    - Momentum triggers (momentum_surge, return_1w_spike) from ticker_scores cache
    """
    from app.backgroundtasks._runtime import (
        _shutdown_event,
        _sleep_interruptible,
    )
    from app.database import _SyncSessionLocal
    from app.jobs.runner import update_job_status_sync
    from app.models.ticker import TickerDaily, TickerScore, TickerIntraday
    from app.models.stockuniverse import StockUniverse

    try:
        logger.info("global_scan_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = _notifications_mod.get_notif_config()
        rsi_oversold_thr = float(cfg["notif.rsi_oversold_threshold"])
        rsi_overbought_thr = float(cfg["notif.rsi_overbought_threshold"])
        vol_spike_ratio = float(cfg["notif.volatility_spike_ratio"])
        atr_exp_thr = float(cfg["notif.atr_expansion_threshold"])
        momentum_thr = float(cfg["notif.momentum_surge_threshold"])
        return_1w_thr = float(cfg["notif.return_1w_spike_threshold"])
        streak_thr = int(cfg["notif.streak_days_threshold"])
        near52w_thr = float(cfg["notif.near_52w_threshold"])
        deal_sig_pct = float(cfg["notif.deal_significance_pct"])
        deal_abs_cr  = float(cfg["notif.deal_absolute_threshold_cr"])

        with _SyncSessionLocal() as db:
            result = db.execute(
                select(TickerDaily.symbol)
                .where(TickerDaily.indicators_updated_at.isnot(None))
                .distinct()
            )
            all_symbols = [row[0] for row in result.fetchall()]

        total_symbols = len(all_symbols)
        if total_symbols == 0:
            logger.info("global_scan_cycle: no symbols with indicator data, skipping")
            return

        logger.info("global_scan_cycle: starting for %d symbols", total_symbols)

        scores_cache: dict[str, TickerScore] = {}
        try:
            with _SyncSessionLocal() as db:
                rows = db.execute(
                    select(TickerScore)
                    .where(TickerScore.compute_date == today_date)
                )
                for row in rows.scalars():
                    scores_cache[row.symbol] = row
            logger.info("global_scan_cycle: loaded %d ticker_scores from cache", len(scores_cache))
        except Exception as e:
            logger.warning("global_scan_cycle: failed to load ticker_scores: %s", e)

        seen_today = _notifications_mod._get_global_seen_today()
        pending: list[dict] = []

        high52_raw = _nse_parsing_mod._safe_fetch_52week_high()
        low52_raw = _nse_parsing_mod._safe_fetch_52week_low()
        vol_raw = _nse_parsing_mod._safe_fetch_volume_gainers()
        gainers_df = _nse_parsing_mod._safe_fetch_top_gainers()
        losers_df = _nse_parsing_mod._safe_fetch_top_losers()
        deals_raw = _nse_parsing_mod._safe_fetch_largedeal_snapshot()

        high52_data = _nse_parsing_mod._parse_52week_data(high52_raw)
        low52_data = _nse_parsing_mod._parse_52week_data(low52_raw)
        vol_data = _nse_parsing_mod._parse_volume_gainers(vol_raw)
        deals = _deal_sig_mod._parse_largedeal_snapshot(deals_raw)

        # Pre-fetch deal significance data once for the whole scan
        deal_symbols      = set(deals.keys())
        deal_mkt_caps     = _deal_sig_mod._fetch_deal_market_caps(deal_symbols)
        short_deals_list  = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px     = _deal_sig_mod._fetch_short_deal_close_prices(short_deals_list)

        processed = 0
        alerts_generated = 0

        for i in range(0, total_symbols, GLOBAL_SCAN_BATCH_SIZE):
            if _shutdown_event.is_set():
                logger.info("global_scan_cycle: shutdown requested, stopping at %d/%d symbols",
                            processed, total_symbols)
                return

            batch = all_symbols[i:i + GLOBAL_SCAN_BATCH_SIZE]
            for symbol in batch:
                processed += 1

                if processed % 200 == 0 or processed == 1:
                    logger.info("global_scan_cycle: progress %d/%d symbols (%.0f%%)",
                                processed, total_symbols, processed / total_symbols * 100)

                try:
                    with _SyncSessionLocal() as db:
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

                    rows_asc = list(reversed(rows))
                    latest = rows_asc[-1]
                    prev = rows_asc[-2]

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
                            break

                    pct_from_52w_high: float | None = None
                    pct_from_52w_low: float | None = None
                    if su_row and su_row.high_52w and su_row.low_52w and latest.close:
                        if su_row.high_52w > 0:
                            pct_from_52w_high = (latest.close - su_row.high_52w) / su_row.high_52w * 100
                        if su_row.low_52w > 0:
                            pct_from_52w_low = (latest.close - su_row.low_52w) / su_row.low_52w * 100

                    alerts: list[tuple[str, str]] = []

                    if latest.rsi_14 is not None:
                        if latest.rsi_14 < rsi_oversold_thr:
                            alerts.append(("rsi_oversold",
                                f"{symbol} RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
                        elif latest.rsi_14 > rsi_overbought_thr:
                            alerts.append(("rsi_overbought",
                                f"{symbol} RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

                    if latest.macd_histogram is not None and prev.macd_histogram is not None:
                        if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
                            alerts.append(("macd_bullish_cross",
                                f"{symbol} MACD bullish crossover"))
                        elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
                            alerts.append(("macd_bearish_cross",
                                f"{symbol} MACD bearish crossover"))

                    if latest.bb_squeeze == "Y":
                        alerts.append(("bb_squeeze_alert",
                            f"{symbol} Bollinger Band squeeze (bb_width={latest.bb_width})"))
                    if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
                        alerts.append(("bb_upper_break",
                            f"{symbol} broke above BB upper"))
                    if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
                        alerts.append(("bb_lower_break",
                            f"{symbol} broke below BB lower"))

                    if (latest.hv_20 is not None and latest.hv_60 is not None
                            and latest.hv_60 > 0
                            and latest.hv_20 > latest.hv_60 * vol_spike_ratio):
                        alerts.append(("volatility_spike",
                            f"{symbol} HV20 > {vol_spike_ratio}x HV60"))
                    if latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
                        alerts.append(("atr_expansion",
                            f"{symbol} ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

                    if up_streak >= streak_thr:
                        alerts.append(("streak_up_5d", f"{symbol} up {up_streak} days"))
                    if dn_streak >= streak_thr:
                        alerts.append(("streak_down_5d", f"{symbol} down {dn_streak} days"))

                    if pct_from_52w_high is not None and -near52w_thr <= pct_from_52w_high <= 0:
                        alerts.append(("near_52w_high",
                            f"{symbol} within {near52w_thr}% of 52W high"))
                    if pct_from_52w_low is not None and 0 <= pct_from_52w_low <= near52w_thr:
                        alerts.append(("near_52w_low",
                            f"{symbol} within {near52w_thr}% of 52W low"))

                    # --- Intraday / Weekly / Monthly indicator triggers ---
                    try:
                        intraday_rows: dict[str, list] = {}
                        with _SyncSessionLocal() as db:
                            for interval in ("1h", "W", "M"):
                                iv_rows = list(
                                    db.execute(
                                        select(TickerIntraday)
                                        .where(TickerIntraday.symbol == symbol)
                                        .where(TickerIntraday.interval == interval)
                                        .where(TickerIntraday.indicators_updated_at.isnot(None))
                                        .order_by(TickerIntraday.timestamp.desc())
                                        .limit(2)
                                    ).scalars()
                                )
                                if iv_rows:
                                    intraday_rows[interval] = list(reversed(iv_rows))

                        for interval, iv_rows in intraday_rows.items():
                            if len(iv_rows) < 1:
                                continue
                            latest_iv = iv_rows[-1]
                            prev_iv = iv_rows[-2] if len(iv_rows) >= 2 else None
                            sfx = f"_{interval}"

                            if latest_iv.rsi_14 is not None:
                                if latest_iv.rsi_14 < rsi_oversold_thr:
                                    alerts.append((f"rsi_oversold{sfx}",
                                        f"{symbol} [{interval}] RSI oversold: {latest_iv.rsi_14:.1f}"))
                                elif latest_iv.rsi_14 > rsi_overbought_thr:
                                    alerts.append((f"rsi_overbought{sfx}",
                                        f"{symbol} [{interval}] RSI overbought: {latest_iv.rsi_14:.1f}"))

                            if prev_iv and latest_iv.macd_histogram is not None and prev_iv.macd_histogram is not None:
                                if prev_iv.macd_histogram < 0 and latest_iv.macd_histogram >= 0:
                                    alerts.append((f"macd_bullish_cross{sfx}",
                                        f"{symbol} [{interval}] MACD bullish crossover"))
                                elif prev_iv.macd_histogram > 0 and latest_iv.macd_histogram <= 0:
                                    alerts.append((f"macd_bearish_cross{sfx}",
                                        f"{symbol} [{interval}] MACD bearish crossover"))

                            if latest_iv.bb_squeeze == "Y":
                                alerts.append((f"bb_squeeze_alert{sfx}",
                                    f"{symbol} [{interval}] BB squeeze"))
                            if latest_iv.close is not None and latest_iv.bb_upper is not None and latest_iv.close > latest_iv.bb_upper:
                                alerts.append((f"bb_upper_break{sfx}",
                                    f"{symbol} [{interval}] close > BB upper"))
                            if latest_iv.close is not None and latest_iv.bb_lower is not None and latest_iv.close < latest_iv.bb_lower:
                                alerts.append((f"bb_lower_break{sfx}",
                                    f"{symbol} [{interval}] close < BB lower"))

                            if interval == "1h" and latest_iv.atr_percent is not None and latest_iv.atr_percent > atr_exp_thr:
                                alerts.append((f"atr_expansion{sfx}",
                                    f"{symbol} [1h] ATR% {latest_iv.atr_percent:.1f}% > {atr_exp_thr}%"))
                    except Exception:
                        logger.debug("global_scan_cycle: intraday eval failed for %s", symbol, exc_info=True)

                    ts = scores_cache.get(symbol)
                    if ts:
                        if ts.momentum_score is not None and ts.momentum_score > momentum_thr:
                            alerts.append(("momentum_surge",
                                f"{symbol} momentum {ts.momentum_score:.1f} > {momentum_thr}"))
                        if ts.return_1w is not None and ts.return_1w > return_1w_thr:
                            alerts.append(("return_1w_spike",
                                f"{symbol} 1w return {ts.return_1w:+.1f}% > {return_1w_thr}%"))

                    if high52_data and symbol in high52_data:
                        row = high52_data[symbol]
                        price = row.get("ltp") or row.get("new52WHL") or "—"
                        alerts.append(("52w_high_breakout", f"{symbol} 52W HIGH @ ₹{price}"))

                    if low52_data and symbol in low52_data:
                        row = low52_data[symbol]
                        price = row.get("ltp") or row.get("new52WHL") or "—"
                        alerts.append(("52w_low_breakout", f"{symbol} 52W LOW @ ₹{price}"))

                    if vol_data and symbol in vol_data:
                        ratio = vol_data[symbol].get("week1volChange", 0)
                        alerts.append(("volume_breakout", f"{symbol} vol {ratio:+.0f}x"))

                    if gainers_df is not None:
                        for row in gainers_df.itertuples():
                            if row.symbol == symbol:
                                pchg = getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0
                                if pchg:
                                    alerts.append(("top_gainer", f"{symbol} +{pchg:.1f}%"))
                                break

                    if losers_df is not None:
                        for row in losers_df.itertuples():
                            if row.symbol == symbol:
                                pchg = getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0
                                if pchg:
                                    alerts.append(("top_loser", f"{symbol} {pchg:.1f}%"))
                                break

                    if deals and symbol in deals:
                        for deal in deals[symbol]:
                            if not _deal_sig_mod._is_recent(deal.date, _notifications_mod.DAILY_NOTIFICATION_WINDOW_DAYS):
                                continue
                            is_sig, trade_val_cr = _deal_sig_mod._is_deal_significant(
                                deal, deal_short_px, deal_mkt_caps,
                                deal_sig_pct, deal_abs_cr,
                            )
                            if not is_sig:
                                continue
                            val_str = f" = ₹{trade_val_cr:.1f} Cr" if trade_val_cr > 0 else ""
                            alerts.append((
                                f"{deal.deal_type}_deal",
                                f"{symbol} {deal.deal_type} {deal.qty:,} @ ₹{deal.watp}{val_str}",
                            ))

                    for trigger_type, message in alerts:
                        key = (symbol, trigger_type)
                        if key in seen_today:
                            continue
                        seen_today.add(key)
                        pending.append({
                            "symbol": symbol,
                            "exchange": "NSE",
                            "trigger_type": trigger_type,
                            "message": message,
                            "triggered_at": now,
                            "triggered_date": today_date,
                            "is_read": False,
                        })
                        alerts_generated += 1

                except Exception:
                    logger.exception(f"global_scan_cycle: failed for {symbol}")

            if i + GLOBAL_SCAN_BATCH_SIZE < total_symbols:
                progress = int((processed / total_symbols) * 100)
                update_job_status_sync(
                    "job.global_scan", "running", progress=progress,
                    message=f"Scanning {processed}/{total_symbols} symbols, {alerts_generated} alerts",
                )
                if _sleep_interruptible(GLOBAL_SCAN_DELAY):
                    break

        if pending:
            _notifications_mod._bulk_upsert_global_notifications(pending)
            logger.info(
                "global_scan_cycle: processed %d symbols, generated %d alerts, upserted %d",
                processed, alerts_generated, len(pending)
            )
        else:
            logger.info("global_scan_cycle: processed %d symbols, no new alerts", processed)

    except Exception:
        logger.exception("global_scan_cycle: unhandled exception")
