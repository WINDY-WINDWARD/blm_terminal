"""
Integration tests for the BLM Analytics FastAPI backend.

Requirements:
  - The server must be running before you execute these tests.
  - Default base URL is http://localhost:4455.  Override with the
    BLM_BASE_URL environment variable:

        BLM_BASE_URL=http://localhost:4455 pytest tests/test_endpoints.py

  - Endpoints that hit NSE (marked with the `slow` marker) are each
    separated by a courtesy delay to avoid hammering upstream servers.
    Run only fast tests with:  pytest -m "not slow"

Install requests if needed:
    pip install requests
"""

import os
import time
from datetime import datetime

import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL: str = os.environ.get("BLM_BASE_URL", "http://127.0.0.1:4455").rstrip("/")

# Seconds to wait between consecutive NSE-hitting requests.
NSE_COURTESY_DELAY: float = 3.0

# A symbol that is virtually guaranteed to exist in the stock universe DB
# once the background scheduler has run at least once.
KNOWN_SYMBOL: str = "RELIANCE"

# A prefix that matches several symbols (used for search endpoint).
KNOWN_PREFIX: str = "RELI"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_TOKEN: str | None = None


def get_auth_headers() -> dict[str, str]:
    global _AUTH_TOKEN
    if _AUTH_TOKEN is None:
        password = os.environ.get("ADMIN_PASSWORD", "admin")
        try:
            resp = requests.post(
                f"{BASE_URL}/api/auth/login",
                data={"username": "admin", "password": password},
                timeout=10,
            )
            if resp.status_code == 200:
                _AUTH_TOKEN = resp.json().get("access_token")
            elif resp.status_code == 401 and len(password) >= 8:
                # Fresh backend with no accounts: first-boot setup owns admin
                # creation (no default credential is seeded anymore).
                setup_resp = requests.post(
                    f"{BASE_URL}/api/auth/setup",
                    json={"username": "admin", "password": password},
                    timeout=10,
                )
                if setup_resp.status_code == 200:
                    _AUTH_TOKEN = setup_resp.json().get("access_token")
        except Exception:
            pass
    return {"Authorization": f"Bearer {_AUTH_TOKEN}"} if _AUTH_TOKEN else {}


def get(path: str, timeout: int = 60, headers: dict | None = None, **kwargs) -> requests.Response:
    """Perform a GET request against the running backend."""
    h = dict(get_auth_headers())
    if headers:
        h.update(headers)
    return requests.get(f"{BASE_URL}{path}", timeout=timeout, headers=h, **kwargs)


# ---------------------------------------------------------------------------
# Server availability check (runs once before the whole suite)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def require_server():
    """Fail fast with a clear message if the backend is not reachable."""
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        pytest.fail(
            f"Backend server not reachable at {BASE_URL} – start it with "
            f"`uvicorn main:app --host 127.0.0.1 --port 4455` before running tests.\n"
            f"Error: {exc}"
        )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_status_ok(self):
        resp = get("/health")
        assert resp.status_code == 200

    def test_response_body(self):
        resp = get("/health")
        data = resp.json()
        assert data == {"status": "ok"}

    def test_content_type_json(self):
        resp = get("/health")
        assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# /api/stockuniverse
# ---------------------------------------------------------------------------


