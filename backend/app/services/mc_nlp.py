import re
from typing import Any
from app.services.nlp_service import (
    Sentiment, 
    ThreatLevel, 
    SourceCredibility, 
    ExtractedEntities,
    detect_language,
    extract_entities,
    get_source_credibility,
    analyze_sentiment,
    classify_threat
)

def analyze_mc_sentiment(headline: str, summary: str = "") -> dict[str, Any]:
    """MoneyControl specific sentiment rules."""
    text = f"{headline} {summary}".lower()
    
    # Positive Earnings/Sales
    if re.search(r'(net sales|net profit|revenue).* up \d+\.?\d*%', text) or re.search(r'jumps.*on.*plans', text):
        return {"sentiment": Sentiment.BULLISH, "sentiment_score": 2.0, "confidence": 0.8}
        
    # Share price increases
    if re.search(r'shares rise', text) or re.search(r'stock jumps', text) or re.search(r'gain.*on order wins', text):
        return {"sentiment": Sentiment.BULLISH, "sentiment_score": 2.0, "confidence": 0.8}

    # Negative Earnings
    if re.search(r'(net sales|net profit|revenue).* down \d+\.?\d*%', text):
        return {"sentiment": Sentiment.BEARISH, "sentiment_score": -2.0, "confidence": 0.8}

    # Neutral things
    if "rebellion crisis" in text or "developer reveals" in text or "to leave" in text:
        return {"sentiment": Sentiment.NEUTRAL, "sentiment_score": 0.0, "confidence": 0.8}
        
    # Fallback to generic
    res = analyze_sentiment(headline, summary)
    return {"sentiment": res.sentiment, "sentiment_score": res.score, "confidence": res.confidence}

def classify_mc_threat(headline: str, summary: str = "") -> dict[str, Any]:
    """MoneyControl specific threat rules. Suppress false alarms on market terms."""
    text = f"{headline} {summary}".lower()
    
    # If it's standard corporate stuff, it's not a conflict
    if re.search(r'jumps.*on.*plans', text) or "shares rise" in text or "rebellion crisis" in text:
        # Note: rebellion crisis might be political, but usually low threat in market context unless extreme
        return {"threat_level": ThreatLevel.LOW, "threat_category": "general"}
        
    # Fallback to generic
    res = classify_threat(headline, summary)
    return {"threat_level": res.level, "threat_category": res.category}

def detect_mc_language(headline: str, summary: str = "") -> str:
    """MoneyControl specific language. English by default for standard titles."""
    text = f"{headline} {summary}".lower()
    if re.match(r'^[a-z0-9\s,\.\'":;\-\(\)\%]+$', headline.lower()):
        return "en"
    return detect_language(headline + " " + summary)

def analyze_mc_article_dict(headline: str, summary: str = "", source_name: str = "") -> dict[str, Any]:
    """Wrapper that returns dict matching analyze_article_dict structure."""
    sentiment = analyze_mc_sentiment(headline, summary)
    threat = classify_mc_threat(headline, summary)
    lang = detect_mc_language(headline, summary)
    entities = extract_entities(headline, summary)
    
    # Credibility for MC is always NONE typically, but let's keep get_source_credibility
    credibility = get_source_credibility(source_name)
    
    # Format entities as dict
    from dataclasses import asdict
    
    return {
        "sentiment": sentiment["sentiment"].value,
        "sentiment_score": sentiment["sentiment_score"],
        "confidence": sentiment["confidence"],
        "language": lang,
        "entities": asdict(entities),
        "threat_level": threat["threat_level"].value,
        "threat_category": threat["threat_category"],
        "source_credibility": credibility.value,
    }
