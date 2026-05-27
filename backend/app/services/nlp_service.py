"""NLP processing service for news articles.

This module provides:
- Sentiment analysis (weighted word lists)
- Entity extraction (countries, organizations, people, tickers)
- Threat classification (CRITICAL, HIGH, MEDIUM, LOW)
- Language detection
- Source credibility flags
"""

import re
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any


class Sentiment(str, Enum):
    """Sentiment classification."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class ThreatLevel(str, Enum):
    """Threat level classification."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SourceCredibility(str, Enum):
    """Source credibility classification."""
    STATE_MEDIA = "STATE_MEDIA"
    CAUTION = "CAUTION"
    NONE = "NONE"


@dataclass
class ExtractedEntities:
    """Extracted entities from text."""
    countries: list[dict[str, str]]
    organizations: list[str]
    people: list[str]
    tickers: list[str]


@dataclass
class SentimentResult:
    """Sentiment analysis result."""
    sentiment: Sentiment
    score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    positive_signals: int
    negative_signals: int


@dataclass
class ThreatResult:
    """Threat classification result."""
    level: ThreatLevel
    category: str
    confidence: float


@dataclass
class NLPResult:
    """Combined NLP analysis result."""
    sentiment: Sentiment
    sentiment_score: float
    confidence: float
    language: str
    entities: ExtractedEntities
    threat_level: ThreatLevel
    threat_category: str
    source_credibility: SourceCredibility


# ── Sentiment Word Lists ──────────────────────────────────────────────────────

POSITIVE_WORDS: dict[str, int] = {
    "surge": 3, "soar": 3, "skyrocket": 3, "breakthrough": 3, "boom": 3,
    "record high": 3, "rally": 2, "gain": 2, "rise": 2, "jump": 2,
    "climb": 2, "rebound": 2, "boost": 2, "beat": 2, "exceed": 2,
    "upgrade": 2, "profit": 2, "growth": 2, "recover": 2, "victory": 2,
    "ceasefire": 2, "strong": 1, "robust": 1, "bullish": 1, "optimism": 1,
    "milestone": 1, "positive": 1, "success": 1, "approval": 1, "deal": 1,
    "surges": 3, "soars": 3, "record": 2, "high": 1, "up": 1,
    "higher": 2, "gains": 2, "rising": 2, "rallying": 2, "jumps": 2,
}

NEGATIVE_WORDS: dict[str, int] = {
    "crash": 3, "plunge": 3, "collapse": 3, "devastat": 3, "catastroph": 3,
    "invasion": 3, "war": 3, "bankruptcy": 3, "meltdown": 3,
    "fall": 2, "drop": 2, "decline": 2, "tumble": 2, "slump": 2, "miss": 2,
    "fail": 2, "recession": 2, "crisis": 2, "conflict": 2, "attack": 2,
    "sanction": 2, "tariff": 2, "escalat": 2, "layoff": 2, "downgrade": 2,
    "fraud": 2, "scandal": 2, "disaster": 2, "weak": 1, "loss": 1,
    "deficit": 1, "fear": 1, "threat": 1, "warning": 1, "bearish": 1,
    "volatile": 1, "uncertain": 1, "ban": 1, "suspend": 1,
    "crashes": 3, "plunges": 3, "falls": 2, "drops": 2, "declines": 2,
}

# ── Entity Patterns ────────────────────────────────────────────────────────────