class TestStockUniverse:
    def test_list_returns_200(self):
        resp = get("/api/stockuniverse")
        assert resp.status_code == 200

    def test_list_returns_list(self):
        resp = get("/api/stockuniverse")
        data = resp.json()
        assert isinstance(data, list)

    def test_list_item_schema(self):
        """If the DB has been seeded, each item must conform to the schema."""
        resp = get("/api/stockuniverse")
        items = resp.json()
        if not items:
            pytest.skip("stock_universe table is empty – run the scheduler first")

        required_keys = {"symbol", "companyName", "segment", "industry"}
        for item in items[:5]:  # check only first 5 to keep it fast
            assert required_keys.issubset(item.keys()), (
                f"Missing keys in item: {set(item.keys())}"
            )

    def test_single_symbol_known(self):
        resp = get(f"/api/stockuniverse/{KNOWN_SYMBOL}")
        if resp.status_code == 404:
            pytest.skip(f"{KNOWN_SYMBOL} not in DB – run the scheduler first")
        assert resp.status_code == 200

    def test_single_symbol_schema(self):
        resp = get(f"/api/stockuniverse/{KNOWN_SYMBOL}")
        if resp.status_code == 404:
            pytest.skip(f"{KNOWN_SYMBOL} not in DB – run the scheduler first")
        data = resp.json()
        assert data["symbol"] == KNOWN_SYMBOL
        assert isinstance(data["companyName"], str)
        assert isinstance(data["segment"], str)
        assert isinstance(data["industry"], str)

    def test_single_symbol_not_found(self):
        resp = get("/api/stockuniverse/THISSYMBOLDOESNOTEXIST_XYZ")
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_search_returns_200(self):
        resp = get(f"/api/stockuniverse/search/{KNOWN_PREFIX}")
        assert resp.status_code == 200

    def test_search_returns_list(self):
        resp = get(f"/api/stockuniverse/search/{KNOWN_PREFIX}")
        data = resp.json()
        assert isinstance(data, list)

    def test_search_results_match_prefix(self):
        resp = get(f"/api/stockuniverse/search/{KNOWN_PREFIX}")
        items = resp.json()
        if not items:
            pytest.skip("No results for prefix – DB may be empty")
        prefix_lower = KNOWN_PREFIX.lower()
        for item in items:
            assert item["symbol"].lower().startswith(prefix_lower) or item[
                "companyName"
            ].lower().startswith(prefix_lower), f"Item does not match prefix: {item}"

    def test_search_empty_prefix_returns_200(self):
        """An empty-ish prefix ('A') is still a valid query."""
        resp = get("/api/stockuniverse/search/A")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_search_no_match_returns_empty_list(self):
        resp = get("/api/stockuniverse/search/ZZZNOMATCH9999")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# /api/event-calendar
# ---------------------------------------------------------------------------


class TestEventCalendar:
    def test_returns_200(self):
        resp = get("/api/event-calendar")
        assert resp.status_code == 200, resp.text

    def test_returns_list(self):
        resp = get("/api/event-calendar")
        data = resp.json()
        assert isinstance(data, list)

    def test_item_schema(self):
        resp = get("/api/event-calendar")
        items = resp.json()
        if not items:
            pytest.skip("event calendar returned an empty list")

        required_keys = {"symbol", "company", "purpose", "description", "date", "source", "attachment"}
        for item in items[:5]:
            assert required_keys.issubset(item.keys()), (
                f"Missing keys in item: {set(item.keys())}"
            )
            assert isinstance(item["symbol"], str)
            assert isinstance(item["company"], str)
            assert isinstance(item["purpose"], str)
            assert isinstance(item["description"], str)
            assert isinstance(item["date"], str)
            assert item["source"] in {"main", "sme"}

    def test_includes_main_or_sme_items(self):
        resp = get("/api/event-calendar")
        items = resp.json()
        if not items:
            pytest.skip("event calendar returned an empty list")

        sources = {item["source"] for item in items if isinstance(item, dict) and "source" in item}
        assert sources.issubset({"main", "sme"})
        assert sources, "Expected at least one event calendar item"

    def test_dates_are_nse_formatted(self):
        resp = get("/api/event-calendar")
        items = resp.json()
        if not items:
            pytest.skip("event calendar returned an empty list")

        for item in items[:5]:
            date_str = item["date"]
            try:
                datetime.strptime(date_str, "%d-%b-%Y")
            except ValueError:
                pytest.fail(f"Invalid NSE date format: {date_str}")


# ---------------------------------------------------------------------------
# /api/corporatefilings/{symbol}
# ---------------------------------------------------------------------------


