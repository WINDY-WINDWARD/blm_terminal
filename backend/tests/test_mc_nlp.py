import pytest
import app.services.mc_nlp as mc_nlp_mod
from app.services.mc_nlp import analyze_mc_article_dict
from app.services.nlp_service import Sentiment, ThreatLevel


def test_mc_nlp_disabled_returns_neutral_stub():
    """Default (MC_NLP_ENABLED=False): no analysis, neutral stub, empty entities."""
    assert mc_nlp_mod.MC_NLP_ENABLED is False
    res = analyze_mc_article_dict(
        headline="GRSE shares rise nearly 5% to hit over 1-month high as govt approves Navratna status"
    )
    assert res["sentiment"] == Sentiment.NEUTRAL.value
    assert res["sentiment_score"] == 0.0
    assert res["confidence"] == 0.0
    assert res["threat_level"] == ThreatLevel.LOW.value
    assert res["entities"] == {"countries": [], "organizations": [], "people": [], "tickers": []}
    assert res["language"] == "en"


def test_mc_nlp_disabled_stub_shape_matches_enabled():
    """Stub keys must match the enabled-path dict so consumers never break."""
    res = analyze_mc_article_dict(headline="Anything", summary="anything")
    assert set(res.keys()) == {
        "sentiment", "sentiment_score", "confidence", "language",
        "entities", "threat_level", "threat_category", "source_credibility",
    }


def test_mc_nlp_enabled_rules_preserved(monkeypatch):
    """Flag on: legacy rule-based behaviour intact (earnings/shares/threat/lang)."""
    monkeypatch.setattr(mc_nlp_mod, "MC_NLP_ENABLED", True)

    res = analyze_mc_article_dict(
        headline="Paisalo Digital Consolidated September 2025 Net Sales at Rs 224.01 crore, up 19.78% Y-o-Y"
    )
    assert res["sentiment"] == Sentiment.BULLISH.value

    res = analyze_mc_article_dict(
        headline="GRSE shares rise nearly 5% to hit over 1-month high as govt approves Navratna status"
    )
    assert res["sentiment"] == Sentiment.BULLISH.value
    assert res["threat_level"] == ThreatLevel.LOW.value

    res = analyze_mc_article_dict(
        headline="Buzzing Stocks: RIL jumps 2% on Jio IPO plans; RVNL, Power Mech gain on order wins"
    )
    assert res["sentiment"] == Sentiment.BULLISH.value
    assert res["threat_level"] == ThreatLevel.LOW.value

    res = analyze_mc_article_dict(
        headline="'Thanks for the insult': Developer reveals how a manager's remark pushed him to Google"
    )
    assert res["sentiment"] == Sentiment.NEUTRAL.value
    assert res["threat_level"] == ThreatLevel.LOW.value

    res = analyze_mc_article_dict(
        headline="Sanjay Raut's dig amid Shiv Sena UBT's rebellion crisis"
    )
    assert res["sentiment"] == Sentiment.NEUTRAL.value
    assert res["language"] == "en"