COUNTRIES: dict[str, str] = {
    "united states": "US", "usa": "US", "u.s.": "US", "america": "US",
    "china": "CN", "chinese": "CN", "beijing": "CN", "shanghai": "CN",
    "russia": "RU", "russian": "RU", "moscow": "RU", "kremlin": "RU",
    "ukraine": "UA", "ukrainian": "UA", "kyiv": "UA", "kiev": "UA",
    "united kingdom": "GB", "britain": "GB", "british": "GB", "london": "GB", "uk": "GB",
    "germany": "DE", "german": "DE", "berlin": "DE",
    "france": "FR", "french": "FR", "paris": "FR",
    "japan": "JP", "japanese": "JP", "tokyo": "JP",
    "india": "IN", "indian": "IN", "mumbai": "IN", "delhi": "IN",
    "brazil": "BR", "brazilian": "BR",
    "canada": "CA", "canadian": "CA",
    "australia": "AU", "australian": "AU",
    "south korea": "KR", "korean": "KR", "seoul": "KR",
    "north korea": "KP", "pyongyang": "KP",
    "iran": "IR", "iranian": "IR", "tehran": "IR",
    "israel": "IL", "israeli": "IL", "tel aviv": "IL",
    "palestine": "PS", "palestinian": "PS", "gaza": "PS", "west bank": "PS",
    "saudi arabia": "SA", "saudi": "SA", "riyadh": "SA",
    "turkey": "TR", "turkish": "TR", "ankara": "TR", "istanbul": "TR",
    "egypt": "EG", "egyptian": "EG", "cairo": "EG",
    "italy": "IT", "italian": "IT", "rome": "IT",
    "spain": "ES", "spanish": "ES", "madrid": "ES",
    "mexico": "MX", "mexican": "MX",
    "indonesia": "ID", "indonesian": "ID", "jakarta": "ID",
    "netherlands": "NL", "dutch": "NL",
    "switzerland": "CH", "swiss": "CH",
    "sweden": "SE", "swedish": "SE",
    "norway": "NO", "norwegian": "NO",
    "poland": "PL", "polish": "PL", "warsaw": "PL",
    "taiwan": "TW", "taiwanese": "TW", "taipei": "TW",
    "singapore": "SG",
    "hong kong": "HK",
    "south africa": "ZA",
    "nigeria": "NG", "nigerian": "NG", "lagos": "NG",
    "argentina": "AR",
    "colombia": "CO",
    "pakistan": "PK", "pakistani": "PK",
    "thailand": "TH", "thai": "TH", "bangkok": "TH",
    "vietnam": "VN", "vietnamese": "VN",
    "philippines": "PH", "filipino": "PH",
    "malaysia": "MY", "malaysian": "MY",
    "iraq": "IQ", "iraqi": "IQ", "baghdad": "IQ",
    "syria": "SY", "syrian": "SY", "damascus": "SY",
    "yemen": "YE", "yemeni": "YE",
    "libya": "LY", "libyan": "LY",
    "lebanon": "LB", "lebanese": "LB", "beirut": "LB",
    "afghanistan": "AF", "afghan": "AF", "kabul": "AF",
    "myanmar": "MM", "burmese": "MM",
    "ethiopia": "ET", "ethiopian": "ET",
    "sudan": "SD", "sudanese": "SD", "khartoum": "SD",
    "somalia": "SO", "somali": "SO",
    "venezuela": "VE", "venezuelan": "VE",
    "european union": "EU", "eu": "EU", "brussels": "EU",
}

ORGANIZATIONS: dict[str, str] = {
    "nato": "NATO", "united nations": "UN", "un": "UN",
    "imf": "IMF", "world bank": "World Bank",
    "federal reserve": "Federal Reserve", "the fed": "Federal Reserve",
    "ecb": "ECB", "european central bank": "ECB",
    "bank of england": "Bank of England", "boe": "Bank of England",
    "bank of japan": "Bank of Japan", "boj": "Bank of Japan",
    "peoples bank of china": "PBOC", "pboc": "PBOC",
    "sec": "SEC", "securities and exchange": "SEC",
    "opec": "OPEC", "opec+": "OPEC+",
    "world health organization": "WHO", "who": "WHO",
    "world trade organization": "WTO", "wto": "WTO",
    "pentagon": "Pentagon", "white house": "White House",
    "congress": "US Congress", "senate": "US Senate",
    "european commission": "European Commission",
    "iaea": "IAEA", "g7": "G7", "g20": "G20", "brics": "BRICS",
    "reuters": "Reuters", "bloomberg": "Bloomberg",
    "apple": "Apple", "google": "Google", "alphabet": "Alphabet",
    "microsoft": "Microsoft", "amazon": "Amazon", "meta": "Meta",
    "nvidia": "NVIDIA", "tesla": "Tesla", "openai": "OpenAI",
    "goldman sachs": "Goldman Sachs", "jpmorgan": "JPMorgan",
    "blackrock": "BlackRock", "berkshire hathaway": "Berkshire Hathaway",
    "hsbc": "HSBC", "ubs": "UBS", "credit suisse": "Credit Suisse",
    "deutsche bank": "Deutsche Bank", "barclays": "Barclays",
    "citigroup": "Citigroup", "morgan stanley": "Morgan Stanley",
}