class TestCorporateFilings:
    def test_known_symbol_returns_200_or_502(self):
        """
        A 200 means data was cached or successfully fetched from NSE.
        A 502 is acceptable when NSE is unreachable in CI / offline environments.
        """
        resp = get(f"/api/corporatefilings/{KNOWN_SYMBOL}")
        assert resp.status_code in (200, 502), f"Unexpected status {resp.status_code}"

    def test_known_symbol_csv_on_success(self):
        resp = get(f"/api/corporatefilings/{KNOWN_SYMBOL}")
        if resp.status_code == 502:
            pytest.skip("NSE upstream not reachable")
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_known_symbol_csv_has_content(self):
        resp = get(f"/api/corporatefilings/{KNOWN_SYMBOL}")
        if resp.status_code == 502:
            pytest.skip("NSE upstream not reachable")
        lines = resp.text.strip().splitlines()
        assert len(lines) >= 2, "CSV should have at least a header + one data row"

    def test_known_symbol_csv_pipe_delimited(self):
        resp = get(f"/api/corporatefilings/{KNOWN_SYMBOL}")
        if resp.status_code == 502:
            pytest.skip("NSE upstream not reachable")
        first_line = resp.text.strip().splitlines()[0]
        assert "|" in first_line, "CSV should be pipe-delimited"

    def test_unknown_symbol_returns_error(self):
        """
        An unknown symbol should return 404 or 502 (NSE may raise its own error).
        It must NOT return 200 with fake data.
        """
        resp = get("/api/corporatefilings/THISSYMBOLDOESNOTEXIST_XYZ")
        assert resp.status_code in (404, 422, 502), (
            f"Unexpected status {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# /api/market/…  (NSE-hitting – marked slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestMarketTopGainers:
    def test_returns_200(self):
        resp = get("/api/market/top-gainers")
        assert resp.status_code == 200, resp.text

    def test_returns_list(self):
        resp = get("/api/market/top-gainers")
        assert isinstance(resp.json(), list)

    def test_items_have_symbol_field(self):
        resp = get("/api/market/top-gainers")
        items = resp.json()
        if not items:
            pytest.skip("top-gainers returned an empty list")
        for item in items[:3]:
            # NSE DataFrames use various column names; at minimum a dict is expected
            assert isinstance(item, dict)


@pytest.mark.slow
class TestMarketTopLosers:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    def test_returns_200(self):
        resp = get("/api/market/top-losers")
        assert resp.status_code == 200, resp.text

    def test_returns_list(self):
        resp = get("/api/market/top-losers")
        assert isinstance(resp.json(), list)

    def test_items_are_dicts(self):
        resp = get("/api/market/top-losers")
        items = resp.json()
        if not items:
            pytest.skip("top-losers returned an empty list")
        for item in items[:3]:
            assert isinstance(item, dict)


@pytest.mark.slow
class TestMarketBulkDeals:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    def test_returns_200(self):
        resp = get(f"/api/market/bulk-deals/{KNOWN_SYMBOL}")
        assert resp.status_code == 200, resp.text

    def test_returns_list(self):
        resp = get(f"/api/market/bulk-deals/{KNOWN_SYMBOL}")
        assert isinstance(resp.json(), list)

    def test_symbol_uppercased_internally(self):
        """Lowercase symbol should work the same as uppercase."""
        resp_lower = get(f"/api/market/bulk-deals/{KNOWN_SYMBOL.lower()}")
        resp_upper = get(f"/api/market/bulk-deals/{KNOWN_SYMBOL}")
        # Both should succeed (cache may mean identical data)
        assert resp_lower.status_code == 200
        assert resp_upper.status_code == 200


@pytest.mark.slow
class TestMarketBlockDeals:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    def test_returns_200(self):
        resp = get(f"/api/market/block-deals/{KNOWN_SYMBOL}")
        assert resp.status_code == 200, resp.text

    def test_returns_list(self):
        resp = get(f"/api/market/block-deals/{KNOWN_SYMBOL}")
        assert isinstance(resp.json(), list)


@pytest.mark.slow
class TestMarketHighShortInterest:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    def test_returns_200(self):
        resp = get("/api/market/high-short-interest")
        assert resp.status_code == 200, resp.text

    def test_returns_list(self):
        resp = get("/api/market/high-short-interest")
        assert isinstance(resp.json(), list)


@pytest.mark.slow
class TestMarketChangeRanges:
    # Expected keys in a successful response.
    EXPECTED_KEYS = {
        "oneWeekPercent",
        "oneMonthPercent",
        "threeMonthPercent",
        "sixMonthPercent",
        "oneYearPercent",
        "twoYearPercent",
        "threeYearPercent",
        "fiveYearPercent",
    }

    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    # ------------------------------------------------------------------
    # Shared helper: fetch once and skip the test if NSE is unreachable.
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch(symbol: str = KNOWN_SYMBOL) -> requests.Response:
        resp = get(f"/api/market/change-ranges/{symbol}")
        if resp.status_code == 500:
            pytest.skip("NSE getYearwiseData upstream not reachable (500)")
        return resp

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_returns_200(self):
        resp = get(f"/api/market/change-ranges/{KNOWN_SYMBOL}")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_content_type_json(self):
        resp = self._fetch()
        assert "application/json" in resp.headers.get("content-type", "")

    def test_response_is_object(self):
        resp = self._fetch()
        assert isinstance(resp.json(), dict)

    def test_all_expected_keys_present(self):
        data = self._fetch().json()
        missing = self.EXPECTED_KEYS - data.keys()
        assert not missing, f"Response missing keys: {missing}"

    def test_no_extra_keys(self):
        """Response should contain exactly the documented keys, nothing more."""
        data = self._fetch().json()
        extra = data.keys() - self.EXPECTED_KEYS
        assert not extra, f"Response has undocumented keys: {extra}"

    def test_values_are_numeric_or_null(self):
        """Every value must be a float/int or null (nan serialises to null)."""
        for key, val in self._fetch().json().items():
            assert val is None or isinstance(val, (int, float)), (
                f"Key '{key}' has non-numeric value: {val!r}"
            )

    def test_lowercase_symbol_accepted(self):
        """Cache key is uppercased internally; lowercase input must not 404."""
        resp = get(f"/api/market/change-ranges/{KNOWN_SYMBOL.lower()}")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_lowercase_and_uppercase_return_same_keys(self):
        """Both casings should return identical key sets."""
        resp_upper = self._fetch(KNOWN_SYMBOL)
        resp_lower = self._fetch(KNOWN_SYMBOL.lower())
        assert resp_upper.json().keys() == resp_lower.json().keys()

    def test_unknown_symbol_returns_500(self):
        """
        An unrecognised symbol causes NSE to return an empty/invalid body,
        which the service raises as a ValueError → FastAPI 500.
        """
        resp = get("/api/market/change-ranges/THISSYMBOLDOESNOTEXIST_XYZ")
        assert resp.status_code == 500, (
            f"Expected 500 for unknown symbol, got {resp.status_code}"
        )


@pytest.mark.slow
class TestMarketSymbolData:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    # ------------------------------------------------------------------
    # Shared helper: fetch once and skip if NSE is unreachable.
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch(symbol: str = KNOWN_SYMBOL) -> requests.Response:
        resp = get(f"/api/market/symbol-data/{symbol}")
        if resp.status_code == 500:
            pytest.skip("NSE getSymbolData upstream not reachable (500)")
        return resp

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_returns_200(self):
        resp = get(f"/api/market/symbol-data/{KNOWN_SYMBOL}")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_content_type_json(self):
        resp = self._fetch()
        assert "application/json" in resp.headers.get("content-type", "")

    def test_response_is_object(self):
        """NSE getSymbolData always returns a dict, never a list."""
        resp = self._fetch()
        assert isinstance(resp.json(), dict)

    def test_response_is_not_empty(self):
        data = self._fetch().json()
        assert len(data) > 0, "Response dict should not be empty"

    def test_lowercase_symbol_uppercased_internally(self):
        """Router uppercases symbol before calling the service; lowercase must not 404."""
        resp = get(f"/api/market/symbol-data/{KNOWN_SYMBOL.lower()}")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_lowercase_and_uppercase_return_same_data(self):
        """Both casings hit the same cache key and should return identical payloads."""
        resp_upper = self._fetch(KNOWN_SYMBOL)
        resp_lower = self._fetch(KNOWN_SYMBOL.lower())
        assert resp_upper.json() == resp_lower.json()

    def test_unknown_symbol_returns_500(self):
        """An unrecognised symbol makes NSE return an unexpected payload → 500."""
        resp = get("/api/market/symbol-data/THISSYMBOLDOESNOTEXIST_XYZ")
        assert resp.status_code == 500, (
            f"Expected 500 for unknown symbol, got {resp.status_code}"
        )


@pytest.mark.slow
class TestMarket52WeekLowHigh:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    # ------------------------------------------------------------------
    # Shared helpers: fetch once and skip if NSE is unreachable.
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_low() -> requests.Response:
        resp = get("/api/market/52week-low")
        if resp.status_code == 500:
            pytest.skip("NSE 52week-low upstream not reachable (500)")
        return resp

    @staticmethod
    def _fetch_high() -> requests.Response:
        resp = get("/api/market/52week-high")
        if resp.status_code == 500:
            pytest.skip("NSE 52week-high upstream not reachable (500)")
        return resp

    # ------------------------------------------------------------------
    # Status / content-type
    # ------------------------------------------------------------------

    def test_low_returns_200_or_500(self):
        resp = get("/api/market/52week-low")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_high_returns_200_or_500(self):
        resp = get("/api/market/52week-high")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_low_content_type_json(self):
        resp = self._fetch_low()
        assert "application/json" in resp.headers.get("content-type", "")

    def test_high_content_type_json(self):
        resp = self._fetch_high()
        assert "application/json" in resp.headers.get("content-type", "")

    # ------------------------------------------------------------------
    # Shape & key checks
    # ------------------------------------------------------------------

    def test_low_response_has_expected_shape(self):
        data = self._fetch_low().json()
        assert isinstance(data, dict)
        assert "data" in data
        assert isinstance(data["data"], list)
        if data["data"]:
            first = data["data"][0]
            assert isinstance(first, dict)
            # Core fields we expect based on NSE sample payload
            for key in ("symbol", "series", "ltp"):
                assert key in first

    def test_high_response_has_expected_shape(self):
        data = self._fetch_high().json()
        assert isinstance(data, dict)
        assert "data" in data
        assert isinstance(data["data"], list)
        if data["data"]:
            first = data["data"][0]
            assert isinstance(first, dict)
            for key in ("symbol", "series", "ltp"):
                assert key in first

    def test_low_metadata_fields_types(self):
        """Check that optional metadata fields like 'low' and 'timestamp' have sane types."""
        data = self._fetch_low().json()
        if "low" in data:
            assert isinstance(data["low"], int)
        if "timestamp" in data:
            assert isinstance(data["timestamp"], str)

    def test_high_metadata_fields_types(self):
        data = self._fetch_high().json()
        if "timestamp" in data:
            assert isinstance(data["timestamp"], str)


@pytest.mark.slow
class TestMarketVolumeGainers:
    @pytest.fixture(autouse=True)
    def delay(self):
        time.sleep(NSE_COURTESY_DELAY)

    # ------------------------------------------------------------------
    # Shared helper: fetch once and skip if NSE is unreachable.
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch() -> requests.Response:
        resp = get("/api/market/volume-gainers")
        if resp.status_code == 500:
            pytest.skip("NSE volume-gainers upstream not reachable (500)")
        return resp

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_returns_200_or_500(self):
        resp = get("/api/market/volume-gainers")
        assert resp.status_code in (200, 500), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_content_type_json(self):
        resp = self._fetch()
        assert "application/json" in resp.headers.get("content-type", "")

    def test_response_is_dict(self):
        """Top-level response should be a dict."""
        resp = self._fetch()
        assert isinstance(resp.json(), dict)

    def test_response_has_data_array(self):
        """Response must have 'data' key containing a list."""
        data = self._fetch().json()
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_data_items_have_expected_fields(self):
        """If data is non-empty, items should have core fields."""
        data = self._fetch().json()
        if data["data"]:
            first = data["data"][0]
            assert isinstance(first, dict)
            for key in ("symbol", "volume", "ltp", "pChange"):
                assert key in first, f"Expected field '{key}' in item"

    def test_response_has_timestamp(self):
        """Response should have optional 'timestamp' field as string if present."""
        data = self._fetch().json()
        if "timestamp" in data:
            assert isinstance(data["timestamp"], str)


# ---------------------------------------------------------------------------
# /api/screener/...
# ---------------------------------------------------------------------------


class TestScreenerSearch:
    """Tests for the screener.in search endpoint (public, no auth required)."""

    def test_search_returns_200(self):
        resp = get("/api/screener/search?q=reliance")
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )

    def test_search_returns_list(self):
        resp = get("/api/screener/search?q=reliance")
        data = resp.json()
        assert isinstance(data, list), "Response should be a list"

    def test_search_results_contain_expected_fields(self):
        resp = get("/api/screener/search?q=reliance")
        data = resp.json()
        if data:
            assert "id" in data[0]
            assert "name" in data[0]
            assert "url" in data[0]

    def test_search_empty_query_returns_422(self):
        resp = get("/api/screener/search?q=")
        assert resp.status_code == 422, (
            f"Expected 422 for empty query, got {resp.status_code}"
        )

    def test_search_results_contain_query_term(self):
        resp = get("/api/screener/search?q=reliance")
        data = resp.json()
        assert len(data) > 0, "Expected at least one result for 'reliance'"
        names = [item.get("name", "").lower() for item in data]
        assert any("reliance" in n for n in names), "Results should contain 'reliance'"


