"""Market data fetcher service for MoneyControl industry and sector data."""

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketcategory import MarketCategory, MarketCategoryStock

logger = logging.getLogger(__name__)

MONEYCONTROL_BASE_URL = "https://www.moneycontrol.com"
MONEYCONTROL_INDUSTRY_LISTING = f"{MONEYCONTROL_BASE_URL}/markets/industry-analysis/"
MONEYCONTROL_SECTOR_LISTING = f"{MONEYCONTROL_BASE_URL}/markets/sector-analysis/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

CONCURRENCY_LIMIT = 3
REQUEST_DELAY = 1.0


def _build_headers(ua: str | None = None) -> dict:
    """Build request headers with realistic browser headers."""
    user_agent = ua or random.choice(USER_AGENTS)
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Referer": "https://www.moneycontrol.com/",
        "Origin": "https://www.moneycontrol.com",
    }


class MarketDataFetcher:
    """Service to fetch and parse industry/sector data from MoneyControl."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        self._client: httpx.AsyncClient | None = None
        self._headers = _build_headers()
        self._cookies_loaded = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )
            await self._load_fresh_cookies()
        return self._client

    async def _load_fresh_cookies(self) -> bool:
        """Load browser cookies from pickle (pre-extracted) if available."""
        if self._cookies_loaded:
            return True

        from app.services.cookie_loader import load_cookies_from_pickle

        pickle_cookies = await asyncio.to_thread(load_cookies_from_pickle, "moneycontrol")
        if pickle_cookies:
            client = await self._get_client()
            for c in pickle_cookies:
                raw_domain = c.get("domain")
                domain_str: str = str(raw_domain) if raw_domain is not None else ""
                name_str: str = str(c.get("name")) if c.get("name") else ""
                value_str: str = str(c.get("value")) if c.get("value") else ""
                client.cookies.set(
                    name_str, value_str, domain=domain_str if domain_str else ""
                )
            self._cookies_loaded = True
            logger.info("_load_fresh_cookies: loaded %d cookies from pickle", len(pickle_cookies))
            return True

        return False

    async def _refresh_cookies(self) -> bool:
        """Force-refresh cookies from Firefox profile (e.g. after a 403)."""
        self._cookies_loaded = False
        return await self._load_fresh_cookies()

    async def _get_page(self, url: str) -> httpx.Response:
        """Fetch a page with 403-handling: refresh cookies and retry once."""
        client = await self._get_client()
        response = await client.get(url)
        if response.status_code == 403:
            logger.warning("Got 403 on %s — refreshing cookies and retrying", url)
            refreshed = await self._refresh_cookies()
            if refreshed:
                await asyncio.sleep(2)
                response = await client.get(url)
        response.raise_for_status()
        return response

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _extract_category_cards(
        self, html: str, category_type: str
    ) -> list[dict[str, Any]]:
        """Extract category card data from listing page HTML."""
        soup = BeautifulSoup(html, "lxml")
        cards = []

        # Find all category cards - they are <a> tags with CardWeb_grayBoxStrip__ class
        card_elements = soup.find_all("a", class_=re.compile(r"CardWeb_grayBoxStrip__"))

        for card in card_elements:
            try:
                # Extract name
                name_elem = card.find(
                    "span", class_=re.compile(r"CardWeb_sectors_name__")
                )
                if not name_elem:
                    continue
                name = name_elem.get_text(strip=True)

                # Extract slug from href
                href = card.get("href", "")
                if not href:
                    continue

                # URL pattern: https://www.moneycontrol.com/markets/industry-analysis/bank-private/
                # or: https://www.moneycontrol.com/markets/sector-analysis/banks/
                path_match = re.search(
                    rf"/markets/{category_type}-analysis/([^/]+)/?", href
                )
                if not path_match:
                    continue
                slug = path_match.group(1)
                if slug == "undefined":
                    continue

                # Extract metrics from the card
                market_cap = None
                pe = None
                advance = None
                decline = None
                sentiment = None
                earnings_yoy = None

                # Get all text from the card first to do simple pattern matching
                card_text = card.get_text()

                # Look for market cap pattern - "M. Cap (Rs. Cr.)" followed by a number
                mcap_match = re.search(
                    r"M\.\s*Cap\s*\(Rs\.\s*Cr\.\)[\s\S]{0,50}?([\d,]+)", card_text
                )
                if mcap_match:
                    try:
                        market_cap = float(mcap_match.group(1).replace(",", ""))
                    except ValueError:
                        pass

                # Look for PE pattern
                pe_match = re.search(
                    r"(?:industry|sector)\s*PE[\s\S]{0,30}?([\d.]+)", card_text
                )
                if pe_match:
                    try:
                        pe = float(pe_match.group(1))
                    except ValueError:
                        pass

                # Look for Earnings YOY pattern - more flexible
                # The format could be "Earnings YOY 54,765 (4.55%)" or similar
                earnings_match = re.search(
                    r"Earnings\s*YOY[\s\S]{0,100}?([\d.-]+)\s*%?", card_text
                )
                if not earnings_match:
                    # Try alternate: percentage might be in parentheses after the number
                    earnings_match = re.search(
                        r"Earnings\s*YOY[\s\S]{0,100}?\(([+-]?[\d.]+)\s*%\)", card_text
                    )
                if earnings_match:
                    try:
                        earnings_yoy = float(earnings_match.group(1).replace(",", ""))
                    except ValueError:
                        pass

                # Look for Adv/Decline pattern - e.g., "Adv/Decline 2 - 26" or "Adv/Decline 2-26"
                adv_decl_match = re.search(
                    r"Adv/Decline\s*(\d+)\s*[-–]\s*(\d+)", card_text
                )
                if adv_decl_match:
                    try:
                        advance = int(adv_decl_match.group(1))
                        decline = int(adv_decl_match.group(2))
                    except ValueError:
                        pass

                # Also try alternate pattern: the value could be after the label
                if advance is None:
                    # Try to find advance by looking for the div with class
                    adv_div = card.find(
                        "div", class_=re.compile(r"CardWeb_advDecline_value__")
                    )
                    if adv_div:
                        adv_text = adv_div.get_text(strip=True)
                        if adv_text and adv_text.lstrip("-").isdigit():
                            advance = int(adv_text)
                    else:
                        # Try finding span with this class
                        adv_span = card.find(
                            "span", class_=re.compile(r"CardWeb_advDecline_value__")
                        )
                        if adv_span:
                            adv_text = adv_span.get_text(strip=True)
                            if adv_text and adv_text.lstrip("-").isdigit():
                                advance = int(adv_text)

                    # Find decline - sibling or nearby span with minus class
                    decl_span = card.find(
                        "span", class_=re.compile(r"CardWeb_advDecline_minus__")
                    )
                    if decl_span:
                        decl_text = decl_span.get_text(strip=True)
                        if decl_text and decl_text.lstrip("-").isdigit():
                            decline = int(decl_text)

                # Extract sentiment - look for Bearish/Bullish in the card
                sentiment = None
                if "Very Bearish" in card_text:
                    sentiment = "Very Bearish"
                elif "Bearish" in card_text:
                    sentiment = "Bearish"
                elif "Very Bullish" in card_text:
                    sentiment = "Very Bullish"
                elif "Bullish" in card_text:
                    sentiment = "Bullish"
                elif "Neutral" in card_text:
                    sentiment = "Neutral"

                cards.append(
                    {
                        "slug": slug,
                        "name": name,
                        "url": href,
                        "market_cap": market_cap,
                        "pe": pe,
                        "advance": advance,
                        "decline": decline,
                        "sentiment": sentiment,
                        "earnings_yoy": earnings_yoy,
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to parse category card: {e}")
                continue

        return cards

    def _extract_next_data(self, html: str) -> dict[str, Any] | None:
        """Extract __NEXT_DATA__ JSON from page HTML."""
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            logger.warning("No __NEXT_DATA__ found in HTML")
            return None
        try:
            return json.loads(script.string)
        except Exception as e:
            logger.warning(f"Failed to parse __NEXT_DATA__: {e}")
            return None

    def _parse_stocks_from_next_data(
        self, next_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Parse stock list from __NEXT_DATA__ JSON."""
        stocks = []
        try:
            # Navigate to the props -> pageProps -> data structure
            props = next_data.get("props", {})
            page_props = props.get("pageProps", {})
            data = page_props.get("data", {})

            # Find the allStocks array
            all_stocks = data.get("allStocks", [])
            if not all_stocks:
                # Try alternative paths
                all_stocks = data.get("stocks", [])

            for stock in all_stocks:
                try:
                    # Extract stock data - fields vary, use safe access
                    stock_name = stock.get("stockName", "")
                    sc_id = stock.get("scId", "")

                    # Skip empty entries
                    if not stock_name:
                        continue

                    # Parse price - remove commas and handle empty
                    curr_price_str = stock.get("currPrice", "")
                    curr_price = None
                    if curr_price_str:
                        try:
                            curr_price = float(curr_price_str.replace(",", ""))
                        except (ValueError, TypeError):
                            pass

                    # Parse percentage change
                    per_change_str = stock.get("perChange", "")
                    per_change = None
                    if per_change_str:
                        try:
                            per_change = float(per_change_str.replace(",", ""))
                        except (ValueError, TypeError):
                            pass

                    # Parse market cap
                    market_cap_str = stock.get("marketCap", "")
                    market_cap = None
                    if market_cap_str:
                        try:
                            market_cap = float(market_cap_str.replace(",", ""))
                        except (ValueError, TypeError):
                            pass

                    # Parse PE
                    ttm_pe = stock.get("ttmPe")
                    if ttm_pe is not None:
                        try:
                            ttm_pe = float(ttm_pe)
                        except (ValueError, TypeError):
                            ttm_pe = None

                    # Parse net profit
                    net_profit_str = stock.get("netProfit", "")
                    net_profit = None
                    if net_profit_str:
                        try:
                            net_profit = float(net_profit_str.replace(",", ""))
                        except (ValueError, TypeError):
                            pass

                    # Parse net profit YOY
                    net_profit_yoy_str = stock.get("netProfitYoy", "")
                    net_profit_yoy = None
                    if net_profit_yoy_str:
                        try:
                            net_profit_yoy = float(
                                net_profit_yoy_str.replace(",", "").replace("%", "")
                            )
                        except (ValueError, TypeError):
                            pass

                    # Tech trend
                    tech_trend = stock.get("techTrend", "")

                    # Exchange
                    exchange_raw = stock.get("ex", "N")
                    exchange = "NSE" if exchange_raw == "N" else "BSE"

                    # Slug for URL
                    slug = stock.get("slug", "")
                    mc_url = None
                    if slug:
                        mc_url = f"{MONEYCONTROL_BASE_URL}/india/stockpricequote/{slug}"

                    # Extract symbol from scId - it's usually the last part
                    # e.g., "HDF01" -> "HDFCBANK" (need to look up)
                    # For now, use scId as identifier
                    symbol = sc_id

                    stocks.append(
                        {
                            "symbol": symbol,
                            "company_name": stock_name,
                            "exchange": exchange,
                            "curr_price": curr_price,
                            "per_change": per_change,
                            "market_cap": market_cap,
                            "ttm_pe": ttm_pe,
                            "net_profit": net_profit,
                            "net_profit_yoy": net_profit_yoy,
                            "tech_trend": tech_trend if tech_trend else None,
                            "mc_url": mc_url,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to parse stock: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Failed to parse stocks from __NEXT_DATA__: {e}")
        return stocks

    async def fetch_industry_list(self) -> list[dict[str, Any]]:
        """Fetch the list of all industries from MoneyControl."""
        logger.info("Fetching industry list from MoneyControl")
        try:
            response = await self._get_page(MONEYCONTROL_INDUSTRY_LISTING)
            cards = self._extract_category_cards(response.text, "industry")
            logger.info(f"Found {len(cards)} industries")
            return cards
        except Exception:
            logger.exception("Failed to fetch industry list")
            return []

    async def fetch_sector_list(self) -> list[dict[str, Any]]:
        """Fetch the list of all sectors from MoneyControl."""
        logger.info("Fetching sector list from MoneyControl")
        try:
            response = await self._get_page(MONEYCONTROL_SECTOR_LISTING)
            cards = self._extract_category_cards(response.text, "sector")
            logger.info(f"Found {len(cards)} sectors")
            return cards
        except Exception:
            logger.exception("Failed to fetch sector list")
            return []

    async def fetch_industry_detail(self, slug: str) -> list[dict[str, Any]]:
        """Fetch stocks in a specific industry."""
        url = f"{MONEYCONTROL_INDUSTRY_LISTING}{slug}/"
        logger.info(f"Fetching industry detail: {slug}")
        try:
            response = await self._get_page(url)
            next_data = self._extract_next_data(response.text)
            if next_data:
                stocks = self._parse_stocks_from_next_data(next_data)
                # Add category info to each stock
                for stock in stocks:
                    stock["_category"] = {"type": "industry", "slug": slug}
                logger.info(f"Found {len(stocks)} stocks in industry {slug}")
                return stocks
            return []
        except Exception:
            logger.exception(f"Failed to fetch industry detail: {slug}")
            return []

    async def fetch_sector_detail(self, slug: str) -> list[dict[str, Any]]:
        """Fetch stocks in a specific sector."""
        url = f"{MONEYCONTROL_SECTOR_LISTING}{slug}/"
        logger.info(f"Fetching sector detail: {slug}")
        try:
            response = await self._get_page(url)
            next_data = self._extract_next_data(response.text)
            if next_data:
                stocks = self._parse_stocks_from_next_data(next_data)
                # Add category info to each stock
                for stock in stocks:
                    stock["_category"] = {"type": "sector", "slug": slug}
                logger.info(f"Found {len(stocks)} stocks in sector {slug}")
                return stocks
            return []
        except Exception:
            logger.exception(f"Failed to fetch sector detail: {slug}")
            return []

    async def _bulk_upsert_categories(
        self, db: AsyncSession, category_rows: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Batch upsert all market categories in a single round-trip.

        Each row is (category_type, data_dict).
        """
        if not category_rows:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        values_list = []
        for category_type, data in category_rows:
            values_list.append({
                "category_type": category_type,
                "slug": data["slug"],
                "name": data["name"],
                "url": data.get("url"),
                "market_cap": data.get("market_cap"),
                "pe": data.get("pe"),
                "advance": data.get("advance"),
                "decline": data.get("decline"),
                "sentiment": data.get("sentiment"),
                "earnings_yoy": data.get("earnings_yoy"),
                "last_updated": now,
            })

        insert_stmt = sqlite_insert(MarketCategory).values(values_list)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["category_type", "slug"],
            set_={
                "name": insert_stmt.excluded.name,
                "url": insert_stmt.excluded.url,
                "market_cap": insert_stmt.excluded.market_cap,
                "pe": insert_stmt.excluded.pe,
                "advance": insert_stmt.excluded.advance,
                "decline": insert_stmt.excluded.decline,
                "sentiment": insert_stmt.excluded.sentiment,
                "earnings_yoy": insert_stmt.excluded.earnings_yoy,
                "last_updated": insert_stmt.excluded.last_updated,
            },
        )
        await db.execute(stmt)

    async def _bulk_upsert_stocks(
        self, db: AsyncSession, stock_rows: list[dict[str, Any]]
    ) -> None:
        """Batch upsert all stocks in batches of 500 for efficiency.

        Each row must contain all MarketCategoryStock fields plus ``categories``.
        """
        if not stock_rows:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        BATCH_SIZE = 500

        for chunk_start in range(0, len(stock_rows), BATCH_SIZE):
            chunk = stock_rows[chunk_start:chunk_start + BATCH_SIZE]
            values_list = []
            for row in chunk:
                values_list.append({
                    "symbol": row["symbol"],
                    "company_name": row["company_name"],
                    "exchange": row.get("exchange"),
                    "curr_price": row.get("curr_price"),
                    "per_change": row.get("per_change"),
                    "market_cap": row.get("market_cap"),
                    "ttm_pe": row.get("ttm_pe"),
                    "net_profit": row.get("net_profit"),
                    "net_profit_yoy": row.get("net_profit_yoy"),
                    "tech_trend": row.get("tech_trend"),
                    "mc_url": row.get("mc_url"),
                    "categories": row.get("categories", []),
                    "last_updated": now,
                })

            insert_stmt2 = sqlite_insert(MarketCategoryStock).values(values_list)
            stmt = insert_stmt2.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "company_name": insert_stmt2.excluded.company_name,
                    "exchange": insert_stmt2.excluded.exchange,
                    "curr_price": insert_stmt2.excluded.curr_price,
                    "per_change": insert_stmt2.excluded.per_change,
                    "market_cap": insert_stmt2.excluded.market_cap,
                    "ttm_pe": insert_stmt2.excluded.ttm_pe,
                    "net_profit": insert_stmt2.excluded.net_profit,
                    "net_profit_yoy": insert_stmt2.excluded.net_profit_yoy,
                    "tech_trend": insert_stmt2.excluded.tech_trend,
                    "mc_url": insert_stmt2.excluded.mc_url,
                    "categories": insert_stmt2.excluded.categories,
                    "last_updated": insert_stmt2.excluded.last_updated,
                },
            )
            await db.execute(stmt)

            # Brief pause between batches to let other DB operations through
            if len(stock_rows) > BATCH_SIZE:
                await asyncio.sleep(0.1)

    async def refresh_all(self, db: AsyncSession) -> tuple[int, int]:
        """Fetch and store all industry and sector data.

        Collects all data in-memory first, then performs batch DB writes
        to minimise round-trips and avoid overwhelming SQLite.

        Returns (categories_count, stocks_count).
        """
        logger.info("Starting market data refresh")
        total_categories = 0
        total_stocks = 0

        # ── Phase 1: Fetch all data (sequential with delay for rate-limiting) ──
        industries = await self.fetch_industry_list()

        industry_stock_pairs: list[tuple[dict, list[dict]]] = []
        for ind in industries:
            stocks = await self.fetch_industry_detail(ind["slug"])
            industry_stock_pairs.append((ind, stocks))
            total_categories += 1
            total_stocks += len(stocks)
            await asyncio.sleep(REQUEST_DELAY)

        sectors = await self.fetch_sector_list()

        sector_stock_pairs: list[tuple[dict, list[dict]]] = []
        for sec in sectors:
            stocks = await self.fetch_sector_detail(sec["slug"])
            sector_stock_pairs.append((sec, stocks))
            total_categories += 1
            total_stocks += len(stocks)
            await asyncio.sleep(REQUEST_DELAY)

        # ── Phase 2: Build in-memory maps ──

        # 2a: Category rows (flat list of (type, data) tuples)
        category_rows: list[tuple[str, dict[str, Any]]] = []
        for ind in industries:
            category_rows.append(("industry", ind))
        for sec in sectors:
            category_rows.append(("sector", sec))

        # 2b: Stock rows grouped by symbol, with merged categories
        # Load existing categories from DB for merge
        existing_categories_map: dict[str, list[dict]] = {}
        try:
            existing_stmt = select(MarketCategoryStock.symbol, MarketCategoryStock.categories)
            existing_result = await db.execute(existing_stmt)
            for row in existing_result:
                existing_categories_map[row[0]] = list(row[1] or [])
        except Exception:
            logger.warning("Failed to load existing stock categories, starting fresh")

        stock_map: dict[str, dict[str, Any]] = {}

        def _ensure_stock(sym: str, stock_data: dict) -> dict:
            """Get or create stock entry in stock_map, copying fields from stock_data."""
            if sym not in stock_map:
                entry = {
                    "symbol": sym,
                    "company_name": stock_data["company_name"],
                    "exchange": stock_data.get("exchange"),
                    "curr_price": stock_data.get("curr_price"),
                    "per_change": stock_data.get("per_change"),
                    "market_cap": stock_data.get("market_cap"),
                    "ttm_pe": stock_data.get("ttm_pe"),
                    "net_profit": stock_data.get("net_profit"),
                    "net_profit_yoy": stock_data.get("net_profit_yoy"),
                    "tech_trend": stock_data.get("tech_trend"),
                    "mc_url": stock_data.get("mc_url"),
                    "categories": existing_categories_map.get(sym, []),
                }
                stock_map[sym] = entry
            return stock_map[sym]

        for ind, stocks in industry_stock_pairs:
            for s in stocks:
                entry = _ensure_stock(s["symbol"], s)
                cat_entry = {"type": "industry", "slug": ind["slug"]}
                if cat_entry not in entry["categories"]:
                    entry["categories"].append(cat_entry)

        for sec, stocks in sector_stock_pairs:
            for s in stocks:
                entry = _ensure_stock(s["symbol"], s)
                cat_entry = {"type": "sector", "slug": sec["slug"]}
                if cat_entry not in entry["categories"]:
                    entry["categories"].append(cat_entry)

        # ── Phase 3: Batch DB writes ──
        await self._bulk_upsert_categories(db, category_rows)
        await self._bulk_upsert_stocks(db, list(stock_map.values()))

        await db.commit()
        logger.info(
            f"Market data refresh complete: {len(category_rows)} categories, "
            f"{len(stock_map)} unique stocks (merging all category associations)"
        )
        return len(category_rows), len(stock_map)

    # ── Legacy individual helpers (kept for backward compat) ──────────────

    async def store_category(
        self, db: AsyncSession, category_type: str, data: dict[str, Any]
    ) -> None:
        """Store or update a single market category.

        Prefer ``_bulk_upsert_categories`` for bulk operations.
        """
        await self._bulk_upsert_categories(db, [(category_type, data)])

    async def store_stock(
        self, db: AsyncSession, stock_data: dict[str, Any], category: dict[str, str]
    ) -> None:
        """Store or update a single stock, merging categories.

        Prefer ``_bulk_upsert_stocks`` for bulk operations.
        """
        # Load existing categories if not already in stock_data
        if "categories" not in stock_data:
            try:
                stmt = select(MarketCategoryStock).where(
                    MarketCategoryStock.symbol == stock_data["symbol"]
                )
                result = await db.execute(stmt)
                existing = result.scalar_one_or_none()
                existing_cats = list(existing.categories or []) if existing else []
            except Exception:
                existing_cats = []
            cat_entry = {"type": category["type"], "slug": category["slug"]}
            if cat_entry not in existing_cats:
                existing_cats.append(cat_entry)
            stock_data["categories"] = existing_cats

        await self._bulk_upsert_stocks(db, [stock_data])


market_data_fetcher = MarketDataFetcher()
