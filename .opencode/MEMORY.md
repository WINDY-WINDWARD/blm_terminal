# MEMORY.md — Task Completion Tracker

**Project:** blm_terminal — Live Charting System  
**Last updated:** 2026-05-28

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🔄 | In progress |
| ✅ | Complete |
| ❌ | Cancelled / skipped |

---

## Backend Tasks

| # | Status | File | Task |
|---|--------|------|------|
| 1 | ✅ | `backend/app/models/ticker.py` | Add `TickerIntraday` ORM model |
| 2 | ✅ | `backend/alembic/versions/add_ticker_intraday.py` | Alembic migration: create `ticker_intraday` table |
| 3 | ✅ | `backend/app/services/nse_charting_client.py` | New file: NSE charting API client (`get_scripcode`, `fetch_candles`, async wrappers) |
| 4 | ✅ | `backend/app/services/ticker_warehouse.py` | Add `upsert_intraday`, `get_intraday`, `backfill_intraday_symbol` |
| 5 | ✅ | `backend/app/routers/ticker.py` | Add `GET /ticker/intraday/{symbol}` endpoint + Pydantic schemas |
| 6 | ✅ | `backend/app/backgroundtasks.py` | Add `ticker_intraday_update_worker` + register job + add to `start_all_workers` |

## Frontend Tasks

| # | Status | File | Task |
|---|--------|------|------|
| 7  | ✅ | `src/lib/socket.ts` | **Deleted** |
| 8  | ✅ | `src/__tests__/mocks/wsService.ts` | **Deleted** |
| 9  | ✅ | `src/store/terminalStore.ts` | Remove socket import, define `TickData` locally with `yearHigh`/`yearLow` fields |
| 10 | ✅ | `src/components/TerminalContainer.tsx` | Replace `wsService` with `marketWsService.onConnectionChange` |
| 11 | ✅ | `src/components/widgets/WatchWidget.tsx` | Remove WS blocks; feed `tickDataAtom` from `onSymbolData` handler |
| 12 | ✅ | `src/components/LiveTicker.tsx` | Remove WS entirely; render from movers query only |
| 13 | ✅ | `src/components/CommandBar.tsx` | Updated: "OpenAlgo WS Connected" → "Market Data Connected" |
| 14 | ✅ | `src/components/widgets/SettingsWidget.tsx` | Updated: "WebSocket:" → "Market WS:", removed dead WS URL line |
| 15 | ✅ | `src/components/widgets/ChartWidget.tsx` | Full rewrite: 1h/W/M polling, `isMarketHours()`, coming-soon overlay |

---

## Verification Steps (run after implementation)

| # | Status | Check |
|---|--------|-------|
| V1 | ✅ | `npm run build` passes with zero TypeScript errors |
| V2 | ✅ | All 114 frontend tests pass |
| V3 | ✅ | No import of `socket.ts` or `wsService` anywhere in codebase |
| V4 | ✅ | `ticker_intraday` table created and queryable in `data.db` |
| V5 | ✅ | All new Python modules import cleanly |
| V6 | ⬜ | `/ticker/intraday/RELIANCE?interval=1h` returns candles (requires live backend) |

---

## Notes

- Tasks 1→2→3→4→5→6 must be done in order (model before migration, client before warehouse, warehouse before router)
- Tasks 7→8→9→10→11→12→13→14 can be done in any order after task 7 is done
- Task 15 (ChartWidget) depends on task 5 (backend endpoint) being done first
