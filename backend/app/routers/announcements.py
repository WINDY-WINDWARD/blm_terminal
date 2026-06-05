"""Router for NSE announcements RSS feed and event calendar."""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"

# NSE event calendar URLs
_CALENDAR_URL_MAIN = "https://www.nseindia.com/api/event-calendar"
_CALENDAR_URL_SME = "https://www.nseindia.com/api/event-calendar?index=sme"
_CALENDAR_URL_PAST = "https://www.nseindia.com/api/event-calendar?index=equities"

# In-memory caches: { "data": list, "expires_at": float }
_CALENDAR_CACHE: dict[str, Any] = {}
_PAST_RESULTS_CACHE: dict[str, Any] = {}
_CALENDAR_TTL_SECONDS = 900  # 15 minutes

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/event-calendar",
}

_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


# ---------------------------------------------------------------------------
# Shared httpx.AsyncClient pool (audit B.2)
# ---------------------------------------------------------------------------
#
# A single ``httpx.AsyncClient`` is created on first use and reused across
# requests.  httpx reuses a single connection pool, so the per-call TCP +
# TLS handshake cost (and the NSE anti-bot cookie warm-up) is paid only
# once.  The client is closed via ``_close_shared_client`` (called from
# tests via the ``reset_announcements_client`` fixture, and available for
# the FastAPI lifespan if we add one later).

_shared_client: httpx.AsyncClient | None = None
_shared_client_lock = asyncio.Lock()


def _get_shared_client() -> httpx.AsyncClient:
    """Return the module-level ``httpx.AsyncClient`` singleton.

    Lazily creates one on first call.  The client is configured with NSE
    headers and conservative connection limits.
    """
    global _shared_client
    if _shared_client is None:
        limits = httpx.Limits(
            max_connections=4,
            max_keepalive_connections=2,
            keepalive_expiry=30.0,
        )
        _shared_client = httpx.AsyncClient(
            headers=_NSE_HEADERS,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=limits,
            follow_redirects=True,
        )
    return _shared_client


def _close_shared_client() -> None:
    """Tear down the shared client.  Idempotent.

    The next ``_get_shared_client`` call will lazily create a fresh one.
    Safe to call when ``_shared_client`` is None.
    """
    global _shared_client
    if _shared_client is not None:
        try:
            # httpx.AsyncClient.aclose is async; if we are already inside
            # an event loop we cannot call it synchronously.  In that case
            # we just drop the reference and let GC handle the aclose().
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — safe to aclose synchronously via run.
            try:
                asyncio.run(_shared_client.aclose())
            except Exception:
                logger.debug("Failed to close shared httpx client cleanly")
        _shared_client = None


class EventCalendarItem(BaseModel):
    """Normalised event calendar entry from NSE (main board or SME)."""

    symbol: str
    company: str
    purpose: str
    description: str
    date: str          # "20-Apr-2026"
    source: str        # "main" | "sme"
    attachment: str | None = None


def _normalize_main(raw: list[dict]) -> list[EventCalendarItem]:
    """Normalize main-board event-calendar items.

    Main schema: symbol, company, purpose, bm_desc, date
    """
    items: list[EventCalendarItem] = []
    for entry in raw:
        try:
            items.append(
                EventCalendarItem(
                    symbol=str(entry.get("symbol", "")).strip().upper(),
                    company=str(entry.get("company", "")).strip(),
                    purpose=str(entry.get("purpose", "")).strip(),
                    description=str(entry.get("bm_desc", "")).strip(),
                    date=str(entry.get("date", "")).strip(),
                    source="main",
                    attachment=None,
                )
            )
        except Exception:
            logger.debug("Skipping malformed main calendar entry: %s", entry)
    return items


