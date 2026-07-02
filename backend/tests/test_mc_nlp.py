import pytest
from app.services.mc_nlp import analyze_mc_article_dict
from app.services.nlp_service import Sentiment, ThreatLevel

def test_mc_nlp_earnings_up():
    res = analyze_mc_article_dict(
        headline="Paisalo Digital Consolidated September 2025 Net Sales at Rs 224.01 crore, up 19.78% Y-o-Y"
    )
    assert res["sentiment"] == Sentiment.BULLISH.value

def test_mc_nlp_shares_rise():
    res = analyze_mc_article_dict(
        headline="GRSE shares rise nearly 5% to hit over 1-month high as govt approves Navratna status"
    )
    assert res["sentiment"] == Sentiment.BULLISH.value
    assert res["threat_level"] == ThreatLevel.LOW.value

def test_mc_nlp_jumps():
    res = analyze_mc_article_dict(
        headline="Buzzing Stocks: RIL jumps 2% on Jio IPO plans; RVNL, Power Mech gain on order wins"
    )
    assert res["sentiment"] == Sentiment.BULLISH.value
    assert res["threat_level"] == ThreatLevel.LOW.value

def test_mc_nlp_neutral():
    res = analyze_mc_article_dict(
        headline="'Thanks for the insult': Developer reveals how a manager's remark pushed him to Google"
    )
    assert res["sentiment"] == Sentiment.NEUTRAL.value
    assert res["threat_level"] == ThreatLevel.LOW.value

def test_mc_nlp_lang():
    res = analyze_mc_article_dict(
        headline="Sanjay Raut's dig amid Shiv Sena UBT's rebellion crisis"
    )
    assert res["sentiment"] == Sentiment.NEUTRAL.value
    assert res["language"] == "en"
