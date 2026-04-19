"""Router for NSE announcements RSS feed."""

import logging

import requests
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"


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
        from fastapi import HTTPException

        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch announcements from NSE: {exc}",
        ) from exc