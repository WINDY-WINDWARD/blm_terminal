# `tests/golden/` — Golden / Snapshot Files

Each `*.json` here is a **captured output of a public function** at a specific
commit. Tests using the `golden_compare` fixture in `conftest.py` diff against
these files on every run.

## Workflow

- **First time** (new function under test): run `UPDATE_GOLDEN=1 pytest ...`
  to create the golden file. Commit it.
- **Subsequent runs**: the test fails if the actual output differs from the
  golden file. Update with `UPDATE_GOLDEN=1` only when the difference is
  intentional.
- **Reviewing a PR** that changes a golden file: read the diff carefully —
  it's a contract change.

## Conventions

- JSON, sorted keys, floats rounded to 8 decimal places (see `_normalize`
  in `conftest.py`).
- Filename is the test name stem (e.g. `tql_simple_query` for a test
  `def test_simple_query(...)`).
- Larger fixtures (binary blobs, NSE HTML responses) go in `tests/fixtures/`,
  not here.

## Current files

### Phase B / TQL
- (none — TQL LRU cache uses a behavioural assertion in
  `test_tql_parser_parity.py`, not a golden diff)

### Phase C (audit items 3, 4, 7)
Captured by `scripts/capture_phase_c_goldens.py` (run from `backend/`
root, deterministic seed `20260106`, 50-symbol synthetic DB):

- `global_scan_50_symbols.json` — output of
  ``_global_scan_cycle()`` on a 50-symbol seeded DB.  ~168 pending
  notifications, JSON-normalized (datetimes → ISO, floats → 4dp).
  Used by ``tests/test_scan_cycle_goldens.py`` to lock the contract
  before the B.2 (N+1 fix) and B.1 (alert-extract) refactors.
- `ticker_indicator_notification_50_symbols.json` — output of
  ``_ticker_indicator_notification_cycle()`` on a 5-symbol watchlist.
  ~27 pending notifications.
- `ticker_intraday_indicator_notification_50_symbols.json` — output
  of ``_ticker_intraday_indicator_notification_cycle()`` on the
  same watchlist.  ~59 pending notifications.
- `intraday_hourly_stale_check_10_symbols.json` — list of stale
  symbols from ``_ticker_intraday_hourly_stale_check_sync()``.
- `ticker_scores_50_symbols.json` — rows upserted by
  ``_ticker_scores_sync()`` to the ``ticker_scores`` table.
  Used to lock the contract before the B.7 (window function) refactor.
