# AI Picks Feature Implementation Plan

## Overview
A new terminal widget (`PICKS`) and background AI pipeline that autonomously hunts, verifies, and continuously evaluates short-term swing trade opportunities using Kimi 2.6 and MiniMax 2.5 via OpenCode Zen.

---

## Phase 1: Database & Backend Models

**Target File:** `backend/app/models/ai_picks.py`

**SQLAlchemy Model: `ai_picks`**
*   `id`: Integer (Primary Key)
*   `symbol`: String (Index, e.g., 'RELIANCE')
*   `exchange`: String (Default: 'NSE')
*   `status`: Enum (`NEW`, `ACTED_ON`, `CLOSED`, `ABANDONED`)
*   `direction`: Enum (`LONG`, `SHORT`)
*   `entry_price`: Float (Suggested entry target)
*   `take_profit`: Float (Target exit)
*   `stop_loss`: Float (Risk management exit)
*   `notes`: JSON (Array of note objects containing timestamps and AI commentary: `[{ "timestamp": "...", "note": "..." }]`)
*   `created_at`: DateTime
*   `updated_at`: DateTime

**Migration:** Generate via `alembic revision --autogenerate -m "add ai_picks table"` and apply.

---

## Phase 2: AI Tool Expansion (ANNC Data)

**Target File:** `backend/app/mcp_server.py`

To allow the AI background loops to access Announcements without reading raw XML filings, two new tools will be added:
1.  `get_recent_announcements(symbol: str)`: Wraps RSS parsing logic to return recent corporate announcements for a specific ticker.
2.  `get_upcoming_events(symbol: str)`: Wraps `get_event_calendar_cached` from the `announcements.py` router to return upcoming board meetings and earnings.

---

## Phase 3: The AI Daemon Workers

**Target File:** `backend/app/workers/ai_picks_worker.py`
*(Registered in `backend/app/orchestrator.py`)*

Three independent daemon loops utilizing the existing `httpx` streaming logic to OpenCode Zen.

### Loop 1: The Hunter
*   **Schedule:** Cron: 8:00 AM (Market pre-open)
*   **Model:** Kimi 2.6
*   **Tool Access:** Screener & Fundamentals, News Feeds, Morningstar Fair Value, Sectors & Industries, Market Movers, and Announcements.
*   **Behavior:** Injected with a system prompt to scan the market for short-term swing trade opportunities. Analyzes top movers, sector momentum, and recent news.
*   **Output:** Structured JSON list of proposed trades (Symbol, Direction, Entry, TP, SL, initial thesis).

### Loop 2: The Verifier
*   **Schedule:** Runs immediately after Loop 1 finishes successfully.
*   **Model:** MiniMax 2.5
*   **Tool Access:** Same as Loop 1.
*   **Behavior:** Acts as a secondary risk officer. Takes Loop 1's JSON proposals and independently verifies the setups using the tools.
*   **Output:** Discards weak setups, refines targets. Surviving picks are committed to the `ai_picks` database table with status `NEW` and the thesis appended to the `notes` JSON.

### Loop 3: The Evaluator
*   **Schedule:** Cron: 5:00 PM (Market post-close)
*   **Model:** MiniMax 2.5
*   **Tool Access:** Fundamentals & Trades, Company News, Morningstar Fair Value, TQL Screener (Technical), and Announcements.
*   **Behavior:** 
    *   Queries the DB for all picks with status `NEW` or `ACTED_ON`.
    *   Passes the historical thesis and today's price action/news to the model.
    *   Appends a new timestamped evaluation note to the `notes` column (e.g., "Hit resistance, suggest tightening stop loss").
    *   **Cleanup Rule:** Auto-updates status to `ABANDONED` if a pick has remained in the `NEW` state for > 48 hours.

---

## Phase 4: API Layer

**Target File:** `backend/app/routers/ai_picks.py`

*   `GET /ai/picks`: Retrieves picks (supports filtering by status). Ordered by `updated_at` DESC.
*   `PUT /ai/picks/{id}/status`: Updates the status of a pick (e.g., `NEW` -> `ACTED_ON` or `CLOSED`).

*Must be registered in `backend/main.py`.*

---

## Phase 5: Frontend Widget

**Target File:** `src/components/widgets/AiPicksWidget.tsx`

**UI Layout:**
*   **Tabs:** View filters for "Active Picks" (`NEW`, `ACTED_ON`) and "History" (`CLOSED`, `ABANDONED`).
*   **Data Table:** Displays Symbol, Direction, Targets (Entry, TP, SL), and Status.
*   **Expandable Rows:** Clicking a row expands it to show the full chronological history from the `notes` JSON array.
*   **Action Buttons:** 
    *   "Mark Acted On" (Changes status to `ACTED_ON` - visual tracker only).
    *   "Close Position" (Changes status to `CLOSED`).

**Registration Steps:**
1.  **Panel Dispatcher:** Add `<AiPicksWidget />` mapped to case `'PICKS'` in `src/components/Panel.tsx`.
2.  **Validation:** Add `'PICKS'` to `VALID_WIDGETS` array in `src/components/TerminalContainer.tsx`.
3.  **Command Bar:** Add `{ cmd: 'PICKS', desc: 'AI Swing Trade Picks' }` to `WIDGET_COMMANDS` in `src/components/CommandBar.tsx`.