KNOWN_PERSONS: dict[str, str] = {
    "biden": "Joe Biden", "trump": "Donald Trump", "obama": "Barack Obama",
    "putin": "Vladimir Putin", "xi jinping": "Xi Jinping", "xi": "Xi Jinping",
    "modi": "Narendra Modi", "macron": "Emmanuel Macron",
    "scholz": "Olaf Scholz", "sunak": "Rishi Sunak", "starmer": "Keir Starmer",
    "kishida": "Fumio Kishida", "trudeau": "Justin Trudeau",
    "zelensky": "Volodymyr Zelensky", "zelenskyy": "Volodymyr Zelensky",
    "netanyahu": "Benjamin Netanyahu",
    "erdogan": "Recep Tayyip Erdogan",
    "musk": "Elon Musk", "bezos": "Jeff Bezos", "zuckerberg": "Mark Zuckerberg",
    "cook": "Tim Cook", "nadella": "Satya Nadella", "altman": "Sam Altman",
    "dimon": "Jamie Dimon", "powell": "Jerome Powell", "lagarde": "Christine Lagarde",
    "yellen": "Janet Yellen",
}

# Common words that look like tickers but aren't
COMMON_TICKER_FALSE_POSITIVES: set[str] = {
    "THE", "FOR", "AND", "BUT", "NOT", "FROM", "WITH", "THIS", "THAT",
    "HAVE", "WILL", "BEEN", "THEY", "WERE", "SAID", "HAS", "ITS", "NEW",
    "ARE", "WAS", "WHO", "HOW", "WHY", "ALL", "CAN", "MAY", "NOW", "SEC",
    "GDP", "CEO", "CFO", "IPO", "ETF", "CPI", "PMI", "OIL", "USD", "EUR",
    "ONE", "TWO", "NEW", "BIG", "TOP", "GET", "SAY", "SEE", "WAY", "DAY",
    "ALL", "OUT", "UP", "DOWN", "OVER", "INTO", "BACK", "ONLY", "JUST",
}

# ── Threat Classification Patterns ─────────────────────────────────────────────

CRITICAL_PATTERNS: list[tuple[str, str]] = [
    ("nuclear strike", "conflict"),
    ("nuclear attack", "conflict"),
    ("war declared", "conflict"),
    ("market crash", "market"),
    ("flash crash", "market"),
    ("circuit breaker", "market"),
    ("bank run", "market"),
    ("sovereign default", "market"),
    ("cyberattack", "cyber"),
    ("data breach", "cyber"),
    ("ransomware", "cyber"),
]

HIGH_PATTERNS: list[tuple[str, str]] = [
    ("invasion", "conflict"),
    ("airstrike", "conflict"),
    ("missile launch", "conflict"),
    ("military deployment", "conflict"),
    ("coup attempt", "conflict"),
    ("martial law", "conflict"),
    ("bankruptcy filing", "market"),
    ("rate hike", "market"),
    ("rate cut", "market"),
    ("earnings miss", "market"),
    ("profit warning", "market"),
    ("downgrade", "market"),
    ("sanction", "regulatory"),
    ("embargo", "regulatory"),
    ("earthquake", "natural"),
    ("tsunami", "natural"),
    ("hurricane", "natural"),
    ("pandemic", "natural"),
]

MEDIUM_PATTERNS: list[tuple[str, str]] = [
    ("protest", "conflict"),
    ("riot", "conflict"),
    ("tension", "conflict"),
    ("escalat", "conflict"),
    ("tariff", "regulatory"),
    ("regulation", "regulatory"),
    ("antitrust", "regulatory"),
    ("investigation", "regulatory"),
    ("layoff", "market"),
    ("recession", "market"),
    ("inflation", "market"),
    ("selloff", "market"),
    ("sell-off", "market"),
    ("volatil", "market"),
    ("wildfire", "natural"),
    ("flood", "natural"),
]