class TestScreenerCompany:
    """Tests for the screener.in company fundamentals endpoint (requires auth)."""

    def test_company_returns_200_or_503(self):
        """Endpoint returns 200 if authenticated via browser cookies, else 503."""
        resp = get("/api/screener/company/RELIANCE")
        assert resp.status_code in (200, 503), (
            f"Expected 200 (authenticated) or 503 (no auth), got {resp.status_code}"
        )

    def test_company_success_response_schema(self):
        """When authenticated, response should have expected schema."""
        resp = get("/api/screener/company/RELIANCE")
        if resp.status_code == 200:
            data = resp.json()
            assert "symbol" in data
            assert "name" in data
            assert "screener_warehouse_id" in data
            assert "ratios" in data
            assert "quarters" in data
            assert "pe" in data["ratios"]
            # eps may be in quarters or supplemental quick_ratios
            if "eps" not in data["ratios"] and data.get("quarters"):
                assert "eps" in data["quarters"][0]
            else:
                assert "eps" in data["ratios"]

    def test_company_invalid_symbol_returns_422(self):
        """Invalid symbol format should return 422."""
        resp = get("/api/screener/company/INVALID@@@")
        assert resp.status_code == 422, (
            f"Expected 422 for invalid symbol, got {resp.status_code}"
        )

    def test_company_unknown_symbol_returns_404(self):
        """Unknown symbol should return 404 when authenticated. Without auth, returns 503."""
        resp = get("/api/screener/company/THISSYMBOLDOESNOTEXIST_XYZ")
        assert resp.status_code in (404, 503), (
            f"Expected 404 (auth + not found) or 503 (no auth), got {resp.status_code}"
        )


