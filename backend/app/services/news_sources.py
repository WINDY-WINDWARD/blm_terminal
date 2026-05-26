"""Central definitions for RSS news feed sources.

This module contains all configured news sources organized by tier and category.
Each source has an ID, name, URL, category, and tier (1 = most trusted).
"""

from dataclasses import dataclass
from enum import Enum


class SourceCategory(str, Enum):
    """News categories."""
    MARKETS = "MARKETS"
    GEOPOLITICS = "GEOPOLITICS"
    CRYPTO = "CRYPTO"
    TECH = "TECH"
    REGULATORY = "REGULATORY"
    ECONOMIC = "ECONOMIC"


class SourceTier(int, Enum):
    """Source reliability tier."""
    TIER_1 = 1  # Wire services, regulators, major financial
    TIER_2 = 2  # Standard news sources
    TIER_3 = 3  # Blogs, aggregators


@dataclass(frozen=True)
class NewsSource:
    """A single RSS news source."""
    id: str
    name: str
    url: str
    category: SourceCategory
    tier: SourceTier
    description: str = ""


# Tier 1: Wire Services & Regulators
TIER1_WIRE_REGULATORY = [
    NewsSource(
        id="ap-top",
        name="AP Top News",
        url="https://rsshub.app/apnews/topics/ap-top-news",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_1,
        description="Associated Press top news",
    ),
    NewsSource(
        id="sec-press",
        name="SEC Press Releases",
        url="https://www.sec.gov/news/pressreleases.rss",
        category=SourceCategory.REGULATORY,
        tier=SourceTier.TIER_1,
        description="SEC official press releases",
    ),
    NewsSource(
        id="fed-press",
        name="Federal Reserve",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        category=SourceCategory.REGULATORY,
        tier=SourceTier.TIER_1,
        description="Federal Reserve press releases",
    ),
    NewsSource(
        id="ecb-press",
        name="ECB Press",
        url="https://www.ecb.europa.eu/rss/press.html",
        category=SourceCategory.REGULATORY,
        tier=SourceTier.TIER_1,
        description="European Central Bank press releases",
    ),
    NewsSource(
        id="boe-news",
        name="Bank of England",
        url="https://www.bankofengland.co.uk/rss/news",
        category=SourceCategory.REGULATORY,
        tier=SourceTier.TIER_1,
        description="Bank of England news",
    ),
]

# Tier 1: Major Financial Media
TIER1_FINANCIAL = [
    NewsSource(
        id="bloomberg-mkts",
        name="Bloomberg Markets",
        url="https://feeds.bloomberg.com/markets/news.rss",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_1,
        description="Bloomberg Markets news",
    ),
    NewsSource(
        id="wsj-markets",
        name="WSJ Markets",
        url="https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_1,
        description="Wall Street Journal Markets",
    ),
    NewsSource(
        id="cnbc-finance",
        name="CNBC Finance",
        url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_1,
        description="CNBC Finance",
    ),
]

# Tier 2: India
TIER2_INDIA = [
    NewsSource(
        id="moneycontrol",
        name="MoneyControl",
        url="https://www.moneycontrol.com/rss/latestnews.xml",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="MoneyControl India news",
    ),
    NewsSource(
        id="et-markets",
        name="Economic Times",
        url="https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="Economic Times Markets",
    ),
    NewsSource(
        id="livemint",
        name="LiveMint",
        url="https://www.livemint.com/rss/markets",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="LiveMint Markets",
    ),
    NewsSource(
        id="hindu-biz",
        name="The Hindu Business",
        url="https://www.thehindu.com/business/feeder/default.rss",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="The Hindu Business Line",
    ),
]

# Tier 2: Global Markets
TIER2_GLOBAL = [
    NewsSource(
        id="marketwatch",
        name="MarketWatch",
        url="https://feeds.marketwatch.com/marketwatch/topstories/",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="MarketWatch top stories",
    ),
    NewsSource(
        id="seekingalpha",
        name="Seeking Alpha",
        url="https://seekingalpha.com/market_currents.xml",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="Seeking Alpha Market Currents",
    ),
    NewsSource(
        id="investing-news",
        name="Investing.com",
        url="https://www.investing.com/rss/news.rss",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="Investing.com news feed",
    ),
    NewsSource(
        id="benzinga",
        name="Benzinga",
        url="https://www.benzinga.com/feed",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="Benzinga markets news",
    ),
    NewsSource(
        id="bbc-business",
        name="BBC Business",
        url="http://feeds.bbci.co.uk/news/business/rss.xml",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="BBC Business",
    ),
    NewsSource(
        id="nikkei-asia",
        name="Nikkei Asia",
        url="https://asia.nikkei.com/rss/feed/nar",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="Nikkei Asia",
    ),
    NewsSource(
        id="cna",
        name="Channel News Asia",
        url="https://www.channelnewsasia.com/rssfeeds/8395986",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_2,
        description="Channel News Asia",
    ),
    NewsSource(
        id="economist",
        name="The Economist",
        url="https://www.economist.com/finance-and-economics/rss.xml",
        category=SourceCategory.ECONOMIC,
        tier=SourceTier.TIER_2,
        description="The Economist Finance & Economics",
    ),
    NewsSource(
        id="aljazeera",
        name="Al Jazeera",
        url="https://www.aljazeera.com/xml/rss/all.xml",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_2,
        description="Al Jazeera World",
    ),
    NewsSource(
        id="foreignpolicy",
        name="Foreign Policy",
        url="https://foreignpolicy.com/feed/",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_2,
        description="Foreign Policy",
    ),
]

