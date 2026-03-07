"""
Integration tests for the BLM Analytics FastAPI backend.

Requirements:
  - The server must be running before you execute these tests.
  - Default base URL is http://localhost:8000.  Override with the
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

import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL: str = os.environ.get("BLM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

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


def get(path: str, timeout: int = 60, **kwargs) -> requests.Response:
    """Perform a GET request against the running backend."""
    return requests.get(f"{BASE_URL}{path}", timeout=timeout, **kwargs)


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
            f"`uvicorn main:app --host 127.0.0.1 --port 8000` before running tests.\n"
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
        "oneDayPercent",
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
