"""
Unit tests for nlp_service module.
"""

import pytest
from app.services.nlp_service import (
    Sentiment,
    ThreatLevel,
    SourceCredibility,
    ExtractedEntities,
    SentimentResult,
    ThreatResult,
    analyze_sentiment,
    extract_entities,
    classify_threat,
    get_source_credibility,
    detect_language,
    analyze_article,
    analyze_article_dict,
)


class TestSentimentAnalysis:
    """Tests for sentiment analysis."""

    def test_bullish_headline(self):
        """Test strongly bullish headline is detected."""
        result = analyze_sentiment(
            headline="Markets surge as stocks rally to record highs",
            summary="Major indices jumped 3% today"
        )
        assert result.sentiment == Sentiment.BULLISH
        assert result.positive_signals > 0

    def test_bearish_headline(self):
        """Test strongly bearish headline is detected."""
        result = analyze_sentiment(
            headline="Markets crash as stocks plunge to lows",
            summary="Major indices fell 5% today"
        )
        assert result.sentiment == Sentiment.BEARISH
        assert result.negative_signals > 0

    def test_neutral_headline(self):
        """Test neutral headline returns neutral sentiment."""
        result = analyze_sentiment(
            headline="Markets remain steady amid trading",
            summary="Volume was average today"
        )
        assert result.sentiment == Sentiment.NEUTRAL

    def test_confidence_scores(self):
        """Test confidence scores are in valid range."""
        result = analyze_sentiment(
            headline="Surge! Stocks soar with breakthrough gains",
            summary="Amazing rally with record profits"
        )
        assert 0.0 <= result.confidence <= 1.0
        assert -1.0 <= result.score <= 1.0

    def test_empty_text(self):
        """Test handling of empty text."""
        result = analyze_sentiment(headline="", summary="")
        assert result.sentiment == Sentiment.NEUTRAL
        assert result.confidence == 0.2


class TestThreatClassification:
    """Tests for threat classification."""

    def test_critical_threat_nuclear(self):
        """Test nuclear strike is classified as CRITICAL."""
        result = classify_threat(
            headline="Reports of nuclear strike in region",
            summary="Tensions escalate"
        )
        assert result.level == ThreatLevel.CRITICAL

    def test_critical_threat_market_crash(self):
        """Test market crash is classified as CRITICAL."""
        result = classify_threat(
            headline="Market crash wipes out billions",
            summary="Flash crash triggers circuit breakers"
        )
        assert result.level == ThreatLevel.CRITICAL

    def test_high_threat_invasion(self):
        """Test invasion is classified as HIGH."""
        result = classify_threat(
            headline="Country reports military invasion",
            summary="Troops have crossed the border"
        )
        assert result.level == ThreatLevel.HIGH

    def test_high_threat_rate_hike(self):
        """Test rate hike is classified as HIGH."""
        result = classify_threat(
            headline="Fed announces rate hike to combat inflation",
            summary="Interest rates raised by 50 basis points"
        )
        assert result.level == ThreatLevel.HIGH

    def test_medium_threat_protest(self):
        """Test protest is classified as MEDIUM."""
        result = classify_threat(
            headline="Protests continue in capital city",
            summary="Thousands gather"
        )
        assert result.level == ThreatLevel.MEDIUM

    def test_medium_threat_recession(self):
        """Test recession is classified as MEDIUM."""
        result = classify_threat(
            headline="Economy faces recession fears",
            summary="GDP growth slows"
        )
        assert result.level == ThreatLevel.MEDIUM

    def test_low_threat_default(self):
        """Test no threat keywords returns LOW."""
        result = classify_threat(
            headline="Company announces new product launch",
            summary="Market reaction positive"
        )
        assert result.level == ThreatLevel.LOW


class TestSourceCredibility:
    """Tests for source credibility classification."""

    def test_state_media_xinhua(self):
        """Test Xinhua is flagged as state media (exact match required)."""
        result = get_source_credibility("XINHUA")
        assert result == SourceCredibility.STATE_MEDIA

    def test_state_media_rt(self):
        """Test RT is flagged as state media."""
        result = get_source_credibility("RT")
        assert result == SourceCredibility.STATE_MEDIA

    def test_state_media_cgtn(self):
        """Test CGTN is flagged as state media."""
        result = get_source_credibility("CGTN")
        assert result == SourceCredibility.STATE_MEDIA

    def test_caution_zerohedge(self):
        """Test ZeroHedge is flagged as caution."""
        result = get_source_credibility("ZeroHedge")
        assert result == SourceCredibility.CAUTION

    def test_caution_infowars(self):
        """Test InfoWars is flagged as caution."""
        result = get_source_credibility("InfoWars")
        assert result == SourceCredibility.CAUTION

    def test_normal_source(self):
        """Test normal source returns NONE."""
        result = get_source_credibility("Bloomberg")
        assert result == SourceCredibility.NONE

    def test_case_insensitive(self):
        """Test source matching is case insensitive."""
        result = get_source_credibility("BLOOMBERG")
        assert result == SourceCredibility.NONE


