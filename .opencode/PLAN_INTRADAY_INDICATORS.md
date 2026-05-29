# PLAN: Multi-Timeframe Indicators, Screener & Notifications

**Status:** ✅ IMPLEMENTED  
**Scope:** Full end-to-end support for `1h`, `W`, and `M` timeframes including computed indicators, screener filtering, and new alert types in both watchlist notifications and global scan.

---

## Files Modified / Created

### Database
| File | Change |
|------|--------|
| `backend/alembic/versions/add_intraday_indicators.py` | **NEW** — adds 17 indicator columns + `indicators_updated_at` to `ticker_intraday`, plus index for stale-indicator queries |
| `backend/alembic/versions/485611de3056_merge_intraday_branches.py` | **NEW** — merges two alembic head revisions (`add_ticker_intraday` + `470ce9fa8403`) |

### Models
| File | Change |
|------|--------|
| `backend/app/models/ticker.py` | Added 17 indicator columns + `indicators_updated_at` to `TickerIntraday` model (mirrors `TickerDaily`) |

### Indicators Service
| File | Change |
|------|--------|
| `backend/app/services/indicators.py` | Added `_INDICATOR_UPDATE_SQL` helper, `_build_indicator_update()`, `compute_intraday_indicators_for_all_rows()`, `compute_intraday_indicators_for_latest_candle()`, `get_intraday_indicators()` |

### Warehouse
| File | Change |
|------|--------|
| `backend/app/services/ticker_warehouse.py` | **No change needed** — `upsert_intraday` already preserves indicator columns on conflict (only updates `open, high, low, close, volume, source`) |

### Background Tasks
| File | Change |
|------|--------|
| `backend/app/backgroundtasks.py` | **Bug fix:** added missing `def _ticker_indicators_sync():` line. **New:** `_ticker_intraday_indicators_sync()`, `ticker_intraday_indicators_worker()`, `_ticker_intraday_indicator_notification_cycle()`. **Extended:** `_global_scan_cycle()` with intraday trigger evaluation. **Registered:** new job `job.ticker_intraday_indicators` in `register_all_jobs()`. **Spawned:** worker in `start_all_workers()`. |

### Routers
| File | Change |
|------|--------|
| `backend/app/routers/ticker.py` | `/indicators/{symbol}` now accepts `?interval=` param (`1d` default, `1h`/`W`/`M`). `/screener` now accepts `?filters_json=` for cross-timeframe filter keys. |

### Screener Service
| File | Change |
|------|--------|
| `backend/app/services/screener.py` | `_get_symbol_data()` now loads indicators from all intervals into `indicators_by_interval`. `_apply_filters()` supports legacy keys (daily aliases) + new interval-prefixed keys (`rsi_1h_min`, `rsi_W_max`, `atr_pct_1h_max`, `bb_squeeze_W`, etc.) |

### Frontend
| File | Change |
|------|--------|
| `src/components/widgets/NotifWidget.tsx` | Added ~25 new trigger types to `TAB_TRIGGERS.technical`, `TRIGGER_LABELS`, `getBadgeColor()`, `getBadgeLabel()`, `getTooltipDescription()` |

---

## New Alert Trigger Types

| trigger_type | Interval | Condition |
|---|---|---|
| `rsi_oversold_1h` | 1h | RSI(14) < threshold |
| `rsi_overbought_1h` | 1h | RSI(14) > threshold |
| `macd_bullish_cross_1h` | 1h | MACD histogram crosses 0 upward |
| `macd_bearish_cross_1h` | 1h | MACD histogram crosses 0 downward |
| `bb_squeeze_alert_1h` | 1h | BB squeeze active |
| `bb_upper_break_1h` | 1h | close > BB upper |
| `bb_lower_break_1h` | 1h | close < BB lower |
| `atr_expansion_1h` | 1h | ATR% > threshold |
| `rsi_oversold_W` | W | RSI(14) < threshold |
| `rsi_overbought_W` | W | RSI(14) > threshold |
| `macd_bullish_cross_W` | W | MACD histogram crosses 0 upward |
| `macd_bearish_cross_W` | W | MACD histogram crosses 0 downward |
| `bb_squeeze_alert_W` | W | BB squeeze active |
| `rsi_oversold_M` | M | RSI(14) < threshold |
| `rsi_overbought_M` | M | RSI(14) > threshold |
| `macd_bullish_cross_M` | M | MACD histogram crosses 0 upward |
| `macd_bearish_cross_M` | M | MACD histogram crosses 0 downward |
| `mtf_bullish_alignment` | all | Daily + Weekly + Monthly RSI all > 50 |
| `mtf_bearish_alignment` | all | Daily + Weekly + Monthly RSI all < 50 |

---

## Screener Cross-Timeframe Filter Keys

Legacy unprefixed keys (`rsi_min`, `atr_pct_max`, `bb_squeeze`) continue to work as aliases for daily (`1d`).

New explicit keys:
- `rsi_1d_min`, `rsi_1d_max`, `rsi_1h_min`, `rsi_1h_max`, `rsi_W_min`, `rsi_W_max`, `rsi_M_min`, `rsi_M_max`
- `atr_pct_1d_min`, `atr_pct_1d_max`, `atr_pct_1h_min`, `atr_pct_1h_max`, `atr_pct_W_min`, `atr_pct_W_max`, `atr_pct_M_min`, `atr_pct_M_max`
- `bb_squeeze_1d`, `bb_squeeze_1h`, `bb_squeeze_W`, `bb_squeeze_M`

Pass via `?filters_json={"rsi_1h_min":70,"rsi_W_min":60}` on the `/screener` endpoint.

---

## Worker Schedule

| Worker | Cron | Purpose |
|--------|------|---------|
| `ticker_intraday_update_worker` | `0 16,17,18,19,20 * * 1-5` | Backfill 1h/W/M candles |
| `ticker_intraday_indicators_worker` | `0 17,18,19,20 * * 1-5` | Compute indicators for 1h/W/M |

---

## Testing

- `npm run build` — ✅ passes (zero TypeScript errors)
- Frontend tests — ✅ 114 passed, 1 skipped
- Backend syntax — ✅ all modified Python files compile
- Alembic migration — ✅ applies cleanly (merge migration resolves dual heads)

---

## Notes

1. **MIN_ROWS_REQUIRED = 60** applies to all intervals. Weekly needs ~60 weeks (~15 months) of history; monthly needs ~60 months (5 years). Shorter history → NULL indicators (no crash).
2. **OBV** is always computed on-the-fly (not stored) for intraday, same as daily.
3. **No frontend ScreenerWidget exists yet** — the API is ready with `filters_json` support. A future frontend task can build the UI.
4. **Bug fix included:** The pre-existing missing `def _ticker_indicators_sync():` line in `backgroundtasks.py` was fixed.
