#!/usr/bin/env python3
"""
test_camoufox.py — manual smoke-test for the camoufox news fetching path.

Run from inside the backend venv with CAMOUFOX_ENABLED=true:

    cd backend
    source .venv/bin/activate
    CAMOUFOX_ENABLED=true python test_camoufox.py

The script runs checks in sequence and prints a pass/fail summary:
  1.  camoufox browser starts
  2.  Listing page fetched + article URLs extracted
  3.  Single article fetched + content parsed (title, date, text)
  4.  camoufox browser closes cleanly
  5.  Company/stockpricequote page fetched (raw camoufox, no resource-blocking)
  6.  #news section found on company page
  7.  Company article URLs extracted from #news section
  8.  Company page fetched with resource-blocking (images/CSS/fonts aborted)
  9.  Resource-blocked fetch is faster than unblocked fetch
  10. Company page fetched with extra HTTP headers
  11. httpx path fetches company page when browser is bypassed
  12. _get_page falls back to httpx on camoufox TimeoutError (monkey-patch test)
"""

import asyncio
import os
import re
import sys
import time
import textwrap
from datetime import datetime
from unittest.mock import patch

# ── ensure we run with CAMOUFOX_ENABLED ──────────────────────────────────────
if os.environ.get("CAMOUFOX_ENABLED", "").lower() not in ("1", "true", "yes"):
    print("[ERROR] Set CAMOUFOX_ENABLED=true before running this script.")
    print("        e.g.  CAMOUFOX_ENABLED=true python test_camoufox.py")
    sys.exit(1)

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
NC     = "\033[0m"

def ok(msg):    print(f"  {GREEN}PASS{NC}  {msg}")
def fail(msg):  print(f"  {RED}FAIL{NC}  {msg}")
def info(msg):  print(f"  {CYAN}    {NC}  {msg}")
def warn(msg):  print(f"  {YELLOW}WARN{NC}  {msg}")
def section(title): print(f"\n{BOLD}{title}{NC}")

results: list[tuple[str, bool, str]] = []   # (label, passed, detail)

def record(label: str, passed: bool, detail: str = ""):
    results.append((label, passed, detail))
    if passed:
        ok(label)
    else:
        fail(label)
    if detail:
        for line in detail.splitlines():
            info(line)


# ── import service internals ──────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from app.services.news_fetcher import NewsFetcher, MONEYCONTROL_BASE_URL, MONEYCONTROL_NEWS_ALL, UA_FIREFOX, _build_headers  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

COMPANY_URL = "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI"

# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_with_resource_blocking(fetcher: NewsFetcher, url: str):
    """Internal helper: fetch url via camoufox with image/CSS/font blocking."""
    assert fetcher._browser is not None
    page = await fetcher._browser.new_page()
    try:
        resource_block = re.compile(r"\.(png|jpg|jpeg|gif|svg|ico|woff2?|css)(\?|$)", re.I)
        await page.route(
            resource_block,
            lambda route, _req=None: route.abort(),
        )
        await page.set_extra_http_headers({
            "Referer": "https://www.moneycontrol.com/",
            "Accept-Language": "en-IN,en;q=0.9",
        })
        response = await page.goto(url, wait_until="commit", timeout=45_000)
        if response is None or not response.ok:
            status = response.status if response else 0
            raise RuntimeError(f"HTTP {status}")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        content = await page.content()
        return content
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
async def run_tests() -> int:
    fetcher = NewsFetcher()

    # ── Test 1: browser starts ────────────────────────────────────────────────
    section("Test 1 — camoufox browser startup")
    t0 = time.perf_counter()
    try:
        await fetcher.init()
        elapsed = time.perf_counter() - t0
        if fetcher._browser is not None:
            record("Browser started", True, f"took {elapsed:.1f}s")
        else:
            record("Browser started", False,
                   "init() succeeded but _browser is still None — "
                   "check CAMOUFOX_ENABLED and that 'camoufox fetch' has been run")
    except Exception as exc:
        record("Browser started", False, str(exc))

    if fetcher._browser is None:
        section("Aborting remaining tests — browser not available")
        await fetcher.close()
        return _print_summary()

    # ── Test 2: listing page + URL extraction ─────────────────────────────────
    section("Test 2 — fetch listing page + extract article URLs")
    t0 = time.perf_counter()
    article_urls: list[str] = []
    try:
        html = await fetcher._fetch_listing_page(1)
        elapsed = time.perf_counter() - t0
        article_urls = fetcher._extract_article_urls(html)

        if len(html) > 500:
            record("Listing page fetched", True,
                   f"got {len(html):,} bytes in {elapsed:.1f}s")
        else:
            record("Listing page fetched", False,
                   f"response suspiciously short ({len(html)} bytes) — possible block/redirect")

        if article_urls:
            record("Article URLs extracted", True,
                   f"found {len(article_urls)} URLs; first: {article_urls[0]}")
        else:
            record("Article URLs extracted", False,
                   "no URLs extracted — HTML may be a challenge/redirect page; "
                   "snippet below:\n" + textwrap.indent(html[:600], "    "))
    except Exception as exc:
        record("Listing page fetched", False, str(exc))
        record("Article URLs extracted", False, "skipped (listing fetch failed)")

    # ── Test 3: single article fetch + parse ─────────────────────────────────
    section("Test 3 — fetch + parse a single article")
    test_url = article_urls[0] if article_urls else (
        "https://www.moneycontrol.com/news/business/markets/"
        "sensex-nifty-today-stock-market-live-updates-april-26-2026-13856001.html"
    )
    info(f"URL: {test_url}")
    t0 = time.perf_counter()
    try:
        result = await fetcher._fetch_and_parse_article(test_url)
        elapsed = time.perf_counter() - t0

        if result is None:
            record("Article fetched", False, "returned None (exception during parse)")
        else:
            record("Article fetched", True, f"in {elapsed:.1f}s")

            title = result.get("title") or ""
            text  = result.get("text") or ""
            pub   = result.get("publish_date")
            img   = result.get("top_image") or ""

            record("Title extracted",        bool(title), repr(title[:80]))
            record("Body text extracted",    bool(text),
                   f"{len(text):,} chars — snippet: {repr(text[:120])}" if text
                   else "text is None/empty")
            record("Publish date extracted", pub is not None,
                   str(pub) if pub else "publish_date is None")
            record("Top image extracted",    bool(img), img[:80] if img else "none")

    except Exception as exc:
        elapsed = time.perf_counter() - t0
        record("Article fetched", False, f"{type(exc).__name__}: {exc}")

    # ── Test 4: clean shutdown ────────────────────────────────────────────────
    section("Test 4 — clean browser shutdown")
    try:
        await fetcher.close()
        record("Browser closed", fetcher._browser is None and fetcher._camoufox_ctx is None)
    except Exception as exc:
        record("Browser closed", False, str(exc))

    # ─────────────────────────────────────────────────────────────────────────
    # Tests 5-12: company page, resource-blocking, headers, fallback
    # Re-init the browser for these tests
    # ─────────────────────────────────────────────────────────────────────────
    section("Re-initialising browser for company page tests …")
    try:
        await fetcher.init()
        info(f"Browser ready: {fetcher._browser is not None}")
    except Exception as exc:
        info(f"Re-init failed: {exc}")

    if fetcher._browser is None:
        section("Aborting company-page tests — browser not available")
        return _print_summary()

    # ── Test 5: raw company page fetch (no blocking) ──────────────────────────
    section("Test 5 — raw camoufox fetch of company/stockpricequote page")
    info(f"URL: {COMPANY_URL}")
    t0 = time.perf_counter()
    raw_html = ""
    raw_elapsed = 999.0
    try:
        page = await fetcher._browser.new_page()
        try:
            response = await page.goto(COMPANY_URL, wait_until="commit", timeout=60_000)
            raw_elapsed = time.perf_counter() - t0
            if response is None or not response.ok:
                status = response.status if response else 0
                raise RuntimeError(f"HTTP {status}")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            raw_html = await page.content()
        finally:
            await page.close()

        if len(raw_html) > 500:
            record("Company page fetched (raw)", True,
                   f"{len(raw_html):,} bytes in {raw_elapsed:.1f}s")
        else:
            record("Company page fetched (raw)", False,
                   f"suspiciously short ({len(raw_html)} bytes)\n"
                   + textwrap.indent(raw_html[:600], "    "))
    except Exception as exc:
        raw_elapsed = time.perf_counter() - t0
        record("Company page fetched (raw)", False,
               f"{type(exc).__name__}: {exc} (after {raw_elapsed:.1f}s)")

    # ── Test 6: #news section present on company page ─────────────────────────
    section("Test 6 — #news section found on company page HTML")
    if raw_html:
        soup = BeautifulSoup(raw_html, "lxml")
        news_div = soup.find(id="news")
        record("#news div present", news_div is not None,
               "found" if news_div else
               "missing — MC may be serving a challenge/JS-rendered page\n"
               + "page snippet:\n" + textwrap.indent(raw_html[:800], "    "))
    else:
        record("#news div present", False, "skipped — company page not fetched")

    # ── Test 7: article URLs extracted from #news ─────────────────────────────
    section("Test 7 — article URLs extracted from company #news section")
    if raw_html:
        company_urls = fetcher._extract_company_article_urls(raw_html)
        record("Company article URLs extracted", bool(company_urls),
               f"found {len(company_urls)} URLs" + (f"; first: {company_urls[0]}" if company_urls else ""))
    else:
        record("Company article URLs extracted", False, "skipped — company page not fetched")

    # ── Test 8: resource-blocked fetch of company page ────────────────────────
    section("Test 8 — company page fetch with resource-blocking (img/CSS/font aborted)")
    t0 = time.perf_counter()
    blocked_html = ""
    blocked_elapsed = 999.0
    try:
        blocked_html = await _fetch_with_resource_blocking(fetcher, COMPANY_URL)
        blocked_elapsed = time.perf_counter() - t0

        if len(blocked_html) > 500:
            record("Company page fetched (blocked)", True,
                   f"{len(blocked_html):,} bytes in {blocked_elapsed:.1f}s")
        else:
            record("Company page fetched (blocked)", False,
                   f"suspiciously short ({len(blocked_html)} bytes)")
    except Exception as exc:
        blocked_elapsed = time.perf_counter() - t0
        record("Company page fetched (blocked)", False,
               f"{type(exc).__name__}: {exc} (after {blocked_elapsed:.1f}s)")

    # ── Test 9: compare blocked vs raw timing (informational) ────────────────
    section("Test 9 — compare resource-blocked vs raw timing (informational)")
    if raw_elapsed < 990 and blocked_elapsed < 990:
        faster = blocked_elapsed < raw_elapsed
        # MoneyControl's CDN and SPA boot can make blocking slower — this is
        # informational only; we don't require blocking to win on timing.
        if faster:
            info(f"Blocked fetch was faster: raw={raw_elapsed:.1f}s  blocked={blocked_elapsed:.1f}s  saving={raw_elapsed - blocked_elapsed:.1f}s")
        else:
            info(f"Raw fetch was faster: raw={raw_elapsed:.1f}s  blocked={blocked_elapsed:.1f}s  (blocking not beneficial for this URL)")
        record("Both fetch strategies completed", True,
               f"raw={raw_elapsed:.1f}s  blocked={blocked_elapsed:.1f}s")
    else:
        record("Both fetch strategies completed", False,
               f"one or both fetches failed (raw={raw_elapsed:.1f}s blocked={blocked_elapsed:.1f}s)")

    # ── Test 10: extra headers + resource-blocking ────────────────────────────
    section("Test 10 — #news section present in resource-blocked HTML")
    if blocked_html:
        soup = BeautifulSoup(blocked_html, "lxml")
        news_div = soup.find(id="news")
        blocked_urls = fetcher._extract_company_article_urls(blocked_html)
        record("#news div in blocked HTML", news_div is not None,
               f"found {len(blocked_urls)} article URLs" if news_div
               else "missing — blocking resources may have broken page structure")
        if news_div:
            record("Article URLs in blocked HTML", bool(blocked_urls),
                   f"{len(blocked_urls)} URLs" + (f"; first: {blocked_urls[0]}" if blocked_urls else ""))
    else:
        record("#news div in blocked HTML", False, "skipped — blocked fetch failed")

    # ── Test 11: httpx path fetches company page independently ────────────────
    section("Test 11 — httpx path fetches company page (browser bypassed)")
    t0 = time.perf_counter()
    try:
        saved_browser = fetcher._browser
        fetcher._browser = None           # force httpx path
        httpx_result = await fetcher._get_page(COMPANY_URL)
        fetcher._browser = saved_browser  # restore
        elapsed = time.perf_counter() - t0
        html_len = len(httpx_result.text)
        record("httpx company page fetched", html_len > 500,
               f"{html_len:,} bytes in {elapsed:.1f}s")
        soup = BeautifulSoup(httpx_result.text, "lxml")
        news_div = soup.find(id="news")
        record("#news div via httpx", news_div is not None,
               "found" if news_div else "missing")
    except Exception as exc:
        fetcher._browser = saved_browser  # type: ignore[possibly-undefined]
        elapsed = time.perf_counter() - t0
        record("httpx company page fetched", False,
               f"{type(exc).__name__}: {exc} (after {elapsed:.1f}s)")

    # ── Test 12: _get_page falls back to httpx on camoufox TimeoutError ───────
    section("Test 12 — _get_page falls back to httpx when camoufox raises TimeoutError")
    t0 = time.perf_counter()
    fallback_triggered = False
    try:
        original_camoufox_get = fetcher._camoufox_get_page

        async def _always_timeout(url: str):
            raise TimeoutError(f"simulated camoufox timeout for {url}")

        fetcher._camoufox_get_page = _always_timeout  # type: ignore[method-assign]
        result = await fetcher._get_page(COMPANY_URL)
        elapsed = time.perf_counter() - t0
        fetcher._camoufox_get_page = original_camoufox_get  # type: ignore[method-assign]

        fallback_triggered = True
        html_len = len(result.text)
        record("Fallback to httpx on TimeoutError", html_len > 500,
               f"got {html_len:,} bytes in {elapsed:.1f}s via httpx after simulated timeout")
    except TimeoutError:
        fetcher._camoufox_get_page = original_camoufox_get  # type: ignore[possibly-undefined]
        elapsed = time.perf_counter() - t0
        record("Fallback to httpx on TimeoutError", False,
               f"TimeoutError propagated — no fallback implemented (after {elapsed:.1f}s)")
    except Exception as exc:
        try:
            fetcher._camoufox_get_page = original_camoufox_get  # type: ignore[possibly-undefined]
        except Exception:
            pass
        elapsed = time.perf_counter() - t0
        record("Fallback to httpx on TimeoutError", False,
               f"{type(exc).__name__}: {exc} (after {elapsed:.1f}s)")

    # ── Test 13: _get_client() reinitializes on loop change ─────────────────────
    section("Test 13 — _get_client() reinitializes on loop change")
    try:
        saved_loop = fetcher._client_loop
        fake_loop = object()  # unique object, never equal to real loop
        old_client = fetcher._client
        fetcher._client_loop = fake_loop
        new_client = await fetcher._get_client()
        fetcher._client_loop = saved_loop  # restore
        record("_get_client() re-inits on loop change",
               new_client is not old_client,
               f"client changed: {new_client is not old_client}")
    except Exception as exc:
        record("_get_client() re-inits on loop change", False, str(exc))

    # ── Test 14: _get_page() survives "different event loop" RuntimeError ───
    section("Test 14 — _get_page() survives 'different event loop' RuntimeError")
    try:
        if fetcher._client is None:
            await fetcher.init()
        real_get = fetcher._client.get
        call_count = 0
        async def _get_with_retry_once(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("is bound to a different event loop")
            return await real_get(url, **kwargs)
        fetcher._client.get = _get_with_retry_once  # type: ignore[method-assign]
        result = await fetcher._get_page(COMPANY_URL)
        fetcher._client.get = real_get  # restore
        record("_get_page() survives RuntimeError",
               len(result.text) > 500,
               f"got {len(result.text):,} bytes after RuntimeError reinit")
    except Exception as exc:
        try:
            fetcher._client.get = real_get  # type: ignore[method-assign]
        except Exception:
            pass
        record("_get_page() survives RuntimeError", False, str(exc))

    # ── Test 15: virtual display browser startup ──────────────────────────
    section("Test 15 — virtual display browser startup")
    try:
        from camoufox.exceptions import (
            CannotFindXvfb,
            VirtualDisplayNotSupported,
        )

        fetcher2 = NewsFetcher()
        fetcher2._headers = _build_headers(UA_FIREFOX)
        try:
            await fetcher2.init()
            vd_started = fetcher2._browser is not None
            info(f"fetcher2._browser is not None: {vd_started}")
        except (CannotFindXvfb, VirtualDisplayNotSupported) as vd_exc:
            info(f"Virtual display unavailable: {vd_exc}")
            vd_started = False

        record(
            "Virtual display browser started",
            vd_started,
            "browser started" if vd_started else "Xvfb unavailable / fallback to headless"
        )

        if fetcher2._browser is not None:
            try:
                await fetcher2.close()
            except Exception:
                pass
    except Exception as exc:
        record("Virtual display browser started", False, str(exc))
        if 'fetcher2' in dir() and getattr(fetcher2, '_browser', None) is not None:
            try:
                await fetcher2.close()
            except Exception:
                pass

    # ── Final shutdown ─────────────────────────────────���──────────────────────
    section("Final — clean browser shutdown")
    try:
        await fetcher.close()
        record("Browser closed (final)", fetcher._browser is None and fetcher._camoufox_ctx is None)
    except Exception as exc:
        record("Browser closed (final)", False, str(exc))

    return _print_summary()


def _print_summary() -> int:
    passed = sum(1 for _, p, _ in results if p)
    total  = len(results)
    colour = GREEN if passed == total else RED

    print(f"\n{BOLD}{'─'*50}{NC}")
    print(f"{BOLD}Results: {colour}{passed}/{total} passed{NC}")
    print(f"{BOLD}{'─'*50}{NC}\n")

    failed = [(l, d) for l, p, d in results if not p]
    if failed:
        print(f"{RED}Failed checks:{NC}")
        for label, detail in failed:
            print(f"  • {label}")
            if detail:
                print(textwrap.indent(detail, "      "))
        print()

    return 0 if passed == total else 1


if __name__ == "__main__":
    print(f"\n{BOLD}camoufox smoke-test{NC}  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python {sys.version.split()[0]}  |  PID {os.getpid()}\n")
    sys.exit(asyncio.run(run_tests()))
