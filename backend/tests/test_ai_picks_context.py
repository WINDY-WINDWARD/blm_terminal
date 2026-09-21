import pytest
from unittest.mock import AsyncMock, patch
from app.workers.ai_picks_worker import _fetch_market_context

@pytest.mark.asyncio
async def test_fetch_market_context():
    """Breadth snapshot: gainers/losers/volume + stamped sector breadth, no news block."""
    with patch("app.workers.ai_picks_worker.get_top_gainers", new_callable=AsyncMock) as mock_gainers, \
         patch("app.workers.ai_picks_worker.get_top_losers", new_callable=AsyncMock) as mock_losers, \
         patch("app.workers.ai_picks_worker.get_volume_gainers", new_callable=AsyncMock) as mock_vol, \
         patch("app.workers.ai_picks_worker.list_sectors", new_callable=AsyncMock) as mock_sectors, \
         patch("app.workers.ai_picks_worker.list_industries", new_callable=AsyncMock) as mock_inds:

        mock_gainers.return_value = [{"symbol": "TCS", "perChange": "5.0", "ltp": "4000"}]
        mock_losers.return_value = [{"symbol": "INFY", "perChange": "-2.0", "ltp": "1500"}]
        mock_vol.return_value = [{"symbol": "RELIANCE", "volume_ratio": "3.5"}]
        mock_sectors.return_value = [
            {"name": "Banks", "slug": "banks", "advance": 10, "decline": 2,
             "sentiment": "Bullish", "pe": 15.0, "earnings_yoy": 5.0,
             "last_updated": "2026-09-20T10:00:00"},
            {"name": "IT", "slug": "it", "advance": 1, "decline": 9,
             "sentiment": "Bearish", "pe": 22.0, "earnings_yoy": -3.0,
             "last_updated": "2026-09-20T10:00:00"},
        ]
        mock_inds.return_value = []

        context = await _fetch_market_context()

        assert "TCS" in context
        assert "INFY" in context
        assert "RELIANCE" in context
        assert "Top Gainers" in context
        # Sector breadth present and stamped
        assert "SECTORS BREADTH" in context
        assert "Banks" in context
        assert "2026-09-20T10:00:00" in context
        # News is fetched by the agents via tools, never pre-injected
        assert "Latest Global News" not in context

@pytest.mark.asyncio
async def test_fetch_market_context_survives_source_failures():
    """One failing source must not kill the whole snapshot."""
    with patch("app.workers.ai_picks_worker.get_top_gainers", new_callable=AsyncMock) as mock_gainers, \
         patch("app.workers.ai_picks_worker.get_top_losers", new_callable=AsyncMock) as mock_losers, \
         patch("app.workers.ai_picks_worker.get_volume_gainers", new_callable=AsyncMock) as mock_vol, \
         patch("app.workers.ai_picks_worker.list_sectors", new_callable=AsyncMock) as mock_sectors, \
         patch("app.workers.ai_picks_worker.list_industries", new_callable=AsyncMock) as mock_inds:

        mock_gainers.side_effect = RuntimeError("yahoo down")
        mock_losers.return_value = []
        mock_vol.return_value = []
        mock_sectors.return_value = []
        mock_inds.return_value = []

        context = await _fetch_market_context()

        assert "MARKET BREADTH SNAPSHOT" in context
