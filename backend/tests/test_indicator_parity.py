"""Parity test: O(n) series indicators must match the O(n^2) per-row
`_compute_from_window` calls bit-for-bit (or to 6 decimal places for floats).

This is a one-shot regression test for the Stage 3 indicator rewrite.
Not part of the regular test suite — run on demand after touching the
series helpers.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

# Ensure the backend root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.indicators import (  # noqa: E402
    _compute_from_window,
    _compute_series_indicators,
    MIN_ROWS_REQUIRED,
)


def _make_ohlcv(n: int, seed: int) -> tuple[list[float], list[float], list[float], list[int]]:
    rng = random.Random(seed)
    close = 100.0
    closes, highs, lows, volumes = [], [], [], []
    for _ in range(n):
        ret = rng.gauss(0.0005, 0.02)
        new_close = max(1.0, close * (1 + ret))
        high = max(close, new_close) * (1 + abs(rng.gauss(0, 0.005)))
        low = min(close, new_close) * (1 - abs(rng.gauss(0, 0.005)))
        volume = int(rng.uniform(50_000, 5_000_000))
        closes.append(new_close)
        highs.append(high)
        lows.append(low)
        volumes.append(volume)
        close = new_close
    return closes, highs, lows, volumes


def _compare(name: str, expected, actual, tol: float = 1e-6) -> list[str]:
    errs: list[str] = []
    if expected is None and actual is None:
        return errs
    if (expected is None) != (actual is None):
        errs.append(f"{name}: None mismatch expected={expected} actual={actual}")
        return errs
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected != actual:
            errs.append(f"{name}: bool mismatch expected={expected} actual={actual}")
        return errs
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if math.isnan(expected) or math.isnan(actual):
            if not (math.isnan(expected) and math.isnan(actual)):
                errs.append(f"{name}: NaN mismatch expected={expected} actual={actual}")
        elif abs(expected - actual) > tol:
            errs.append(f"{name}: {expected} vs {actual} (diff {abs(expected - actual):.2e})")
        return errs
    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in set(expected) | set(actual):
            errs.extend(_compare(f"{name}.{k}", expected.get(k), actual.get(k), tol))
        return errs
    if expected != actual:
        errs.append(f"{name}: mismatch expected={expected!r} actual={actual!r}")
    return errs


def test_parity() -> None:
    for seed in (1, 7, 42, 1234):
        for n in (60, 100, 250, 500, 1500):
            closes, highs, lows, volumes = _make_ohlcv(n, seed)
            series_rows = _compute_series_indicators(closes, highs, lows, volumes)
            # Compare against per-row _compute_from_window calls
            all_errs: list[str] = []
            for i in range(n):
                expected = (
                    _compute_from_window(closes[: i + 1], highs[: i + 1],
                                         lows[: i + 1], volumes[: i + 1])
                    if i + 1 >= MIN_ROWS_REQUIRED
                    else {
                        "rsi_14": None, "macd": None, "macd_signal": None,
                        "macd_histogram": None, "bb_middle": None, "bb_upper": None,
                        "bb_lower": None, "bb_width": None, "bb_squeeze": None,
                        "atr_14": None, "atr_percent": None, "vwma_20": None,
                        "hv_20": None, "hv_60": None, "sharpe_60": None, "sharpe_126": None,
                    }
                )
                errs = _compare(f"row[{i}]", expected, series_rows[i])
                all_errs.extend(errs)
            if all_errs:
                print(f"\n=== seed={seed} n={n} FAILED ===")
                for e in all_errs[:30]:
                    print(" ", e)
                if len(all_errs) > 30:
                    print(f"  ... and {len(all_errs) - 30} more")
                raise AssertionError(f"Parity failed: seed={seed} n={n}, {len(all_errs)} diffs")
            print(f"  seed={seed} n={n}: OK ({len(series_rows)} rows)")


def test_perf() -> None:
    """Quick benchmark: confirm the series version is much faster than per-row."""
    import time as _t
    closes, highs, lows, volumes = _make_ohlcv(2000, 1)
    t0 = _t.perf_counter()
    _compute_series_indicators(closes, highs, lows, volumes)
    series_t = _t.perf_counter() - t0
    t0 = _t.perf_counter()
    for i in range(MIN_ROWS_REQUIRED, len(closes)):
        _compute_from_window(closes[: i + 1], highs[: i + 1],
                             lows[: i + 1], volumes[: i + 1])
    legacy_t = _t.perf_counter() - t0
    print(f"  perf: series={series_t*1000:.1f}ms legacy={legacy_t*1000:.1f}ms "
          f"speedup={legacy_t/series_t:.1f}x")
    assert series_t * 20 < legacy_t, f"Series not fast enough: {series_t:.3f}s vs {legacy_t:.3f}s"


if __name__ == "__main__":
    print("Parity test:")
    test_parity()
    print("\nPerf test:")
    test_perf()
    print("\nALL OK")