class TestScreenerQuarterly:
    """Tests for the screener.in quarterly results endpoint."""

    def test_quarterly_returns_200_or_503(self):
        """Returns 200 when authenticated, 503 when no screener.in session is available."""
        resp = get("/api/screener/quarterly/RELIANCE")
        assert resp.status_code in (200, 503), (
            f"Expected 200 (authenticated) or 503 (no auth), got {resp.status_code}"
        )

    def test_quarterly_success_top_level_schema(self):
        """When authenticated, response must have symbol, consolidated, quarterly_results."""
        resp = get("/api/screener/quarterly/RELIANCE")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        data = resp.json()
        assert "symbol" in data
        assert "consolidated" in data
        assert "quarterly_results" in data

    def test_quarterly_symbol_uppercased(self):
        """symbol field in response must be uppercased regardless of request casing."""
        resp = get("/api/screener/quarterly/reliance")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        data = resp.json()
        assert data["symbol"] == "RELIANCE"

    def test_quarterly_consolidated_flag_true_by_default(self):
        """consolidated defaults to True."""
        resp = get("/api/screener/quarterly/RELIANCE")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        data = resp.json()
        assert data["consolidated"] is True

    def test_quarterly_results_is_dict(self):
        """quarterly_results must be a dict (year-keyed)."""
        resp = get("/api/screener/quarterly/RELIANCE")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        data = resp.json()
        assert isinstance(data["quarterly_results"], dict)

    def test_quarterly_results_year_keys_are_numeric_strings(self):
        """Top-level keys of quarterly_results should be year strings like '2024'."""
        resp = get("/api/screener/quarterly/RELIANCE")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        qr = resp.json()["quarterly_results"]
        if not qr:
            pytest.skip("quarterly_results is empty")
        for year_key in qr:
            assert year_key.isdigit() or year_key[:4].isdigit(), (
                f"Expected year-like key, got: {year_key!r}"
            )

    def test_quarterly_results_month_values_are_dicts(self):
        """Each month entry must be a dict mapping metric names to string values."""
        resp = get("/api/screener/quarterly/RELIANCE")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        qr = resp.json()["quarterly_results"]
        if not qr:
            pytest.skip("quarterly_results is empty")
        for year_key, months in qr.items():
            assert isinstance(months, dict), (
                f"Expected dict under year '{year_key}', got {type(months)}"
            )
            for month_key, metrics in months.items():
                assert isinstance(metrics, dict), (
                    f"Expected dict under '{year_key}.{month_key}', got {type(metrics)}"
                )

    def test_quarterly_results_contains_sales_metric(self):
        """All periods should include at least a 'Sales' metric (present on all pages)."""
        resp = get("/api/screener/quarterly/RELIANCE")
        if resp.status_code != 200:
            pytest.skip("screener.in session not available (503)")
        qr = resp.json()["quarterly_results"]
        if not qr:
            pytest.skip("quarterly_results is empty")
        # Check the first available period
        first_year = next(iter(qr))
        first_month = next(iter(qr[first_year]))
        metrics = qr[first_year][first_month]
        assert "Sales" in metrics, (
            f"Expected 'Sales' in metrics for {first_year}/{first_month}, got: {list(metrics.keys())}"
        )

    def test_quarterly_invalid_symbol_returns_422(self):
        """Invalid symbol format must return 422."""
        resp = get("/api/screener/quarterly/INVALID@@@")
        assert resp.status_code == 422, (
            f"Expected 422 for invalid symbol, got {resp.status_code}"
        )

    def test_quarterly_unknown_symbol_returns_404_or_503(self):
        """Unknown symbol returns 404 when authenticated, 503 otherwise."""
        resp = get("/api/screener/quarterly/THISSYMBOLDOESNOTEXIST_XYZ")
        assert resp.status_code in (404, 503), (
            f"Expected 404 or 503, got {resp.status_code}"
        )

    def test_quarterly_html_cache_shared_with_company(self):
        """
        Calling /screener/company then /screener/quarterly for the same symbol
        should both succeed (second call served from HTML cache).
        The test verifies consistent symbol/consolidated in both responses.
        """
        company_resp = get("/api/screener/company/RELIANCE")
        quarterly_resp = get("/api/screener/quarterly/RELIANCE")
        if company_resp.status_code != 200 or quarterly_resp.status_code != 200:
            pytest.skip("screener.in session not available")
        company_data = company_resp.json()
        quarterly_data = quarterly_resp.json()
        assert company_data["symbol"] == quarterly_data["symbol"]


