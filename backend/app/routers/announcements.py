"""Router for NSE announcements RSS feed and event calendar."""

import logging
import time
from typing import Any

import requests
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


def _fetch_event_calendar_raw() -> list[EventCalendarItem]:
    """Fetch both NSE event calendar endpoints and return merged, deduped list.

    Uses a synchronous requests session with a shared NSE cookie (required by
    NSE anti-bot — fetching the homepage first sets the session cookie).
    """
    session = requests.Session()
    session.headers.update(_NSE_HEADERS)

    # Prime the NSE session cookie (required to bypass anti-bot 401)
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        logger.debug("NSE homepage pre-fetch failed; proceeding anyway")

    items: list[EventCalendarItem] = []
    seen: set[tuple[str, str, str]] = set()

    for url, normalizer in [
        (_CALENDAR_URL_MAIN, _normalize_main),
        (_CALENDAR_URL_SME, _normalize_sme),
    ]:
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            raw: list[dict] = resp.json()
            for item in normalizer(raw):
                key = (item.symbol, item.date, item.purpose)
                if item.symbol and key not in seen:
                    seen.add(key)
                    items.append(item)
        except Exception:
            logger.exception("Failed to fetch event calendar from %s", url)

    # Sort by date ascending (parse "20-Apr-2026" → sortable)
    from datetime import datetime

    def _sort_key(item: EventCalendarItem) -> tuple:
        try:
            return (datetime.strptime(item.date, "%d-%b-%Y"),)
        except ValueError:
            return (datetime.max,)

    items.sort(key=_sort_key)
    return items


def _fetch_past_results_raw() -> list[EventCalendarItem]:
    """Fetch results published in the last 3 months."""
    session = requests.Session()
    session.headers.update(_NSE_HEADERS)

    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        logger.debug("NSE homepage pre-fetch failed; proceeding anyway")

    from datetime import date, timedelta, datetime

    to_date = date.today()
    from_date = to_date - timedelta(days=90)
    url = (
        f"{_CALENDAR_URL_PAST}"
        f"&from_date={from_date.strftime('%d-%m-%Y')}"
        f"&to_date={to_date.strftime('%d-%m-%Y')}"
    )

    items: list[EventCalendarItem] = []
    seen: set[tuple[str, str, str]] = set()
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        raw: list[dict] = resp.json()
        for item in _normalize_main(raw):
            if "financial results" not in item.purpose.lower():
                continue
            key = (item.symbol, item.date, item.purpose)
            if item.symbol and key not in seen:
                seen.add(key)
                items.append(item)
    except Exception:
        logger.exception("Failed to fetch past results from %s", url)

    def _sort_key(item: EventCalendarItem) -> tuple:
        try:
            return (datetime.strptime(item.date, "%d-%b-%Y"),)
        except ValueError:
            return (datetime.min,)

    items.sort(key=_sort_key, reverse=True)
    return items


def get_event_calendar_cached() -> list[EventCalendarItem]:
    """Return event calendar items, using in-memory cache with 15-min TTL.

    Exported so background tasks can call this without going through HTTP.
    """
    now = time.monotonic()
    if _CALENDAR_CACHE.get("expires_at", 0) > now:
        cached = _CALENDAR_CACHE.get("data")
        if cached is not None:
            return cached

    logger.info("event_calendar: cache miss — fetching from NSE")
    data = _fetch_event_calendar_raw()
    _CALENDAR_CACHE["data"] = data
    _CALENDAR_CACHE["expires_at"] = now + _CALENDAR_TTL_SECONDS
    return data


def get_past_results_cached() -> list[EventCalendarItem]:
    """Return past results items, using in-memory cache with 15-min TTL."""
    now = time.monotonic()
    if _PAST_RESULTS_CACHE.get("expires_at", 0) > now:
        cached = _PAST_RESULTS_CACHE.get("data")
        if cached is not None:
            return cached

    logger.info("event_calendar_past: cache miss — fetching from NSE")
    data = _fetch_past_results_raw()
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
    """Fetch and proxy the NSE announcements RSS feed."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    }
    try:
        res = requests.get(RSS_URL, headers=headers, timeout=30)
        res.raise_for_status()

        return StreamingResponse(
            content=iter([res.content]),
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
        return get_event_calendar_cached()
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
        return get_past_results_cached()
    except Exception as exc:
        logger.exception("Failed to fetch past results calendar")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch past results from NSE: {exc}",
        ) from exc
