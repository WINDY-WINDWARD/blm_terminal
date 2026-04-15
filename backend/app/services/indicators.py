"""Technical indicators — calculation and per-candle storage in ticker_daily.

Design
------
* Indicators are stored IN ticker_daily, one value per OHLCV candle row.
* compute_indicators_for_all_rows(symbol)   — full historical backfill
* compute_indicators_for_latest_candle(symbol) — incremental nightly update
* get_indicators(symbol) — reads the latest ticker_daily row directly

OBV is NOT stored; it is always computed on-the-fly from the full series.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text

from app.models.ticker import TickerDaily
from app.database import _SyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lookback constants
# ---------------------------------------------------------------------------
_RSI_PERIOD        = 14
_RSI_MIN_ROWS      = _RSI_PERIOD + 28   # warm-up buffer
_MACD_MIN_ROWS     = 60
_BB_PERIOD         = 20
_BB_SQUEEZE_WINDOW = 126
_ATR_PERIOD        = 14
_VWMA_PERIOD       = 20
_HV_PERIOD_SHORT   = 20
_HV_PERIOD_LONG    = 60
_SHARPE_PERIOD_S   = 60
_SHARPE_PERIOD_L   = 126
# Minimum rows we must have to compute ANY indicator
MIN_ROWS_REQUIRED  = 60


# ---------------------------------------------------------------------------
# Pure calculation helpers (stateless, work on plain Python lists)
# ---------------------------------------------------------------------------

def _wilder_smoothing(values: list[float], period: int) -> list[float]:
    if not values or len(values) < period:
        return []
    alpha = 1.0 / period
    smoothed = [values[0]]
    for v in values[1:]:
        smoothed.append(alpha * v + (1 - alpha) * smoothed[-1])
    return smoothed


def _calculate_rsi(closes: list[float], period: int = _RSI_PERIOD) -> Optional[float]:
    if len(closes) < period + 28:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(
        _wilder_smoothing(gains[period:], period),
        _wilder_smoothing(losses[period:], period),
    ):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def _calculate_ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(alpha * v + (1 - alpha) * ema[-1])
    return ema


def _calculate_macd(closes: list[float]) -> Optional[dict]:
    if len(closes) < _MACD_MIN_ROWS:
        return None
    ema12 = _calculate_ema(closes, 12)
    ema26 = _calculate_ema(closes, 26)
    if len(ema12) < len(ema26):
        return None
    macd_line = [e12 - e26 for e12, e26 in zip(ema12[-len(ema26):], ema26)]
    if len(macd_line) < 9:
        return None
    signal = _calculate_ema(macd_line, 9)
    if not signal:
        return None
    m, s = macd_line[-1], signal[-1]
    return {"macd": round(m, 4), "signal": round(s, 4), "histogram": round(m - s, 4)}


def _calculate_bollinger_bands(closes: list[float], period: int = _BB_PERIOD) -> Optional[dict]:
    if len(closes) < period + 1:
        return None
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((c - sma) ** 2 for c in recent) / period
    std = math.sqrt(variance)
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma * 100 if sma != 0 else 0.0

    squeeze = False
    if len(closes) >= _BB_SQUEEZE_WINDOW:
        past_widths = []
        for i in range(len(closes) - _BB_SQUEEZE_WINDOW, len(closes) - period):
            w = closes[i: i + period]
            w_sma = sum(w) / period
            w_var = sum((c - w_sma) ** 2 for c in w) / period
            w_std = math.sqrt(w_var)
            pw = (w_sma + 2 * w_std - (w_sma - 2 * w_std)) / w_sma * 100 if w_sma else 0
            past_widths.append(pw)
        if past_widths and width <= min(past_widths):
            squeeze = True

    return {
        "middle":  round(sma,   2),
        "upper":   round(upper, 2),
        "lower":   round(lower, 2),
        "width":   round(width, 2),
        "squeeze": squeeze,
    }


def _calculate_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = _ATR_PERIOD
) -> Optional[dict]:
    if len(highs) < period + 1:
        return None
    trs = []
    for i in range(1, len(highs)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        ))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for t in trs[period:]:
        atr = (atr * (period - 1) + t) / period
    pct = (atr / closes[-1]) * 100 if closes[-1] != 0 else 0.0
    return {"atr": round(atr, 2), "atr_percent": round(pct, 2)}


def _calculate_vwma(closes: list[float], volumes: list[int], period: int = _VWMA_PERIOD) -> Optional[float]:
    if len(closes) < period or len(volumes) < period:
        return None
    rc = closes[-period:]
    rv = volumes[-period:]
    total_vol = sum(rv)
    if total_vol == 0:
        return None
    return round(sum(c * v for c, v in zip(rc, rv)) / total_vol, 2)


def _calculate_historical_volatility(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    log_rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    if len(log_rets) < period:
        return None
    recent = log_rets[-period:]
    mean = sum(recent) / len(recent)
    var = sum((r - mean) ** 2 for r in recent) / len(recent)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 2)


def _calculate_sharpe(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < period:
        return None
    recent = rets[-period:]
    mean = sum(recent) / len(recent)
    var = sum((r - mean) ** 2 for r in recent) / len(recent)
    std = math.sqrt(var)
    if std == 0:
        return None
    return round((mean / std) * math.sqrt(252), 2)


def _calculate_obv(closes: list[float], volumes: list[int]) -> Optional[int]:
    """OBV — always computed on-the-fly, never stored."""
    if len(closes) < 2 or len(volumes) < 2:
        return None
    obv = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
    return obv


# ---------------------------------------------------------------------------
# Build a single indicator dict from a window of OHLCV lists
# ---------------------------------------------------------------------------

def _compute_from_window(
    closes: list[float],
    highs:  list[float],
    lows:   list[float],
    volumes: list[int],
) -> dict:
    """Compute all storable indicators for the LAST candle of the given window."""
    ind: dict = {}

    rsi = _calculate_rsi(closes)
    if rsi is not None:
        ind["rsi_14"] = rsi

    macd = _calculate_macd(closes)
    if macd:
        ind["macd"]           = macd["macd"]
        ind["macd_signal"]    = macd["signal"]
        ind["macd_histogram"] = macd["histogram"]

    bb = _calculate_bollinger_bands(closes)
    if bb:
        ind["bb_middle"] = bb["middle"]
        ind["bb_upper"]  = bb["upper"]
        ind["bb_lower"]  = bb["lower"]
        ind["bb_width"]  = bb["width"]
        ind["bb_squeeze"] = "Y" if bb["squeeze"] else "N"

    atr = _calculate_atr(highs, lows, closes)
    if atr:
        ind["atr_14"]      = atr["atr"]
        ind["atr_percent"] = atr["atr_percent"]

    vwma = _calculate_vwma(closes, volumes)
    if vwma is not None:
        ind["vwma_20"] = vwma

    hv20 = _calculate_historical_volatility(closes, _HV_PERIOD_SHORT)
    if hv20 is not None:
        ind["hv_20"] = hv20

    hv60 = _calculate_historical_volatility(closes, _HV_PERIOD_LONG)
    if hv60 is not None:
        ind["hv_60"] = hv60

    s60 = _calculate_sharpe(closes, _SHARPE_PERIOD_S)
    if s60 is not None:
        ind["sharpe_60"] = s60

    s126 = _calculate_sharpe(closes, _SHARPE_PERIOD_L)
    if s126 is not None:
        ind["sharpe_126"] = s126

    return ind


# ---------------------------------------------------------------------------
# Public compute functions
# ---------------------------------------------------------------------------

def compute_indicators_for_all_rows(symbol: str) -> int:
    """Full historical backfill — compute indicators for every candle row.

    For each row at index i, the window is rows[0:i+1].  Rows that lack
    enough lookback get NULL for the indicator.  Returns number of rows
    updated.  Processes in a single DB session to keep the transaction
    small.
    """
    symbol = symbol.upper()
    with _SyncSessionLocal() as db:
        rows = list(
            db.execute(
                select(TickerDaily)
                .where(TickerDaily.symbol == symbol)
                .order_by(TickerDaily.date.asc())
            ).scalars()
        )

    if not rows:
        return 0

    # Use ISO string — Python 3.12 deprecated the built-in sqlite3 datetime
    # adapter, so raw datetime objects fail inside executemany() even though
    # single execute() works via SQLAlchemy's coercion path.
    now_str = datetime.now().isoformat()
    closes  = [r.close  for r in rows]
    highs   = [r.high   for r in rows]
    lows    = [r.low    for r in rows]
    volumes = [r.volume for r in rows]

    updates: list[dict] = []
    for i, row in enumerate(rows):
        if i + 1 < MIN_ROWS_REQUIRED:
            # Too few candles — leave NULLs
            updates.append({
                "id": row.id,
                "indicators_updated_at": now_str,
                "rsi_14": None, "macd": None, "macd_signal": None,
                "macd_histogram": None, "bb_middle": None, "bb_upper": None,
                "bb_lower": None, "bb_width": None, "bb_squeeze": None,
                "atr_14": None, "atr_percent": None, "vwma_20": None,
                "hv_20": None, "hv_60": None, "sharpe_60": None, "sharpe_126": None,
            })
            continue

        ind = _compute_from_window(
            closes[: i + 1],
            highs[: i + 1],
            lows[: i + 1],
            volumes[: i + 1],
        )
        updates.append({
            "id":                   row.id,
            "indicators_updated_at": now_str,
            "rsi_14":               ind.get("rsi_14"),
            "macd":                 ind.get("macd"),
            "macd_signal":          ind.get("macd_signal"),
            "macd_histogram":       ind.get("macd_histogram"),
            "bb_middle":            ind.get("bb_middle"),
            "bb_upper":             ind.get("bb_upper"),
            "bb_lower":             ind.get("bb_lower"),
            "bb_width":             ind.get("bb_width"),
            "bb_squeeze":           ind.get("bb_squeeze"),
            "atr_14":               ind.get("atr_14"),
            "atr_percent":          ind.get("atr_percent"),
            "vwma_20":              ind.get("vwma_20"),
            "hv_20":                ind.get("hv_20"),
            "hv_60":                ind.get("hv_60"),
            "sharpe_60":            ind.get("sharpe_60"),
            "sharpe_126":           ind.get("sharpe_126"),
        })

    if not updates:
        return 0

    with _SyncSessionLocal() as db:
        db.execute(
            text(
                """
                UPDATE ticker_daily SET
                    rsi_14               = :rsi_14,
                    macd                 = :macd,
                    macd_signal          = :macd_signal,
                    macd_histogram       = :macd_histogram,
                    bb_middle            = :bb_middle,
                    bb_upper             = :bb_upper,
                    bb_lower             = :bb_lower,
                    bb_width             = :bb_width,
                    bb_squeeze           = :bb_squeeze,
                    atr_14               = :atr_14,
                    atr_percent          = :atr_percent,
                    vwma_20              = :vwma_20,
                    hv_20                = :hv_20,
                    hv_60                = :hv_60,
                    sharpe_60            = :sharpe_60,
                    sharpe_126           = :sharpe_126,
                    indicators_updated_at = :indicators_updated_at
                WHERE id = :id
                """
            ),
            updates,
        )
        db.commit()

    return len(updates)


def compute_indicators_for_latest_candle(symbol: str) -> bool:
    """Incremental update — compute indicators for the most recent candle only.

    Loads the last 260 rows (enough for every lookback), computes indicators
    for the tail row, and writes them back.  Used after each new bhavcopy
    insert.  Returns True if successful.
    """
    symbol = symbol.upper()
    with _SyncSessionLocal() as db:
        rows = list(
            db.execute(
                select(TickerDaily)
                .where(TickerDaily.symbol == symbol)
                .order_by(TickerDaily.date.asc())
            ).scalars()
        )

    if len(rows) < MIN_ROWS_REQUIRED:
        return False

    closes  = [r.close  for r in rows]
    highs   = [r.high   for r in rows]
    lows    = [r.low    for r in rows]
    volumes = [r.volume for r in rows]

    ind = _compute_from_window(closes, highs, lows, volumes)
    latest = rows[-1]
    now = datetime.now()

    with _SyncSessionLocal() as db:
        db.execute(
            text(
                """
                UPDATE ticker_daily SET
                    rsi_14               = :rsi_14,
                    macd                 = :macd,
                    macd_signal          = :macd_signal,
                    macd_histogram       = :macd_histogram,
                    bb_middle            = :bb_middle,
                    bb_upper             = :bb_upper,
                    bb_lower             = :bb_lower,
                    bb_width             = :bb_width,
                    bb_squeeze           = :bb_squeeze,
                    atr_14               = :atr_14,
                    atr_percent          = :atr_percent,
                    vwma_20              = :vwma_20,
                    hv_20                = :hv_20,
                    hv_60                = :hv_60,
                    sharpe_60            = :sharpe_60,
                    sharpe_126           = :sharpe_126,
                    indicators_updated_at = :indicators_updated_at
                WHERE id = :id
                """
            ),
            {
                "id":                    latest.id,
                "indicators_updated_at": now,
                "rsi_14":               ind.get("rsi_14"),
                "macd":                 ind.get("macd"),
                "macd_signal":          ind.get("macd_signal"),
                "macd_histogram":       ind.get("macd_histogram"),
                "bb_middle":            ind.get("bb_middle"),
                "bb_upper":             ind.get("bb_upper"),
                "bb_lower":             ind.get("bb_lower"),
                "bb_width":             ind.get("bb_width"),
                "bb_squeeze":           ind.get("bb_squeeze"),
                "atr_14":               ind.get("atr_14"),
                "atr_percent":          ind.get("atr_percent"),
                "vwma_20":              ind.get("vwma_20"),
                "hv_20":                ind.get("hv_20"),
                "hv_60":                ind.get("hv_60"),
                "sharpe_60":            ind.get("sharpe_60"),
                "sharpe_126":           ind.get("sharpe_126"),
            },
        )
        db.commit()

    return True


# ---------------------------------------------------------------------------
# Public read functions
# ---------------------------------------------------------------------------

def get_indicators(symbol: str) -> dict:
    """Return the latest computed indicators for a symbol.

    Reads indicator columns from the most recent ticker_daily row.
    If that row has NULL indicators (not yet backfilled), falls back to
    on-the-fly computation and returns the result without persisting.

    OBV is always computed on-the-fly (appended to the response).
    """
    symbol = symbol.upper()

    with _SyncSessionLocal() as db:
        rows = list(
            db.execute(
                select(TickerDaily)
                .where(TickerDaily.symbol == symbol)
                .order_by(TickerDaily.date.desc())
                .limit(260)
            ).scalars()
        )

    if not rows:
        return {"symbol": symbol, "error": "No data available", "data_points": 0}

    latest = rows[0]  # most recent (DESC order)

    # --- OBV from latest ~252 rows (always on-the-fly) ---
    sorted_rows = list(reversed(rows))  # ASC for OBV
    obv_closes  = [r.close  for r in sorted_rows if r.close  is not None]
    obv_volumes = [r.volume for r in sorted_rows if r.volume is not None]
    obv = _calculate_obv(obv_closes, obv_volumes)

    # If indicators were already computed and stored, return them directly
    if latest.indicators_updated_at is not None:
        return {
            "symbol":          symbol,
            "data_points":     len(rows),
            "latest_date":     latest.date.isoformat(),
            "close":           latest.close,
            "rsi_14":          latest.rsi_14,
            "macd":            latest.macd,
            "macd_signal":     latest.macd_signal,
            "macd_histogram":  latest.macd_histogram,
            "bb_middle":       latest.bb_middle,
            "bb_upper":        latest.bb_upper,
            "bb_lower":        latest.bb_lower,
            "bb_width":        latest.bb_width,
            "bb_squeeze":      latest.bb_squeeze == "Y" if latest.bb_squeeze else False,
            "atr_14":          latest.atr_14,
            "atr_percent":     latest.atr_percent,
            "vwma_20":         latest.vwma_20,
            "hv_20":           latest.hv_20,
            "hv_60":           latest.hv_60,
            "sharpe_60":       latest.sharpe_60,
            "sharpe_126":      latest.sharpe_126,
            "obv":             obv,
        }

    # Fallback: compute on-the-fly (backfill not yet run)
    all_rows = list(reversed(rows))  # ASC
    if len(all_rows) < MIN_ROWS_REQUIRED:
        return {
            "symbol":      symbol,
            "error":       f"Insufficient data ({len(all_rows)} rows, need {MIN_ROWS_REQUIRED}+)",
            "data_points": len(all_rows),
        }

    closes  = [r.close  for r in all_rows if r.close  is not None]
    highs   = [r.high   for r in all_rows if r.high   is not None]
    lows    = [r.low    for r in all_rows if r.low    is not None]
    volumes = [r.volume for r in all_rows if r.volume is not None]

    ind = _compute_from_window(closes, highs, lows, volumes)

    return {
        "symbol":         symbol,
        "data_points":    len(all_rows),
        "latest_date":    latest.date.isoformat(),
        "close":          latest.close,
        **{k: v for k, v in ind.items()},
        "bb_squeeze":     ind.get("bb_squeeze") == "Y",
        "obv":            obv,
    }
