"""Global NSE scan cycle (audit C.1, A.12 part 1, A.13).

Single cycle callable: ``_global_scan_cycle`` — scans all NSE
stocks (not just watchlist) for technical and market alerts.  Automatic
runs use a weekday market-hours schedule via the ``global_scan_worker``
daemon in ``app.workers.notifications``; direct Jobs-page runs are
available at any time.

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
    breakout_snapshot as _breakout_snapshot_mod,
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
    from app.models.ticker import TickerDaily, TickerScore
    from app.services import ticker_warehouse as _tw_mod
    from app.services.data_sync import alerts as _alerts_mod

    try:
        logger.info("global_scan_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = _notifications_mod.get_notif_config()
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

        # Capture daily breakout snapshots for repeat-breakout detection
        try:
            _breakout_snapshot_mod._capture_breakout_snapshot()
        except Exception:
            logger.exception("global_scan_cycle: breakout snapshot capture failed (non-fatal)")

        # Pre-fetch deal significance data once for the whole scan
        deal_symbols      = set(deals.keys())
        deal_mkt_caps     = _deal_sig_mod._fetch_deal_market_caps(deal_symbols)
        short_deals_list  = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px     = _deal_sig_mod._fetch_short_deal_close_prices(short_deals_list)

        # Hoist gainers/losers DataFrames into O(1) dicts
        gainers_by_symbol: dict[str, float] = {}
        if gainers_df is not None:
            for row in gainers_df.itertuples():
                sym = row.symbol
                pchg = getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0
                if pchg:
                    gainers_by_symbol[sym] = float(pchg)
        losers_by_symbol: dict[str, float] = {}
        if losers_df is not None:
            for row in losers_df.itertuples():
                sym = row.symbol
                pchg = getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0
                if pchg:
                    losers_by_symbol[sym] = float(pchg)

        del high52_raw, low52_raw, vol_raw, deals_raw
        del gainers_df, losers_df

        processed = 0
        alerts_generated = 0

        for i in range(0, total_symbols, GLOBAL_SCAN_BATCH_SIZE):
            if _shutdown_event.is_set():
                logger.info("global_scan_cycle: shutdown requested, stopping at %d/%d symbols",
                            processed, total_symbols)
                return

            batch = all_symbols[i:i + GLOBAL_SCAN_BATCH_SIZE]

            # Bulk-fetch daily data and intraday data for this batch
            daily_bulk = _tw_mod.get_latest_indicator_rows(batch, n=10)
            su_bulk = _tw_mod.get_52w_levels(batch)
            intraday_bulk = _tw_mod.get_intraday_latest(batch, ["1h", "W", "M"], n=2)
            # Filter intraday rows to those with indicators computed
            intraday_bulk = {
                k: [r for r in v if r.indicators_updated_at is not None]
                for k, v in intraday_bulk.items()
                if any(r.indicators_updated_at is not None for r in v)
            }

            for symbol in batch:
                processed += 1

                if processed % 200 == 0 or processed == 1:
                    logger.info("global_scan_cycle: progress %d/%d symbols (%.0f%%)",
                                processed, total_symbols, processed / total_symbols * 100)

                try:
                    rows = daily_bulk.get(symbol, [])
                    if len(rows) < 2:
                        continue

                    latest = rows[-1]
                    prev = rows[-2]

                    up_streak = 0
                    dn_streak = 0
                    for r in reversed(rows):
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
                    su_level = su_bulk.get(symbol)
                    if su_level and latest.close:
                        high_52w, low_52w = su_level
                        if high_52w > 0:
                            pct_from_52w_high = (latest.close - high_52w) / high_52w * 100
                        if low_52w > 0:
                            pct_from_52w_low = (latest.close - low_52w) / low_52w * 100

                    ts = scores_cache.get(symbol)

                    alerts: list[tuple[str, str]] = []
                    alerts.extend(_alerts_mod.evaluate_technical_alerts(
                        symbol, latest, prev, cfg,
                        ts=ts,
                        up_streak=up_streak,
                        dn_streak=dn_streak,
                        pct_from_52w_high=pct_from_52w_high,
                        pct_from_52w_low=pct_from_52w_low,
                    ))

                    # --- Intraday / Weekly / Monthly indicator triggers ---
                    try:
                        intraday_rows: dict[str, list] = {}
                        for interval in ("1h", "W", "M"):
                            key = (symbol, interval)
                            if key in intraday_bulk:
                                intraday_rows[interval] = intraday_bulk[key]

                        for interval, iv_rows in intraday_rows.items():
                            if len(iv_rows) < 1:
                                continue
                            latest_iv = iv_rows[-1]
                            prev_iv = iv_rows[-2] if len(iv_rows) >= 2 else None
                            alerts.extend(_alerts_mod.evaluate_intraday_alerts(
                                symbol, latest_iv, prev_iv, cfg, interval,
                            ))
                    except Exception:
                        logger.debug("global_scan_cycle: intraday eval failed for %s", symbol, exc_info=True)

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

                    if symbol in gainers_by_symbol:
                        alerts.append(("top_gainer", f"{symbol} +{gainers_by_symbol[symbol]:.1f}%"))

                    if symbol in losers_by_symbol:
                        alerts.append(("top_loser", f"{symbol} {losers_by_symbol[symbol]:.1f}%"))

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

        # Generate repeat-breakout alerts from accumulated snapshots
        try:
            cfg_repeat = _notifications_mod.get_notif_config()
            repeat_window = int(float(cfg_repeat.get("notif.repeat_breakout_window_days", 10.0)))
            repeat_min = int(float(cfg_repeat.get("notif.repeat_breakout_min_days", 2.0)))
            repeat_alerts = _breakout_snapshot_mod._generate_repeat_breakout_alerts(
                window_days=repeat_window,
                min_days=repeat_min,
            )
            pending.extend(repeat_alerts)
            alerts_generated += len(repeat_alerts)
        except Exception:
            logger.exception("global_scan_cycle: repeat breakout alert generation failed (non-fatal)")

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
