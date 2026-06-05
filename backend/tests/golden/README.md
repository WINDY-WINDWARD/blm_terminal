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

(none yet — first refactor target is TQL LRU cache, which doesn't need
a golden file; its test is a behavioural assertion in `test_tql_parser_parity.py`.)
