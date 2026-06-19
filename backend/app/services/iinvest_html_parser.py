"""iinvest HTML parser.

The iinvest overview page embeds a ``__NEXT_DATA__`` JSON blob. When
fetched server-side (no browser session) the data layer is empty but the
ISIN, symbol, and company name are recoverable from the URL path and the
page's h1.

This parser is the fallback for tier-4 path resolution (when the
``/api/v1/marketdata/symbollookup`` endpoint isn't usable) and a sanity
check on the JS bundle.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any


# URL pattern: /<ISIN>/symbol/ns/<SYMBOL>/<COMPANY-NAME>
_OVERVIEW_URL_RE = re.compile(
    r"^/([A-Z]{2}[A-Z0-9]{9}[0-9])/symbol/ns/([^/]+)/([^?]+)",
    re.IGNORECASE,
)


def parse_overview_html(url: str, html: str) -> dict[str, Any]:
    """Extract identity fields from an iinvest overview page.

    Returns a dict with keys ``isin``, ``symbol``, ``company_name``,
    ``next_data`` (the raw __NEXT_DATA__ blob, or None if absent/empty).
    Never raises — bad input returns empty fields.
    """
    isin: str | None = None
    symbol: str | None = None
    company_name: str | None = None

    # Parse the URL — works even with query string / fragment
    parsed = urllib.parse.urlparse(url)
    m = _OVERVIEW_URL_RE.match(parsed.path)
    if m:
        isin = m.group(1).upper()
        symbol = urllib.parse.unquote(m.group(2))
        company_name = urllib.parse.unquote(m.group(3).replace("-", " ")).strip()

    # Try to extract __NEXT_DATA__ (may be empty, that's fine)
    next_data: Any = None
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        html,
        re.DOTALL,
    )
    if m:
        try:
            next_data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            next_data = None

    # If we don't have a company name from the URL, try the h1
    if not company_name:
        h1 = re.search(r"<h1[^>]*>(.+?)</h1>", html, re.DOTALL | re.IGNORECASE)
        if h1:
            company_name = re.sub(r"<[^>]+>", "", h1.group(1)).strip()
            # Decode HTML entities
            company_name = (
                company_name.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
            )

    return {
        "isin": isin,
        "symbol": symbol,
        "company_name": company_name,
        "next_data": next_data,
    }