def _normalize_sme(raw: list[dict]) -> list[EventCalendarItem]:
    """Normalize SME event-calendar items.

    SME schema: bm_symbol, sm_name, bm_purpose, bm_desc, bm_date, attachment
    """
    items: list[EventCalendarItem] = []
    for entry in raw:
        try:
            items.append(
                EventCalendarItem(
                    symbol=str(entry.get("bm_symbol", "")).strip().upper(),
                    company=str(entry.get("sm_name", "")).strip(),
                    purpose=str(entry.get("bm_purpose", "")).strip(),
                    description=str(entry.get("bm_desc", "")).strip(),
                    date=str(entry.get("bm_date", "")).strip(),
                    source="sme",
                    attachment=entry.get("attachment") or None,
                )
            )
        except Exception:
            logger.debug("Skipping malformed SME calendar entry: %s", entry)
    return items


def _parse_event_date(d: str) -> datetime:
    """Parse the NSE date format ``20-Apr-2026`` → ``datetime`` (or max on error)."""
    try:
        return datetime.strptime(d, "%d-%b-%Y")
    except ValueError:
        return datetime.max


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    normalizer,
) -> list[EventCalendarItem]:
    """Fetch a single URL, normalise, return items.  Logs but never raises.

    Used by ``_fetch_event_calendar_raw`` which calls this twice via
    ``asyncio.gather`` so that one URL's failure does not poison the
    other.
    """
    try:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()
        raw: list[dict] = resp.json()
        return normalizer(raw)
    except Exception:
        logger.exception("Failed to fetch event calendar from %s", url)
        return []


async def _fetch_event_calendar_raw() -> list[EventCalendarItem]:
    """Fetch both NSE event calendar endpoints concurrently and return a
    merged, deduped, date-sorted list.

    B.3: the main-board and SME fetches run in parallel via
    ``asyncio.gather`` (not sequentially) — a cache miss now costs the
    time of one HTTP round-trip, not two.

    B.2: uses the module-shared ``httpx.AsyncClient`` so the connection
    pool, NSE cookies, and TLS handshake are amortised across calls.
    """
    client = _get_shared_client()
    main_items, sme_items = await asyncio.gather(
        _fetch_one(client, _CALENDAR_URL_MAIN, _normalize_main),
        _fetch_one(client, _CALENDAR_URL_SME, _normalize_sme),
    )

    items: list[EventCalendarItem] = []
    seen: set[tuple[str, str, str]] = set()
    for item in main_items + sme_items:
        key = (item.symbol, item.date, item.purpose)
        if item.symbol and key not in seen:
            seen.add(key)
            items.append(item)

    items.sort(key=lambda i: _parse_event_date(i.date))
    return items


async def _fetch_past_results_raw() -> list[EventCalendarItem]:
    """Fetch results published in the last 3 months, via the shared client."""
    client = _get_shared_client()

    to_date = date.today()
    from_date = to_date - timedelta(days=90)
    url = (
        f"{_CALENDAR_URL_PAST}"
        f"&from_date={from_date.strftime('%d-%m-%Y')}"
        f"&to_date={to_date.strftime('%d-%m-%Y')}"
    )

    items: list[EventCalendarItem] = []
    try:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()
        raw: list[dict] = resp.json()
        for item in _normalize_main(raw):
            if "financial results" not in item.purpose.lower():
                continue
            items.append(item)
    except Exception:
        logger.exception("Failed to fetch past results from %s", url)

    items.sort(
        key=lambda i: _parse_event_date(i.date) or datetime.min,
        reverse=True,
    )
    return items


def get_event_calendar_cached() -> list[EventCalendarItem]:
    """Return event calendar items, using in-memory cache with 15-min TTL.

    Synchronous wrapper around the async fetch — used by background tasks
    (e.g. ``results_calendar_sync`` in ``backgroundtasks.py``) that run
    outside an event loop.  Uses ``asyncio.run`` to drive the async
    fetch.
    """
    now = time.monotonic()
    if _CALENDAR_CACHE.get("expires_at", 0) > now:
        cached = _CALENDAR_CACHE.get("data")
        if cached is not None:
            return cached

    logger.info("event_calendar: cache miss — fetching from NSE")
    data = asyncio.run(_fetch_event_calendar_raw())
    _CALENDAR_CACHE["data"] = data
    _CALENDAR_CACHE["expires_at"] = now + _CALENDAR_TTL_SECONDS
    return data


