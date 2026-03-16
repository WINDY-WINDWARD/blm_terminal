"""Service for linking MoneyControl stock data with stockuniverse."""

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketcategory import MarketCategoryStock
from app.models.stockuniverse import StockUniverse


@dataclass
class MatchResult:
    symbol: str
    mc_symbol: str
    mc_company_name: str
    mc_url: str
    review_status: str
    match_confidence: float
    mc_match_source: str


def normalize_company_name(name: str) -> str:
    """Normalize company name for fuzzy matching."""
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name)
    suffixes_to_remove = [
        "limited",
        "ltd",
        " ltd",
        "private limited",
        " pvt ltd",
        " pvt.",
        "india",
        "(india)",
        "(india) limited",
        "the",
        "&",
    ]
    for suffix in suffixes_to_remove:
        name = name.replace(suffix, "")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_symbol_from_url(url: str) -> Optional[str]:
    """Extract stock symbol from MoneyControl URL."""
    if not url:
        return None
    match = re.search(r"/([a-z0-9]+)/([a-z0-9]+)$", url, re.IGNORECASE)
    if match:
        return match.group(2).upper()
    return None


class MCStockLinker:
    """Service to match MoneyControl stocks with stockuniverse."""

    FUZZY_THRESHOLD = 70
    HIGH_CONFIDENCE_THRESHOLD = 90

    def __init__(self, session: AsyncSession):
        self.session = session

    async def run_matching(self) -> dict:
        """Run the complete matching algorithm across all tiers."""
        result = await self._run_tier_1_exact_match()
        result += await self._run_tier_2_url_extract()
        result += await self._run_tier_3_fuzzy_match()
        return {
            "total_matched": len(result),
            "exact_matches": sum(1 for r in result if r.review_status == "exact"),
            "url_extract_matches": sum(1 for r in result if r.review_status == "url_extract"),
            "fuzzy_matches": sum(1 for r in result if r.review_status == "fuzzy"),
            "ambiguous_matches": sum(1 for r in result if r.review_status == "ambiguous"),
        }

    async def _run_tier_1_exact_match(self) -> list[MatchResult]:
        """Tier 1: Exact symbol match."""
        result = []
        stmt = select(MarketCategoryStock).where(
            MarketCategoryStock.symbol.isnot(None)
        )
        result_mcs = await self.session.execute(stmt)
        mcs_dict = {row.symbol: row for row in result_mcs.scalars().all()}

        stmt = select(StockUniverse)
        result_su = await self.session.execute(stmt)
        su_records = result_su.scalars().all()

        for su in su_records:
            if su.symbol in mcs_dict:
                mcs = mcs_dict[su.symbol]
                su.review_status = "exact"
                su.match_confidence = 1.0
                su.mc_match_source = "symbol"
                su.mc_url = mcs.mc_url
                su.mc_company_name = mcs.company_name
                result.append(
                    MatchResult(
                        symbol=su.symbol,
                        mc_symbol=mcs.symbol,
                        mc_company_name=mcs.company_name,
                        mc_url=mcs.mc_url,
                        review_status="exact",
                        match_confidence=1.0,
                        mc_match_source="symbol",
                    )
                )

        await self.session.flush()
        await self.session.flush()
        await self.session.commit()
        return result

    async def _run_tier_2_url_extract(self) -> list[MatchResult]:
        """Tier 2: Extract symbol from mc_url and match."""
        result = []
        stmt = select(MarketCategoryStock).where(
            MarketCategoryStock.mc_url.isnot(None),
            MarketCategoryStock.mc_url != "",
        )
        result_mcs = await self.session.execute(stmt)
        mcs_list = list(result_mcs.scalars().all())

        mc_by_extracted = {}
        for mcs in mcs_list:
            extracted = extract_symbol_from_url(mcs.mc_url)
            if extracted:
                mc_by_extracted[extracted] = mcs

        stmt = select(StockUniverse).where(
            StockUniverse.review_status.is_(None),
            StockUniverse.symbol.in_(mc_by_extracted.keys()),
        )
        result_su = await self.session.execute(stmt)
        su_records = result_su.scalars().all()

        for su in su_records:
            if su.symbol in mc_by_extracted:
                mcs = mc_by_extracted[su.symbol]
                su.review_status = "url_extract"
                su.match_confidence = 0.95
                su.mc_match_source = "url"
                su.mc_url = mcs.mc_url
                su.mc_company_name = mcs.company_name
                result.append(
                    MatchResult(
                        symbol=su.symbol,
                        mc_symbol=mcs.symbol,
                        mc_company_name=mcs.company_name,
                        mc_url=mcs.mc_url,
                        review_status="url_extract",
                        match_confidence=0.95,
                        mc_match_source="url",
                    )
                )

        await self.session.commit()
        return result

    async def _run_tier_3_fuzzy_match(self) -> list[MatchResult]:
        """Tier 3: Fuzzy company name matching."""
        result = []

        stmt = select(MarketCategoryStock).where(
            MarketCategoryStock.company_name.isnot(None)
        )
        result_mcs = await self.session.execute(stmt)
        mcs_list = list(result_mcs.scalars().all())

        stmt = select(StockUniverse).where(
            StockUniverse.review_status.is_(None),
            StockUniverse.company_name.isnot(None),
        )
        result_su = await self.session.execute(stmt)
        su_records = list(result_su.scalars().all())

        for su in su_records:
            su_normalized = normalize_company_name(su.company_name)
            if not su_normalized:
                continue

            best_match: Optional[MatchResult] = None
            best_score = 0

            for mcs in mcs_list:
                mc_normalized = normalize_company_name(mcs.company_name)
                if not mc_normalized:
                    continue

                score = fuzz.ratio(su_normalized, mc_normalized)

                if score > best_score:
                    best_score = score
                    best_match = MatchResult(
                        symbol=su.symbol,
                        mc_symbol=mcs.symbol,
                        mc_company_name=mcs.company_name,
                        mc_url=mcs.mc_url or "",
                        review_status="pending",
                        match_confidence=score / 100.0,
                        mc_match_source="name",
                    )

            if best_match and best_score >= self.FUZZY_THRESHOLD:
                if best_score >= self.HIGH_CONFIDENCE_THRESHOLD:
                    su.review_status = "fuzzy"
                    best_match.review_status = "fuzzy"
                else:
                    su.review_status = "ambiguous"
                    best_match.review_status = "ambiguous"

                su.match_confidence = best_score / 100.0
                su.mc_match_source = "name"
                su.mc_url = best_match.mc_url
                su.mc_company_name = best_match.mc_company_name
                result.append(best_match)

        await self.session.flush()
        await self.session.commit()
        return result

    async def get_pending_review(self, limit: int = 50) -> list[StockUniverse]:
        """Get stocks that need manual review (ambiguous matches)."""
        stmt = (
            select(StockUniverse)
            .where(StockUniverse.review_status == "ambiguous")
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def confirm_match(
        self, symbol: str, confirmed: bool, mc_url: Optional[str] = None
    ) -> bool:
        """Confirm or reject an ambiguous match."""
        stmt = select(StockUniverse).where(StockUniverse.symbol == symbol)
        result = await self.session.execute(stmt)
        su = result.scalar_one_or_none()

        if not su:
            return False

        if confirmed:
            su.review_status = "confirmed"
            if mc_url:
                su.mc_url = mc_url
        else:
            su.review_status = "rejected"
            su.mc_url = None
            su.mc_company_name = None
            su.mc_match_source = None
            su.match_confidence = None

        await self.session.commit()
        return True
