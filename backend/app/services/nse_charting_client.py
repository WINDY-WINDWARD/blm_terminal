"""NSE Charting API client — fetches OHLCV candles from charting.nseindia.com.

Two-step process:
  1. Resolve symbol → scripcode (NSE internal token) via symbolsDynamic endpoint.
  2. Fetch OHLCV candles via symbolHistoricalData endpoint.

Scripcode values are cached in memory for the lifetime of the process — they
never change for a given symbol, so there is no need for DB persistence.

All calls are synchronous (uses requests, not httpx) because this client is
called from background threads and sync warehouse functions, not async handlers.
The async wrapper `fetch_candles_async` is provided for use from FastAPI routes.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://charting.nseindia.com"
_SYMBOLS_ENDPOINT = "/v1/exchanges/symbolsDynamic"
_HISTORY_ENDPOINT = "/v1/charts/symbolHistoricalData"

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Rate-limit: minimum seconds between consecutive requests
_REQUEST_DELAY_SECONDS = 1.0

# Series suffix fallback order — mirrors NSEClient.SERIES_PREFERENCE
_SERIES_FALLBACK: list[str] = ["EQ", "BE", "SM", "ST"]

# Interval → (chartType, timeInterval) mapping
INTERVAL_PARAMS: dict[str, tuple[str, str]] = {
    "1m":  ("I", "1"),
    "5m":  ("I", "5"),
    "15m": ("I", "15"),
    "30m": ("I", "30"),
    "1h":  ("I", "60"),
    "D":   ("D", "1"),
    "W":   ("W", "1"),
    "M":   ("M", "1"),
}

# ---------------------------------------------------------------------------
# Module-level scripcode cache: symbol → (scripcode, series) or None (known-bad)
# Storing None for failed lookups prevents repeated 4-series probe on every call.
# ---------------------------------------------------------------------------
_scripcode_cache: dict[str, tuple[str, str] | None] = {}

# Timestamp of the last outbound HTTP request (for rate limiting)
_last_request_time: float = 0.0


def _rate_limit() -> None:
    """Sleep if needed to honour _REQUEST_DELAY_SECONDS between calls."""
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _REQUEST_DELAY_SECONDS:
        time.sleep(_REQUEST_DELAY_SECONDS - elapsed)
    _last_request_time = time.monotonic()


def _build_headers(symbol: str) -> dict[str, str]:
    return {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Referer": f"https://charting.nseindia.com/?symbol={symbol}-EQ",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://charting.nseindia.com",
    }


# ---------------------------------------------------------------------------
# Scripcode resolution
# ---------------------------------------------------------------------------

def _lookup_scripcode_for_nse_symbol(nse_symbol: str, symbol: str) -> str | None:
    """Single attempt: resolve nse_symbol (e.g. 'RELIANCE-EQ') to a scripcode.

    Returns scripcode string on success, None if not found.
    """
    url = f"{_BASE_URL}{_SYMBOLS_ENDPOINT}"
    params = {"symbol": nse_symbol, "segment": ""}
    _rate_limit()
    try:
        resp = requests.get(url, params=params, headers=_build_headers(symbol), timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("[nse_charting] scripcode HTTP error for %s: %s", nse_symbol, exc)
        return None

    entries = data.get("data", [])
    if not entries:
        return None
    code = str(entries[0].get("scripcode", ""))
    return code if code else None


def get_scripcode(symbol: str, series: str | None = None) -> tuple[str, str]:
    """Return (scripcode, resolved_series) for *symbol*.

    Resolution order:
      1. If *series* is provided, try ``{symbol}-{series}`` first.
      2. If symbol already ends with a known series suffix (e.g. BODALCHEM-BE),
         try the symbol as-is first (don't double-append), then try the base
         symbol with other standard series.
      3. If symbol ends with a non-standard suffix (e.g. 5PAISA-RE), strip it
         and try the base symbol with standard series fallbacks.
      4. Plain symbol — standard fallback loop through _SERIES_FALLBACK.
      5. Raise ValueError if nothing resolves.

    Results are cached in-process keyed by symbol. Failed lookups are cached
    as None to avoid repeating the full series-probe on subsequent calls.
    """
    if symbol in _scripcode_cache:
        cached = _scripcode_cache[symbol]
        if cached is None:
            raise ValueError(f"[nse_charting] no scripcode found for {symbol} (cached failure)")
        return cached

    # Detect if symbol already embeds a series suffix
    parts = symbol.rsplit("-", 1)
    symbol_has_known_series = len(parts) == 2 and parts[1] in _SERIES_FALLBACK
    symbol_has_other_suffix = len(parts) == 2 and parts[1] not in _SERIES_FALLBACK

    # Build ordered list of candidate (nse_symbol, resolved_series)
    candidates: list[tuple[str, str]] = []

    # 1. Caller-supplied series hint
    if series and series not in _SERIES_FALLBACK:
        candidates.append((f"{symbol}-{series}", series))
    elif series:
        for s in [series] + [s for s in _SERIES_FALLBACK if s != series]:
            candidates.append((f"{symbol}-{s}", s))

    if symbol_has_known_series:
        # 2a. Symbol already has known series suffix (e.g. BODALCHEM-BE)
        known_s = parts[1]
        candidates.append((symbol, known_s))
        # Also try other series on the base symbol
        base = parts[0]
        for s in _SERIES_FALLBACK:
            if s != known_s:
                candidates.append((f"{base}-{s}", s))

    elif symbol_has_other_suffix:
        # 2b. Non-standard suffix (e.g. 5PAISA-RE) — try base + standard series
        base = parts[0]
        for s in _SERIES_FALLBACK:
            candidates.append((f"{base}-{s}", s))

    else:
        # 3. Plain symbol — standard fallback loop
        for s in _SERIES_FALLBACK:
            candidates.append((f"{symbol}-{s}", s))

    # Deduplicate while preserving order
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            deduped.append(c)

    for nse_symbol, resolved_s in deduped:
        code = _lookup_scripcode_for_nse_symbol(nse_symbol, symbol)
        if code:
            _scripcode_cache[symbol] = (code, resolved_s)
            logger.debug("[nse_charting] scripcode %s → %s (series=%s)", symbol, code, resolved_s)
            return code, resolved_s

    # Cache the failure so we don't probe all series again
    _scripcode_cache[symbol] = None
    raise ValueError(
        f"[nse_charting] no scripcode found for {symbol} (tried {[c[0] for c in deduped]})"
    )


# ---------------------------------------------------------------------------
# Candle fetch
# ---------------------------------------------------------------------------

def fetch_candles(
    symbol: str,
    interval: str,
    from_ts: int = 0,
    to_ts: Optional[int] = None,
    series: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch OHLCV candles from NSE charting API.

    Args:
        symbol:   NSE ticker (e.g. "RELIANCE").
        interval: One of the INTERVAL_PARAMS keys ("1h", "W", "M", etc.).
        from_ts:  Start time as Unix *seconds* (0 = all available history).
        to_ts:    End time as Unix *seconds* (None → current time).
        series:   NSE series hint (e.g. "EQ", "BE"). If None, tries EQ first
                  then falls back through BE, SM, ST automatically.

    Returns:
        List of dicts: [{time_ms, open, high, low, close, volume}, ...]
        Ordered oldest → newest. Empty list if no data.

    Raises:
        ValueError: if interval unknown or API returns non-OK status.
    """
    if interval not in INTERVAL_PARAMS:
        raise ValueError(f"[nse_charting] unknown interval: {interval!r}")

    chart_type, time_interval = INTERVAL_PARAMS[interval]

    if to_ts is None:
        to_ts = int(datetime.now(timezone.utc).timestamp())

    scripcode, resolved_series = get_scripcode(symbol, series=series)

    url = f"{_BASE_URL}{_HISTORY_ENDPOINT}"
    params = {
        "token": scripcode,
        "fromDate": str(from_ts),
        "toDate": str(to_ts),
        "symbol": f"{symbol}-{resolved_series}",
        "symbolType": "Equity",
        "chartType": chart_type,
        "timeInterval": time_interval,
    }

    _rate_limit()
    try:
        resp = requests.get(url, params=params, headers=_build_headers(symbol), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise ValueError(f"[nse_charting] candle fetch failed for {symbol}/{interval}: {exc}") from exc

    if not payload.get("status"):
        raise ValueError(f"[nse_charting] API returned status=false for {symbol}/{interval}")

    raw_candles: list[dict] = payload.get("data", [])

    result = []
    for c in raw_candles:
        try:
            result.append({
                "time_ms": int(c["time"]),
                "open":    float(c["open"]),
                "high":    float(c["high"]),
                "low":     float(c["low"]),
                "close":   float(c["close"]),
                "volume":  int(c.get("volume", 0)),
            })
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("[nse_charting] skipping malformed candle %s: %s", c, exc)

    logger.debug(
        "[nse_charting] %s/%s from_ts=%s → %d candles",
        symbol, interval, from_ts, len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Async wrapper (for use from FastAPI async route handlers)
# ---------------------------------------------------------------------------

async def fetch_candles_async(
    symbol: str,
    interval: str,
    from_ts: int = 0,
    to_ts: Optional[int] = None,
    series: str | None = None,
) -> list[dict[str, Any]]:
    """Async wrapper around fetch_candles — runs in a thread pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: fetch_candles(symbol, interval, from_ts, to_ts, series)
    )


async def get_scripcode_async(symbol: str, series: str | None = None) -> tuple[str, str]:
    """Async wrapper around get_scripcode."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: get_scripcode(symbol, series))