def get_past_results_cached() -> list[EventCalendarItem]:
    """Return past results items, using in-memory cache with 15-min TTL.

    Sync wrapper — see ``get_event_calendar_cached`` for rationale.
    """
    now = time.monotonic()
    if _PAST_RESULTS_CACHE.get("expires_at", 0) > now:
        cached = _PAST_RESULTS_CACHE.get("data")
        if cached is not None:
            return cached

    logger.info("event_calendar_past: cache miss — fetching from NSE")
    data = asyncio.run(_fetch_past_results_raw())
    _PAST_RESULTS_CACHE["data"] = data
    _PAST_RESULTS_CACHE["expires_at"] = now + _CALENDAR_TTL_SECONDS
    return data


async def aget_event_calendar_cached() -> list[EventCalendarItem]:
    """Async variant of ``get_event_calendar_cached`` — used by endpoints
    that run inside FastAPI's event loop, where ``asyncio.run`` would
    fail with "asyncio.run() cannot be called from a running event loop".
    """
    now = time.monotonic()
    if _CALENDAR_CACHE.get("expires_at", 0) > now:
        cached = _CALENDAR_CACHE.get("data")
        if cached is not None:
            return cached

    logger.info("event_calendar: cache miss — fetching from NSE")
    data = await _fetch_event_calendar_raw()
    _CALENDAR_CACHE["data"] = data
    _CALENDAR_CACHE["expires_at"] = now + _CALENDAR_TTL_SECONDS
    return data


async def aget_past_results_cached() -> list[EventCalendarItem]:
    """Async variant of ``get_past_results_cached`` (see rationale above)."""
    now = time.monotonic()
    if _PAST_RESULTS_CACHE.get("expires_at", 0) > now:
        cached = _PAST_RESULTS_CACHE.get("data")
        if cached is not None:
            return cached

    logger.info("event_calendar_past: cache miss — fetching from NSE")
    data = await _fetch_past_results_raw()
    _PAST_RESULTS_CACHE["data"] = data
    _PAST_RESULTS_CACHE["expires_at"] = now + _CALENDAR_TTL_SECONDS
    return data


@router.get(
    "/announcements",
    tags=["announcements"],
    responses={
        200: {
            "content": {"application/rss+xml": {}},
            "description": "NSE corporate announcements RSS feed",
        },
        502: {"description": "Failed to fetch from NSE"},
    },
)
async def get_announcements() -> StreamingResponse:
    """Fetch and proxy the NSE announcements RSS feed via the shared client."""
    client = _get_shared_client()
    try:
        resp = await client.get(RSS_URL, timeout=30.0)
        resp.raise_for_status()

        return StreamingResponse(
            content=iter([resp.content]),
            media_type="application/rss+xml",
            headers={
                "Cache-Control": "s-maxage=300, stale-while-revalidate=60",
            },
        )
    except Exception as exc:
        logger.exception("Failed to fetch announcements RSS")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch announcements from NSE: {exc}",
        ) from exc


@router.get(
    "/event-calendar",
    response_model=list[EventCalendarItem],
    tags=["announcements"],
    responses={
        200: {"description": "Combined NSE event calendar (main board + SME)"},
        502: {"description": "Failed to fetch from NSE"},
    },
)
async def get_event_calendar() -> list[EventCalendarItem]:
    """Return upcoming board meeting events from NSE (main board + SME), cached 15 min."""
    try:
        return await aget_event_calendar_cached()
    except Exception as exc:
        logger.exception("Failed to fetch event calendar")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch event calendar from NSE: {exc}",
        ) from exc


@router.get(
    "/event-calendar/past",
    response_model=list[EventCalendarItem],
    tags=["announcements"],
    responses={
        200: {"description": "NSE results published in last 3 months"},
        502: {"description": "Failed to fetch from NSE"},
    },
)
async def get_past_event_calendar() -> list[EventCalendarItem]:
    """Return published financial results from the last 3 months."""
    try:
        return await aget_past_results_cached()
    except Exception as exc:
        logger.exception("Failed to fetch past results calendar")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch past results from NSE: {exc}",
        ) from exc