# ── Source Credibility ─────────────────────────────────────────────────────────

STATE_MEDIA_SOURCES: set[str] = {
    "XINHUA", "CGTN", "GLOBAL TIMES", "RT", "TASS", "SPUTNIK",
    "PRESS TV", "KCNA", "TRT WORLD", "AL ARABIYA",
}

CAUTION_SOURCES: set[str] = {
    "ZEROHEDGE", "INFOWARS", "DAILY MAIL", "NY POST",
}


# ── Language Detection ────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Detect language from text.

    Returns ISO 639-1 language code or 'en' as default.
    """
    # Simple character-based detection
    text_lower = text.lower()

    # Check for CJK characters
    if re.search(r'[\u4e00-\u9fff]', text):
        # Chinese
        return "zh"
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
        # Japanese
        return "ja"
    if re.search(r'[\uac00-\ud7af]', text):
        # Korean
        return "ko"

    # Cyrillic - Russian
    if re.search(r'[\u0400-\u04ff]', text):
        return "ru"

    # Arabic
    if re.search(r'[\u0600-\u06ff]', text):
        return "ar"

    # Devanagari - Hindi
    if re.search(r'[\u0900-\u097f]', text):
        return "hi"

    # Default to English
    return "en"


# ── Core NLP Functions ─────────────────────────────────────────────────────────

def analyze_sentiment(headline: str, summary: str = "") -> SentimentResult:
    """Analyze sentiment from headline and optional summary.

    Returns SentimentResult with classification, score, and confidence.
    """
    text = (headline + " " + summary).lower()

    pos_score = 0
    neg_score = 0

    for word, weight in POSITIVE_WORDS.items():
        if word in text:
            pos_score += weight

    for word, weight in NEGATIVE_WORDS.items():
        if word in text:
            neg_score += weight

    total = pos_score + neg_score
    net = pos_score - neg_score

    if total == 0:
        return SentimentResult(
            sentiment=Sentiment.NEUTRAL,
            score=0.0,
            confidence=0.2,
            positive_signals=0,
            negative_signals=0,
        )
    elif net >= 2:
        score = min(net / max(total, 1), 1.0)
        confidence = min(0.4 + total * 0.05, 0.95)
        return SentimentResult(
            sentiment=Sentiment.BULLISH,
            score=score,
            confidence=confidence,
            positive_signals=pos_score,
            negative_signals=neg_score,
        )
    elif net <= -2:
        score = max(net / max(total, 1), -1.0)
        confidence = min(0.4 + total * 0.05, 0.95)
        return SentimentResult(
            sentiment=Sentiment.BEARISH,
            score=score,
            confidence=confidence,
            positive_signals=pos_score,
            negative_signals=neg_score,
        )
    else:
        score = net / max(total, 1)
        confidence = 0.3
        return SentimentResult(
            sentiment=Sentiment.NEUTRAL,
            score=score,
            confidence=confidence,
            positive_signals=pos_score,
            negative_signals=neg_score,
        )


def extract_entities(headline: str, summary: str = "") -> ExtractedEntities:
    """Extract entities from headline and optional summary.

    Returns ExtractedEntities with countries, organizations, people, and tickers.
    """
    text = (headline + " " + summary).lower()
    text_orig = headline + " " + summary

    countries: list[dict[str, str]] = []
    organizations: list[str] = []
    people: list[str] = []
    tickers: list[str] = []

    # Extract countries
    for pattern, code in COUNTRIES.items():
        if len(pattern) <= 4 or " " not in pattern:
            if re.search(r'\b' + re.escape(pattern) + r'\b', text):
                countries.append({"name": pattern.title(), "code": code})
        else:
            if pattern in text:
                countries.append({"name": pattern.title(), "code": code})

    # Deduplicate countries by code
    seen_codes: set[str] = set()
    unique_countries: list[dict[str, str]] = []
    for c in countries:
        if c["code"] not in seen_codes:
            seen_codes.add(c["code"])
            unique_countries.append(c)
    countries = unique_countries[:5]

    # Extract organizations
    for pattern, name in ORGANIZATIONS.items():
        if pattern in text:
            if name not in organizations:
                organizations.append(name)
    organizations = organizations[:5]

    # Extract known persons
    for pattern, name in KNOWN_PERSONS.items():
        if pattern in text:
            if name not in people:
                people.append(name)

    # Extract persons by title patterns
    person_title_patterns = [
        r"\b(president|prime minister|chancellor|king|queen|prince|princess)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        r"\b(ceo|cfo|chairman|director|minister|secretary|governor|general)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        r"\b(mr|mrs|ms|dr|prof)\.\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    ]
    for pat in person_title_patterns:
        for match in re.finditer(pat, text_orig):
            name = match.group(2).strip()
            if len(name) > 3 and name not in people:
                people.append(name)

    people = list(dict.fromkeys(people))[:5]

    # Extract tickers (uppercase 2-5 letter words)
    for match in re.finditer(r'\b[A-Z]{2,5}\b', text_orig):
        t = match.group()
        if t not in COMMON_TICKER_FALSE_POSITIVES:
            if t not in tickers:
                tickers.append(t)
    tickers = tickers[:5]

    return ExtractedEntities(
        countries=countries,
        organizations=organizations,
        people=people,
        tickers=tickers,
    )


def classify_threat(headline: str, summary: str = "") -> ThreatResult:
    """Classify threat level from headline and optional summary.

    Returns ThreatResult with level, category, and confidence.
    """
    text = (headline + " " + summary).lower()

    # Check CRITICAL patterns first
    for pattern, category in CRITICAL_PATTERNS:
        if pattern in text:
            return ThreatResult(level=ThreatLevel.CRITICAL, category=category, confidence=0.95)

    # Check HIGH patterns
    for pattern, category in HIGH_PATTERNS:
        if pattern in text:
            return ThreatResult(level=ThreatLevel.HIGH, category=category, confidence=0.8)

    # Check MEDIUM patterns
    for pattern, category in MEDIUM_PATTERNS:
        if pattern in text:
            return ThreatResult(level=ThreatLevel.MEDIUM, category=category, confidence=0.6)

    return ThreatResult(level=ThreatLevel.LOW, category="general", confidence=0.3)


def get_source_credibility(source_name: str) -> SourceCredibility:
    """Get credibility classification for a source name."""
    name_upper = source_name.upper()
    if name_upper in STATE_MEDIA_SOURCES:
        return SourceCredibility.STATE_MEDIA
    if name_upper in CAUTION_SOURCES:
        return SourceCredibility.CAUTION
    return SourceCredibility.NONE


def analyze_article(headline: str, summary: str = "", source_name: str = "") -> NLPResult:
    """Perform full NLP analysis on an article.

    Returns NLPResult with all analysis components.
    """
    sentiment_result = analyze_sentiment(headline, summary)
    entities = extract_entities(headline, summary)
    threat_result = classify_threat(headline, summary)
    language = detect_language(headline + " " + summary)
    credibility = get_source_credibility(source_name)

    return NLPResult(
        sentiment=sentiment_result.sentiment,
        sentiment_score=sentiment_result.score,
        confidence=sentiment_result.confidence,
        language=language,
        entities=entities,
        threat_level=threat_result.level,
        threat_category=threat_result.category,
        source_credibility=credibility,
    )


def analyze_article_dict(headline: str, summary: str = "", source_name: str = "") -> dict[str, Any]:
    """Perform full NLP analysis and return as dictionary.

    Convenience function for JSON serialization.
    """
    result = analyze_article(headline, summary, source_name)
    return {
        "sentiment": result.sentiment.value,
        "sentiment_score": result.sentiment_score,
        "confidence": result.confidence,
        "language": result.language,
        "entities": asdict(result.entities),
        "threat_level": result.threat_level.value,
        "threat_category": result.threat_category,
        "source_credibility": result.source_credibility.value,
    }
