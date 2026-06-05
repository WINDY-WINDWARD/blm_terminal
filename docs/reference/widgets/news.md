# News Widget Enrichment

## Goal

Expose the backend's computed news metadata directly in the `NewsWidget` so users can see and act on the NLP output without leaving the feed.

The main goals were:
- show extracted backend entities instead of hiding them
- surface sentiment confidence, not just a colored dot
- show the threat category alongside the threat level
- display the backend-tagged `company_symbol`
- let users click extracted ticker chips to update the global active symbol

---

## What Was Done

File changed:
- `src/components/widgets/NewsWidget.tsx`

New documentation:
- `docs/widgets/news.md`

UI additions in the widget:
- inline chips for extracted `tickers`, `organizations`, `people`, and `countries`
- inline confidence percentage next to the sentiment dot
- threat badge extended from `LEVEL` to `LEVEL · CATEGORY`
- `company_symbol` chip rendered on article rows when present
- clickable ticker chips that resolve against stock-universe search and then set the global symbol/exchange atoms

Behavior preserved:
- clicking the row still opens the article
- live news rendering and paginated DB news rendering still use the same `ArticleRow`
- source filtering, live section, pagination, and company/global tabs were left intact

---

## How It Was Done

### 1. Kept the change local to the widget

The implementation was intentionally contained in `NewsWidget.tsx` to avoid unnecessary cross-file risk. No backend contract changes were needed because the backend already returned the required fields.

### 2. Added small formatting helpers

Small helpers were introduced to keep rendering code simple:
- `formatPercent()` for confidence display
- `formatThreatCategory()` for readable uppercase threat labels
- `normalizeTicker()` for matching extracted tickers with stock-universe symbols
- `getEntityValues()` for safe extraction from `article.entities`

### 3. Added reusable chip rendering

Two small UI helpers were added:
- `MetaChip` for read-only tags
- `EntityChips` for entity groups with display limits and overflow handling

`EntityChips` caps visible values and shows a `+N` overflow chip to prevent rows from becoming too wide.

### 4. Avoided nested interactive element regressions

Before the change, the whole article row was rendered as an anchor tag.

That structure would conflict with clickable ticker buttons inside the row. To avoid invalid nested interactive markup and unreliable click behavior, the row was converted into an accessible clickable container:
- row click opens the article in a new tab
- `Enter` and `Space` also open the article
- ticker buttons call `stopPropagation()` so they do not trigger row navigation

This was the main regression-sensitive part of the change.

### 5. Matched the repo's symbol-selection flow

Ticker chips do not blindly set the symbol. Instead they:
1. normalize the extracted ticker
2. query `/api/py/stockuniverse/search/:query`
3. require an exact symbol match from the search results
4. set `activeSymbolAtom`
5. set `activeExchangeAtom` using the matched exchange, falling back to `NSE`

This keeps the behavior aligned with the rest of the terminal and avoids setting invalid symbols from noisy entity extraction.

---

## Goals Achieved

- backend-computed entity extraction is now visible in the frontend
- users can act on extracted tickers directly from news rows
- sentiment confidence is now visible instead of hidden in backend data only
- threat context is clearer because category is shown next to level
- backend-tagged company association is visible on each article row
- the feature was delivered without changing the backend API

---

## Validation

Validation run during implementation:
- `npx eslint src/components/widgets/NewsWidget.tsx`
- `npm run build`

Results:
- widget file lint passed
- production build passed
- TypeScript passed
- test suite passed as part of `npm run build`

Note:
- repo-wide `npm run lint` still reports unrelated pre-existing issues outside this widget

---

## Files Included In Commit

- `src/components/widgets/NewsWidget.tsx`
- `docs/widgets/news.md`
