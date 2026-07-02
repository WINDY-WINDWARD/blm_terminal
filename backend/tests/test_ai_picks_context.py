import pytest
from unittest.mock import AsyncMock, patch
from app.workers.ai_picks_worker import _fetch_market_context

@pytest.mark.asyncio
async def test_fetch_market_context():
    """Test fetching market context returns formatted markdown."""
    with patch("app.workers.ai_picks_worker.get_top_gainers", new_callable=AsyncMock) as mock_gainers, \
         patch("app.workers.ai_picks_worker.get_top_losers", new_callable=AsyncMock) as mock_losers, \
         patch("app.workers.ai_picks_worker.get_volume_gainers", new_callable=AsyncMock) as mock_vol, \
         patch("app.workers.ai_picks_worker.get_global_news", new_callable=AsyncMock) as mock_news:
         
        mock_gainers.return_value = [{"symbol": "TCS", "perChange": "5.0", "ltp": "4000"}]
        mock_losers.return_value = [{"symbol": "INFY", "perChange": "-2.0", "ltp": "1500"}]
        mock_vol.return_value = [{"symbol": "RELIANCE", "volume_ratio": "3.5"}]
        mock_news.return_value = {"articles": [{"title": "Market goes up", "source": "MC"}]}
        
        context = await _fetch_market_context()
        
        assert "TCS" in context
        assert "INFY" in context
        assert "RELIANCE" in context
        assert "Market goes up" in context
        assert "Top Gainers" in context