# Tier 2: Crypto
TIER2_CRYPTO = [
    NewsSource(
        id="coindesk",
        name="CoinDesk",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        category=SourceCategory.CRYPTO,
        tier=SourceTier.TIER_2,
        description="CoinDesk cryptocurrency news",
    ),
    NewsSource(
        id="cointelegraph",
        name="CoinTelegraph",
        url="https://cointelegraph.com/rss",
        category=SourceCategory.CRYPTO,
        tier=SourceTier.TIER_2,
        description="CoinTelegraph cryptocurrency",
    ),
    NewsSource(
        id="theblock",
        name="The Block",
        url="https://www.theblock.co/rss.xml",
        category=SourceCategory.CRYPTO,
        tier=SourceTier.TIER_2,
        description="The Block crypto news",
    ),
]

# Tier 2: Tech
TIER2_TECH = [
    NewsSource(
        id="techcrunch",
        name="TechCrunch",
        url="https://techcrunch.com/feed/",
        category=SourceCategory.TECH,
        tier=SourceTier.TIER_2,
        description="TechCrunch startup/tech news",
    ),
    NewsSource(
        id="finextra",
        name="Finextra",
        url="https://www.finextra.com/rss/headlines.aspx",
        category=SourceCategory.TECH,
        tier=SourceTier.TIER_2,
        description="Finextra fintech news",
    ),
    NewsSource(
        id="theverge",
        name="The Verge",
        url="https://www.theverge.com/rss/index.xml",
        category=SourceCategory.TECH,
        tier=SourceTier.TIER_2,
        description="The Verge technology",
    ),
    NewsSource(
        id="arstechnica",
        name="Ars Technica",
        url="https://feeds.arstechnica.com/arstechnica/index",
        category=SourceCategory.TECH,
        tier=SourceTier.TIER_2,
        description="Ars Technica technology",
    ),
]

# Tier 3: Additional (blogs, aggregators, supplementary)
TIER3_ADDITIONAL = [
    NewsSource(
        id="bbc-world",
        name="BBC World",
        url="http://feeds.bbci.co.uk/news/world/rss.xml",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_3,
        description="BBC World news",
    ),
    NewsSource(
        id="calculated-risk",
        name="Calculated Risk",
        url="https://feeds.feedburner.com/CalculatedRisk",
        category=SourceCategory.ECONOMIC,
        tier=SourceTier.TIER_3,
        description="Calculated Risk economics blog",
    ),
    NewsSource(
        id="zero-hedge",
        name="ZeroHedge",
        url="https://feeds.feedburner.com/zerohedge/feed",
        category=SourceCategory.ECONOMIC,
        tier=SourceTier.TIER_3,
        description="ZeroHedge (use with caution)",
    ),
    NewsSource(
        id="bellingcat",
        name="Bellingcat",
        url="https://www.bellingcat.com/feed/",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_3,
        description="Bellingcat investigations",
    ),
    NewsSource(
        id="hackernews",
        name="Hacker News",
        url="https://hnrss.org/frontpage",
        category=SourceCategory.TECH,
        tier=SourceTier.TIER_3,
        description="Hacker News top stories",
    ),
    NewsSource(
        id="abnormal-returns",
        name="Abnormal Returns",
        url="https://abnormalreturns.com/feed/",
        category=SourceCategory.MARKETS,
        tier=SourceTier.TIER_3,
        description="Abnormal Returns investment blog",
    ),
]

# All sources combined
ALL_SOURCES = (
    TIER1_WIRE_REGULATORY
    + TIER1_FINANCIAL
    + TIER2_INDIA
    + TIER2_GLOBAL
    + TIER2_CRYPTO
    + TIER2_TECH
    + TIER3_ADDITIONAL
)

# Source lookup by ID
SOURCES_BY_ID: dict[str, NewsSource] = {s.id: s for s in ALL_SOURCES}

# Sources by category
SOURCES_BY_CATEGORY: dict[SourceCategory, list[NewsSource]] = {}
for source in ALL_SOURCES:
    if source.category not in SOURCES_BY_CATEGORY:
        SOURCES_BY_CATEGORY[source.category] = []
    SOURCES_BY_CATEGORY[source.category].append(source)

# Sources by tier
SOURCES_BY_TIER: dict[SourceTier, list[NewsSource]] = {}
for source in ALL_SOURCES:
    if source.tier not in SOURCES_BY_TIER:
        SOURCES_BY_TIER[source.tier] = []
    SOURCES_BY_TIER[source.tier].append(source)

# Tier 1 and 2 sources (higher priority for frequent updates)
HIGH_PRIORITY_SOURCES = [s for s in ALL_SOURCES if s.tier in (SourceTier.TIER_1, SourceTier.TIER_2)]

# India sources
INDIA_SOURCES = [s for s in ALL_SOURCES if s.category == SourceCategory.MARKETS and s.id in (
    "moneycontrol", "et-markets", "livemint", "hindu-biz"
)]


def get_source_by_id(source_id: str) -> NewsSource | None:
    """Get a source by its ID."""
    return SOURCES_BY_ID.get(source_id)


def get_sources_by_category(category: SourceCategory) -> list[NewsSource]:
    """Get all sources in a category."""
    return SOURCES_BY_CATEGORY.get(category, [])


def get_sources_by_tier(tier: SourceTier) -> list[NewsSource]:
    """Get all sources in a tier."""
    return SOURCES_BY_TIER.get(tier, [])


def get_all_source_ids() -> list[str]:
    """Get all source IDs."""
    return list(SOURCES_BY_ID.keys())


def get_high_priority_sources() -> list[NewsSource]:
    """Get tier 1 and 2 sources for frequent updates."""
    return HIGH_PRIORITY_SOURCES


def get_india_sources() -> list[NewsSource]:
    """Get India-focused sources."""
    return INDIA_SOURCES