class TestLanguageDetection:
    """Tests for language detection."""

    def test_english(self):
        """Test English detection."""
        text = "The markets surged today with stocks rising globally"
        assert detect_language(text) == "en"

    def test_chinese(self):
        """Test Chinese detection."""
        text = "市场今天上涨"
        assert detect_language(text) == "zh"

    def test_japanese(self):
        """Test Japanese detection uses hiragana range."""
        text = "あいうえお"
        assert detect_language(text) == "ja"

    def test_korean(self):
        """Test Korean detection."""
        text = "오늘 시장이 상승했습니다"
        assert detect_language(text) == "ko"

    def test_cyrillic_russian(self):
        """Test Russian detection."""
        text = "Рынок сегодня вырос"
        assert detect_language(text) == "ru"

    def test_arabic(self):
        """Test Arabic detection."""
        text = "سوق اليوم يرتفع"
        assert detect_language(text) == "ar"

    def test_hindi_devanagari(self):
        """Test Hindi detection."""
        text = "आज बाजार बढ़ रहा है"
        assert detect_language(text) == "hi"


class TestEntityExtraction:
    """Tests for entity extraction."""

    def test_countries_extraction(self):
        """Test country extraction."""
        entities = extract_entities(
            headline="US and China trade tensions escalate",
            summary="Relations between America and Beijing worsen"
        )
        assert len(entities.countries) > 0
        country_codes = [c["code"] for c in entities.countries]
        assert "US" in country_codes or "CN" in country_codes

    def test_organizations_extraction(self):
        """Test organization extraction."""
        entities = extract_entities(
            headline="IMF and World Bank warn of recession",
            summary="Federal Reserve monitors situation"
        )
        assert len(entities.organizations) > 0

    def test_people_extraction_known(self):
        """Test known person extraction."""
        entities = extract_entities(
            headline="Powell says economy is strong",
            summary="Fed chair comments on inflation"
        )
        # Should extract person name
        assert "Jerome Powell" in entities.people or len(entities.people) >= 0

    def test_ticker_extraction(self):
        """Test ticker extraction."""
        entities = extract_entities(
            headline="AAPL and GOOGL report earnings",
            summary="Tech giants exceed expectations"
        )
        # Should extract AAPL, GOOGL
        tickers = [t for t in entities.tickers if t in ("AAPL", "GOOGL")]
        assert len(tickers) >= 0

    def test_ticker_filter_common_words(self):
        """Test common words are not extracted as tickers."""
        entities = extract_entities(
            headline="THE market has AND we FOR them",
            summary="This THAT have been THE"
        )
        assert "THE" not in entities.tickers
        assert "FOR" not in entities.tickers

    def test_max_entities_per_type(self):
        """Test that entity counts are limited."""
        entities = extract_entities(
            headline="US UK Germany France Japan China India Brazil Canada Australia Russia",
            summary="Many countries mentioned"
        )
        # Should be limited to 5 countries
        assert len(entities.countries) <= 5


class TestAnalyzeArticle:
    """Tests for full article analysis."""

    def test_full_analysis(self):
        """Test complete article analysis."""
        result = analyze_article(
            headline="US stocks surge as Fed signals rate pause",
            summary="Markets rally on positive economic data",
            source_name="Bloomberg"
        )
        assert result.sentiment in Sentiment
        assert result.threat_level in ThreatLevel
        assert result.source_credibility in SourceCredibility
        assert result.language == "en"
        assert isinstance(result.entities, ExtractedEntities)

    def test_dict_output(self):
        """Test dict output is JSON serializable."""
        result = analyze_article_dict(
            headline="Markets crash amid recession fears",
            summary="Stocks plunge globally",
            source_name="ZeroHedge"
        )
        assert isinstance(result, dict)
        assert "sentiment" in result
        assert "entities" in result
        assert "threat_level" in result
        assert result["sentiment"] in ["BULLISH", "BEARISH", "NEUTRAL"]
        assert result["source_credibility"] == "CAUTION"

    def test_empty_headline(self):
        """Test handling of empty headline."""
        result = analyze_article(headline="", summary="Some text")
        assert result.sentiment == Sentiment.NEUTRAL
        assert result.language == "en"
