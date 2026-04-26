#!/usr/bin/env python3
"""
test_camoufox.py — manual smoke-test for the camoufox news fetching path.

Run from inside the backend venv with CAMOUFOX_ENABLED=true:

    cd backend
    source .venv/bin/activate
    CAMOUFOX_ENABLED=true python test_camoufox.py

The script runs four checks in sequence and prints a pass/fail summary:
  1. camoufox browser starts
  2. Listing page fetched + article URLs extracted
  3. Single article fetched + content parsed (title, date, text)
  4. camoufox browser closes cleanly
"""

import asyncio
import os
import sys
import time
import textwrap
from datetime import datetime

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
# Add the backend root to sys.path so app.* imports resolve.
sys.path.insert(0, os.path.dirname(__file__))

from app.services.news_fetcher import NewsFetcher, MONEYCONTROL_NEWS_ALL  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


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
