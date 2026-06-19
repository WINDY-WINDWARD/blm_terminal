"""Tests for the iinvest HTML parser.

The iinvest overview page embeds a ``__NEXT_DATA__`` JSON blob in the
HTML. The data layer is empty when fetched without a browser session
(server-side rendering is incomplete), but the ISIN is in the URL path
and company name is in the page title / h1.

The parser should:
  1. Extract the ISIN from the URL path (the first segment after iinvest.cogencis.com/)
  2. Extract the symbol from /symbol/ns/{SYM}/ segment
  3. Extract the company name from the URL slug or h1 (whichever is cleaner)
  4. NOT crash on empty __NEXT_DATA__ (which is the live case)
  5. Handle the M&M URL encoding (M%26M)
"""

from __future__ import annotations

import pytest


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Reliance Industries Ltd - iinvest</title>
  <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"data":{"response":{"OV":[]}}}}}
  </script>
</head>
<body>
  <h1>Reliance Industries Limited</h1>
</body>
</html>
"""


SAMPLE_HTML_NEXT_DATA_EMPTY = """<!DOCTYPE html>
<html>
<head>
  <title>iinvest</title>
  <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"data":[]}}}
  </script>
</head>
<body>
  <h1>Mahindra &amp; Mahindra Limited</h1>
</body>
</html>
"""


class TestParseOverviewHtml:
    def test_extracts_isin_from_url(self):
        from app.services.iinvest_html_parser import parse_overview_html
        result = parse_overview_html(
            url="https://iinvest.cogencis.com/INE002A01018/symbol/ns/RELIANCE/Reliance%20Industries%20Limited?tab=overview",
            html=SAMPLE_HTML,
        )
        assert result["isin"] == "INE002A01018"

    def test_extracts_symbol_from_url(self):
        from app.services.iinvest_html_parser import parse_overview_html
        result = parse_overview_html(
            url="https://iinvest.cogencis.com/INE002A01018/symbol/ns/RELIANCE/Reliance%20Industries%20Limited?tab=overview",
            html=SAMPLE_HTML,
        )
        assert result["symbol"] == "RELIANCE"

    def test_handles_m_and_m_ampersand(self):
        """M&M is URL-encoded as M%26M in iinvest URLs."""
        from app.services.iinvest_html_parser import parse_overview_html
        result = parse_overview_html(
            url="https://iinvest.cogencis.com/INE101A01026/symbol/ns/M%26M/Mahindra%20%26%20Mahindra%20Limited?tab=overview",
            html=SAMPLE_HTML_NEXT_DATA_EMPTY,
        )
        assert result["isin"] == "INE101A01026"
        assert result["symbol"] == "M&M"  # decoded

    def test_does_not_crash_on_empty_next_data(self):
        """The real iinvest SSR data is empty; parser must still work."""
        from app.services.iinvest_html_parser import parse_overview_html
        result = parse_overview_html(
            url="https://iinvest.cogencis.com/INE002A01018/symbol/ns/RELIANCE/Reliance%20Industries%20Limited?tab=overview",
            html=SAMPLE_HTML_NEXT_DATA_EMPTY,
        )
        # We should still get ISIN and symbol from the URL
        assert result["isin"] == "INE002A01018"
        assert result["symbol"] == "RELIANCE"

    def test_extracts_company_name_from_h1(self):
        from app.services.iinvest_html_parser import parse_overview_html
        result = parse_overview_html(
            url="https://iinvest.cogencis.com/INE002A01018/symbol/ns/RELIANCE/Reliance%20Industries%20Limited?tab=overview",
            html=SAMPLE_HTML,
        )
        # h1 is the cleanest source when __NEXT_DATA__ is empty
        assert "Reliance" in result["company_name"]

    def test_returns_empty_when_url_has_no_isin(self):
        from app.services.iinvest_html_parser import parse_overview_html
        result = parse_overview_html(
            url="https://iinvest.cogencis.com/",
            html="<html><body>homepage</body></html>",
        )
        assert result["isin"] is None
        assert result["symbol"] is None
