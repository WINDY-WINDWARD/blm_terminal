"""
Unit tests for news_sources module.
"""

import pytest
from app.services.news_sources import (
    ALL_SOURCES,
    SOURCES_BY_ID,
    SourceCategory,
    SourceTier,
    get_source_by_id,
    get_sources_by_category,
    get_sources_by_tier,
    get_all_source_ids,
    get_high_priority_sources,
    get_india_sources,
)


class TestNewsSources:
    """Tests for news source definitions."""

    def test_all_sources_not_empty(self):
        """Verify we have sources defined."""
        assert len(ALL_SOURCES) > 0

    def test_all_sources_have_unique_ids(self):
        """Verify no duplicate source IDs."""
        ids = [s.id for s in ALL_SOURCES]
        assert len(ids) == len(set(ids)), "Duplicate source IDs found"

    def test_all_sources_have_required_fields(self):
        """Verify each source has all required fields."""
        for source in ALL_SOURCES:
            assert source.id, "Source missing ID"
            assert source.name, "Source missing name"
            assert source.url, "Source missing URL"
            assert source.category, "Source missing category"
            assert source.tier, "Source missing tier"

    def test_sources_by_id_complete(self):
        """Verify SOURCES_BY_ID contains all sources."""
        assert len(SOURCES_BY_ID) == len(ALL_SOURCES)
        for source in ALL_SOURCES:
            assert source.id in SOURCES_BY_ID
            assert SOURCES_BY_ID[source.id] == source

    def test_get_source_by_id_valid(self):
        """Test getting a valid source by ID."""
        source = get_source_by_id("bloomberg-mkts")
        assert source is not None
        assert source.name == "Bloomberg Markets"

    def test_get_source_by_id_invalid(self):
        """Test getting an invalid source ID returns None."""
        source = get_source_by_id("nonexistent-source")
        assert source is None

    def test_get_sources_by_category(self):
        """Test filtering sources by category."""
        markets_sources = get_sources_by_category(SourceCategory.MARKETS)
        assert len(markets_sources) > 0
        for source in markets_sources:
            assert source.category == SourceCategory.MARKETS

    def test_get_sources_by_tier(self):
        """Test filtering sources by tier."""
        tier1_sources = get_sources_by_tier(SourceTier.TIER_1)
        assert len(tier1_sources) > 0
        for source in tier1_sources:
            assert source.tier == SourceTier.TIER_1

    def test_get_all_source_ids(self):
        """Test getting all source IDs."""
        ids = get_all_source_ids()
        assert len(ids) == len(ALL_SOURCES)
        assert "bloomberg-mkts" in ids
        assert "moneycontrol" in ids
        assert "coindesk" in ids

    def test_high_priority_sources(self):
        """Test that high priority sources are TIER_1 and TIER_2 only."""
        high_priority = get_high_priority_sources()
        assert len(high_priority) > 0
        for source in high_priority:
            assert source.tier in (SourceTier.TIER_1, SourceTier.TIER_2)

    def test_india_sources(self):
        """Test that India sources are correctly identified."""
        india_sources = get_india_sources()
        assert len(india_sources) > 0
        india_ids = [s.id for s in india_sources]
        assert "moneycontrol" in india_ids
        assert "et-markets" in india_ids
        assert "livemint" in india_ids

    def test_source_categories_covered(self):
        """Verify all major categories are present."""
        categories = {s.category for s in ALL_SOURCES}
        assert SourceCategory.MARKETS in categories
        # At least one of these should be present
        assert len(categories) >= 3

    def test_tier1_sources_are_wire_or_major_financial(self):
        """Verify TIER_1 sources are wire services or major financial."""
        tier1_sources = get_sources_by_tier(SourceTier.TIER_1)
        for source in tier1_sources:
            assert source.category in (
                SourceCategory.REGULATORY,
                SourceCategory.MARKETS,
                SourceCategory.GEOPOLITICS,
            )


class TestSourceTierEnum:
    """Tests for SourceTier enum values."""

    def test_tier_values(self):
        """Verify tier enum has expected values."""
        assert SourceTier.TIER_1 == 1
        assert SourceTier.TIER_2 == 2
        assert SourceTier.TIER_3 == 3


class TestSourceCategoryEnum:
    """Tests for SourceCategory enum values."""

    def test_category_values(self):
        """Verify category enum has expected values."""
        assert SourceCategory.MARKETS.value == "MARKETS"
        assert SourceCategory.GEOPOLITICS.value == "GEOPOLITICS"
        assert SourceCategory.CRYPTO.value == "CRYPTO"
        assert SourceCategory.TECH.value == "TECH"
        assert SourceCategory.REGULATORY.value == "REGULATORY"
        assert SourceCategory.ECONOMIC.value == "ECONOMIC"