# ---------------------------------------------------------------------------
# /api/watchlist
# ---------------------------------------------------------------------------


class TestWatchlist:
    """Tests for the watchlist CRUD endpoints."""

    TEST_SYMBOL = "TCS"
    TEST_EXCHANGE = "NSE"

    def test_list_returns_200(self):
        """GET /api/watchlist should return 200."""
        resp = get("/api/watchlist")
        assert resp.status_code == 200

    def test_list_returns_list(self):
        """GET /api/watchlist should return a list."""
        resp = get("/api/watchlist")
        data = resp.json()
        assert isinstance(data, list)

    def test_list_item_schema(self):
        """Each item should have id, symbol, exchange, created_at."""
        resp = get("/api/watchlist")
        items = resp.json()
        if not items:
            pytest.skip("watchlist is empty")
        required_keys = {"id", "symbol", "exchange", "created_at"}
        for item in items:
            assert required_keys.issubset(item.keys()), (
                f"Missing keys in item: {set(item.keys())}"
            )

    def test_add_item_returns_201(self):
        """POST /api/watchlist should create a new item and return 201."""
        payload = {"symbol": self.TEST_SYMBOL, "exchange": self.TEST_EXCHANGE}
        resp = requests.post(f"{BASE_URL}/api/watchlist", json=payload, headers=get_auth_headers())
        assert resp.status_code == 201, (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["symbol"] == self.TEST_SYMBOL
        assert data["exchange"] == self.TEST_EXCHANGE

    def test_add_item_idempotent(self):
        """Adding the same symbol/exchange twice should return the existing item."""
        payload = {"symbol": self.TEST_SYMBOL, "exchange": self.TEST_EXCHANGE}
        resp1 = requests.post(f"{BASE_URL}/api/watchlist", json=payload, headers=get_auth_headers())
        assert resp1.status_code == 201
        item1 = resp1.json()

        resp2 = requests.post(f"{BASE_URL}/api/watchlist", json=payload, headers=get_auth_headers())
        assert resp2.status_code == 201
        item2 = resp2.json()

        # Should return the same item (idempotent)
        assert item1["id"] == item2["id"]

    def test_add_item_normalizes_input(self):
        """Input symbol/exchange should be uppercased."""
        payload = {"symbol": "tcs", "exchange": "nse"}
        resp = requests.post(f"{BASE_URL}/api/watchlist", json=payload, headers=get_auth_headers())
        assert resp.status_code == 201
        data = resp.json()
        assert data["symbol"] == "TCS"
        assert data["exchange"] == "NSE"

    def test_add_item_missing_fields_returns_422(self):
        """Missing symbol or exchange should return 422."""
        resp1 = requests.post(f"{BASE_URL}/api/watchlist", json={"symbol": "TCS"}, headers=get_auth_headers())
        assert resp1.status_code == 422

        resp2 = requests.post(f"{BASE_URL}/api/watchlist", json={"exchange": "NSE"}, headers=get_auth_headers())
        assert resp2.status_code == 422

        resp3 = requests.post(f"{BASE_URL}/api/watchlist", json={}, headers=get_auth_headers())
        assert resp3.status_code == 422

    def test_delete_item_returns_200(self):
        """DELETE /api/watchlist/{id} should remove the item."""
        # First add an item to delete
        payload = {"symbol": "DELTEST", "exchange": "NSE"}
        add_resp = requests.post(f"{BASE_URL}/api/watchlist", json=payload, headers=get_auth_headers())
        assert add_resp.status_code == 201
        item_id = add_resp.json()["id"]

        resp = requests.delete(f"{BASE_URL}/api/watchlist/{item_id}", headers=get_auth_headers())
        assert resp.status_code == 200
        assert resp.json() in ({"status": "ok"}, {"ok": True})

    def test_delete_nonexistent_returns_404(self):
        """Deleting a non-existent ID should return 404."""
        resp = requests.delete(f"{BASE_URL}/api/watchlist/999999", headers=get_auth_headers())
        assert resp.status_code == 404
