"""
Unit tests for notification worker helpers.

These tests mock NSE client responses and verify the parsing and alert generation logic.
"""
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock
import pandas as pd

from app.backgroundtasks import (
    DealRecord,
    _coerce_int,
    _coerce_float,
    _is_recent,
    _parse_52week_data,
    _parse_volume_gainers,
    _parse_largedeal_snapshot,
    _build_alerts,
    _safe_fetch_52week_high,
    _safe_fetch_52week_low,
    _safe_fetch_volume_gainers,
    _safe_fetch_top_gainers,
    _safe_fetch_top_losers,
    _safe_fetch_largedeal_snapshot,
)


class TestDealRecord:
    """Test DealRecord dataclass."""
    
    def test_deal_record_creation(self):
        deal = DealRecord(
            symbol="TEST",
            deal_type="bulk",
            date="12-Mar-2026",
            qty=1000,
            watp=150.5,
            client_name="Test Client",
            buy_sell="buy",
        )
        assert deal.symbol == "TEST"
        assert deal.deal_type == "bulk"
        assert deal.qty == 1000
        assert deal.watp == 150.5


class TestCoercionHelpers:
    """Test _coerce_int and _coerce_float."""
    
    def test_coerce_int_none(self):
        assert _coerce_int(None) == 0
    
    def test_coerce_int_string(self):
        assert _coerce_int("123") == 123
    
    def test_coerce_int_string_with_commas(self):
        assert _coerce_int("1,234") == 1234
    
    def test_coerce_int_invalid(self):
        assert _coerce_int("invalid") == 0
    
    def test_coerce_float_none(self):
        assert _coerce_float(None) == 0.0
    
    def test_coerce_float_string(self):
        assert _coerce_float("123.45") == 123.45
    
    def test_coerce_float_string_with_commas(self):
        assert _coerce_float("1,234.56") == 1234.56
    
    def test_coerce_float_invalid(self):
        assert _coerce_float("invalid") == 0.0


class TestIsRecent:
    """Test _is_recent function."""
    
    def test_is_recent_none(self):
        assert _is_recent(None, 7) == False
    
    def test_is_recent_empty_string(self):
        assert _is_recent("", 7) == False
    
    def test_is_recent_today(self):
        today = date.today().strftime("%d-%b-%Y")
        assert _is_recent(today, 7) == True
    
    def test_is_recent_yesterday(self):
        yesterday = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
        assert _is_recent(yesterday, 7) == True
    
    def test_is_recent_within_window(self):
        five_days_ago = (date.today() - timedelta(days=5)).strftime("%d-%b-%Y")
        assert _is_recent(five_days_ago, 7) == True
    
    def test_is_recent_outside_window(self):
        ten_days_ago = (date.today() - timedelta(days=10)).strftime("%d-%b-%Y")
        assert _is_recent(ten_days_ago, 7) == False
    
    def test_is_recent_invalid_format(self):
        # Should log warning and return False
        assert _is_recent("invalid-date", 7) == False
    
    def test_is_recent_future_date(self):
        # Future date should be False (not within last N days)
        tomorrow = (date.today() + timedelta(days=1)).strftime("%d-%b-%Y")
        assert _is_recent(tomorrow, 7) == False


class TestParse52WeekData:
    """Test _parse_52week_data function."""
    
    def test_empty_dict(self):
        assert _parse_52week_data({}) == {}
    
    def test_empty_data_list(self):
        assert _parse_52week_data({"data": []}) == {}
    
    def test_with_items(self):
        data = {
            "data": [
                {
                    "symbol": "TEST1",
                    "ltp": 100.5,
                    "new52WHL": 150,
                    "pChange": 5.5,
                },
                {
                    "symbol": "TEST2",
                    "ltp": 200,
                    "new52WHL": 250,
                    "pChange": -2.3,
                },
            ]
        }
        result = _parse_52week_data(data)
        assert "TEST1" in result
        assert "TEST2" in result
        assert result["TEST1"]["ltp"] == 100.5
        assert result["TEST1"]["new52WHL"] == 150
        assert result["TEST2"]["pChange"] == -2.3
    
    def test_missing_symbol(self):
        data = {
            "data": [
                {"ltp": 100},  # no symbol
                {"symbol": "TEST", "ltp": 200},
            ]
        }
        result = _parse_52week_data(data)
        assert len(result) == 1
        assert "TEST" in result


class TestParseVolumeGainers:
    """Test _parse_volume_gainers function."""
    
    def test_empty_dict(self):
        assert _parse_volume_gainers({}) == {}
    
    def test_with_items(self):
        data = {
            "data": [
                {
                    "symbol": "TEST",
                    "week1volChange": 4.96,
                    "pChange": 5.95,
                },
            ]
        }
        result = _parse_volume_gainers(data)
        assert "TEST" in result
        assert result["TEST"]["week1volChange"] == 4.96
        assert result["TEST"]["pChange"] == 5.95


class TestParseLargedealSnapshot:
    """Test _parse_largedeal_snapshot function."""
    
    def test_empty_dict(self):
        assert _parse_largedeal_snapshot({}) == {}
    
    def test_bulk_deals(self):
        snapshot = {
            "BULK_DEALS_DATA": [
                {
                    "date": "12-Mar-2026",
                    "symbol": "TEST",
                    "clientName": "Test Client",
                    "buySell": "buy",
                    "qty": "1,000",
                    "watp": "150.5",
                },
            ],
            "BLOCK_DEALS_DATA": [],
            "SHORT_DEALS_DATA": [],
        }
        deals_by_symbol = _parse_largedeal_snapshot(snapshot)
        assert "TEST" in deals_by_symbol
        deals = deals_by_symbol["TEST"]
        assert len(deals) == 1
        assert deals[0].symbol == "TEST"
        assert deals[0].deal_type == "bulk"
        assert deals[0].qty == 1000
        assert deals[0].watp == 150.5
    
    def test_block_deals(self):
        snapshot = {
            "BULK_DEALS_DATA": [],
            "BLOCK_DEALS_DATA": [
                {
                    "date": "12-Mar-2026",
                    "symbol": "TEST",
                    "qty": "500",
                    "watp": "200",
                },
            ],
            "SHORT_DEALS_DATA": [],
        }
        deals_by_symbol = _parse_largedeal_snapshot(snapshot)
        assert "TEST" in deals_by_symbol
        deals = deals_by_symbol["TEST"]
        assert len(deals) == 1
        assert deals[0].deal_type == "block"
        assert deals[0].qty == 500
    
    def test_short_deals(self):
        snapshot = {
            "BULK_DEALS_DATA": [],
            "BLOCK_DEALS_DATA": [],
            "SHORT_DEALS_DATA": [
                {
                    "date": "12-Mar-2026",
                    "symbol": "TEST",
                    "qty": "100",
                    "watp": "50",
                },
            ],
        }
        deals_by_symbol = _parse_largedeal_snapshot(snapshot)
        assert "TEST" in deals_by_symbol
        deals = deals_by_symbol["TEST"]
        assert len(deals) == 1
        assert deals[0].deal_type == "short"
    
    def test_missing_fields(self):
        snapshot = {
            "BULK_DEALS_DATA": [
                {"symbol": "TEST"},  # missing qty and watp
            ],
        }
        deals_by_symbol = _parse_largedeal_snapshot(snapshot)
        assert "TEST" in deals_by_symbol
        deals = deals_by_symbol["TEST"]
        assert len(deals) == 1
        assert deals[0].qty == 0
        assert deals[0].watp == 0.0
    
    def test_null_values(self):
        snapshot = {
            "BULK_DEALS_DATA": [
                {
                    "symbol": "TEST",
                    "qty": None,
                    "watp": None,
                },
            ],
        }
        deals_by_symbol = _parse_largedeal_snapshot(snapshot)
        assert "TEST" in deals_by_symbol
        deals = deals_by_symbol["TEST"]
        assert len(deals) == 1
        assert deals[0].qty == 0
        assert deals[0].watp == 0.0


class TestBuildAlerts:
    """Test _build_alerts function."""
    
    def test_empty_alerts(self):
        alerts = _build_alerts("TEST")
        assert alerts == []
    
    def test_52week_high_alert(self):
        high52_data = {"TEST": {"ltp": 150, "new52WHL": 200}}
        alerts = _build_alerts("TEST", high52_data=high52_data)
        assert len(alerts) == 1
        assert alerts[0][0] == "52w_high_breakout"
        assert "150" in alerts[0][1]
    
    def test_52week_low_alert(self):
        low52_data = {"TEST": {"ltp": 100, "new52WHL": 50}}
        alerts = _build_alerts("TEST", low52_data=low52_data)
        assert len(alerts) == 1
        assert alerts[0][0] == "52w_low_breakout"
    
    def test_volume_breakout_alert(self):
        vol_data = {"TEST": {"week1volChange": 5.5}}
        alerts = _build_alerts("TEST", vol_data=vol_data)
        assert len(alerts) == 1
        assert alerts[0][0] == "volume_breakout"
        # The formatting uses :.0f, so 5.5 becomes 6
        assert "6x" in alerts[0][1]
    
    def test_top_gainer_alert(self):
        gainers_df = pd.DataFrame([
            {"symbol": "TEST", "pChange": 5.5},
        ])
        alerts = _build_alerts("TEST", gainers_df=gainers_df)
        assert len(alerts) == 1
        assert alerts[0][0] == "top_gainer"
        assert "+5.5%" in alerts[0][1]
    
    def test_top_loser_alert(self):
        losers_df = pd.DataFrame([
            {"symbol": "TEST", "pChange": -3.2},
        ])
        alerts = _build_alerts("TEST", losers_df=losers_df)
        assert len(alerts) == 1
        assert alerts[0][0] == "top_loser"
        assert "-3.2%" in alerts[0][1]
    
    def test_deal_alert(self):
        deals = [
            DealRecord(
                symbol="TEST",
                deal_type="bulk",
                date=date.today().strftime("%d-%b-%Y"),
                qty=1000,
                watp=150.5,
                client_name=None,
                buy_sell=None,
            ),
        ]
        deals_by_symbol = {"TEST": deals}
        alerts = _build_alerts("TEST", deals_by_symbol=deals_by_symbol)
        assert len(alerts) == 1
        assert alerts[0][0] == "bulk_deal"
        assert "1,000 shares" in alerts[0][1]
    
    def test_deal_alert_old_date(self):
        ten_days_ago = (date.today() - timedelta(days=10)).strftime("%d-%b-%Y")
        deals = [
            DealRecord(
                symbol="TEST",
                deal_type="bulk",
                date=ten_days_ago,
                qty=1000,
                watp=150.5,
                client_name=None,
                buy_sell=None,
            ),
        ]
        deals_by_symbol = {"TEST": deals}
        alerts = _build_alerts("TEST", deals_by_symbol=deals_by_symbol)
        # Deal is older than DAILY_NOTIFICATION_WINDOW_DAYS (7 days)
        assert len(alerts) == 0
    
    def test_insider_trade_buy_alert(self):
        insider_trades = [
            {"direction": "up", "person": "John Doe", "quantity": 5000},
        ]
        alerts = _build_alerts("TEST", insider_trades=insider_trades)
        assert len(alerts) == 1
        assert alerts[0][0] == "insider_buy"
        assert "John Doe" in alerts[0][1]
    
    def test_insider_trade_sell_alert(self):
        insider_trades = [
            {"direction": "down", "person": "Jane Doe", "quantity": 3000},
        ]
        alerts = _build_alerts("TEST", insider_trades=insider_trades)
        assert len(alerts) == 1
        assert alerts[0][0] == "insider_sell"
    
    def test_multiple_alerts(self):
        """Test that multiple triggers generate multiple alerts."""
        high52_data = {"TEST": {"ltp": 150}}
        vol_data = {"TEST": {"week1volChange": 4.0}}
        alerts = _build_alerts(
            "TEST",
            high52_data=high52_data,
            vol_data=vol_data,
        )
        assert len(alerts) == 2
        trigger_types = [a[0] for a in alerts]
        assert "52w_high_breakout" in trigger_types
        assert "volume_breakout" in trigger_types


class TestSafeFetchWrappers:
    """Test safe fetch wrapper functions."""
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_52week_high_success(self, mock_client):
        mock_client.get_52week_high_stocks.return_value = {"data": []}
        result = _safe_fetch_52week_high()
        assert result == {"data": []}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_52week_high_failure(self, mock_client):
        mock_client.get_52week_high_stocks.side_effect = Exception("NSE error")
        result = _safe_fetch_52week_high()
        assert result == {}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_52week_low_success(self, mock_client):
        mock_client.get_52week_low_stocks.return_value = {"data": []}
        result = _safe_fetch_52week_low()
        assert result == {"data": []}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_volume_gainers_success(self, mock_client):
        mock_client.get_volume_gainers.return_value = {"data": []}
        result = _safe_fetch_volume_gainers()
        assert result == {"data": []}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_top_gainers_success(self, mock_client):
        df = pd.DataFrame([{"symbol": "TEST"}])
        mock_client.get_top_gainers.return_value = df
        result = _safe_fetch_top_gainers()
        assert result is not None
        assert len(result) == 1
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_top_gainers_failure(self, mock_client):
        mock_client.get_top_gainers.side_effect = Exception("NSE error")
        result = _safe_fetch_top_gainers()
        assert result is None
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_largedeal_snapshot_success(self, mock_client):
        mock_client.get_largedeal_snapshot.return_value = {"BULK_DEALS_DATA": []}
        result = _safe_fetch_largedeal_snapshot()
        assert result == {"BULK_DEALS_DATA": []}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_largedeal_snapshot_failure(self, mock_client):
        mock_client.get_largedeal_snapshot.side_effect = Exception("NSE error")
        result = _safe_fetch_largedeal_snapshot()
        assert result == {}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_52week_low_failure(self, mock_client):
        mock_client.get_52week_low_stocks.side_effect = Exception("NSE error")
        result = _safe_fetch_52week_low()
        assert result == {}
    
    @patch('app.backgroundtasks._nse_client')
    def test_safe_fetch_top_losers_failure(self, mock_client):
        mock_client.get_top_losers.side_effect = Exception("NSE error")
        result = _safe_fetch_top_losers()
        assert result is None


class TestIntegration:
    """Integration tests for the full notification cycle."""
    
    @patch('app.backgroundtasks._get_watchlist_symbols')
    @patch('app.backgroundtasks._get_seen_today')
    @patch('app.backgroundtasks._safe_fetch_52week_high')
    @patch('app.backgroundtasks._safe_fetch_52week_low')
    @patch('app.backgroundtasks._safe_fetch_volume_gainers')
    @patch('app.backgroundtasks._safe_fetch_top_gainers')
    @patch('app.backgroundtasks._safe_fetch_top_losers')
    @patch('app.backgroundtasks._safe_fetch_largedeal_snapshot')
    @patch('app.backgroundtasks._fetch_insider_trades_cached')
    @patch('app.backgroundtasks._bulk_upsert_notifications')
    @patch('app.backgroundtasks._run_cleanup_if_due')
    def test_notification_cycle_full_with_alerts(
        self,
        mock_cleanup,
        mock_bulk_upsert,
        mock_insider_trades,
        mock_largedeal,
        mock_losers,
        mock_gainers,
        mock_volume,
        mock_low52,
        mock_high52,
        mock_seen_today,
        mock_watchlist_symbols,
    ):
        """Test that notification cycle creates alerts when triggers are present."""
        from app.backgroundtasks import _notification_cycle_full
        
        # Setup mocks
        mock_watchlist_symbols.return_value = {1: ["TEST"]}
        mock_seen_today.return_value = set()
        mock_high52.return_value = {"data": [{"symbol": "TEST", "ltp": 150}]}
        mock_low52.return_value = {"data": []}
        mock_volume.return_value = {"data": []}
        mock_gainers.return_value = None
        mock_losers.return_value = None
        mock_largedeal.return_value = {"BULK_DEALS_DATA": [], "BLOCK_DEALS_DATA": [], "SHORT_DEALS_DATA": []}
        mock_insider_trades.return_value = []
        
        # Run the cycle
        _notification_cycle_full()
        
        # Should have called bulk_upsert with 1 notification (52-week high)
        mock_bulk_upsert.assert_called_once()
        pending = mock_bulk_upsert.call_args[0][0]
        assert len(pending) == 1
        assert pending[0]["trigger_type"] == "52w_high_breakout"
        assert pending[0]["symbol"] == "TEST"
        assert pending[0]["watchlist_id"] == 1
    
    @patch('app.backgroundtasks._get_watchlist_symbols')
    @patch('app.backgroundtasks._get_seen_today')
    @patch('app.backgroundtasks._safe_fetch_52week_high')
    @patch('app.backgroundtasks._safe_fetch_52week_low')
    @patch('app.backgroundtasks._safe_fetch_volume_gainers')
    @patch('app.backgroundtasks._safe_fetch_top_gainers')
    @patch('app.backgroundtasks._safe_fetch_top_losers')
    @patch('app.backgroundtasks._safe_fetch_largedeal_snapshot')
    @patch('app.backgroundtasks._fetch_insider_trades_cached')
    @patch('app.backgroundtasks._bulk_upsert_notifications')
    @patch('app.backgroundtasks._run_cleanup_if_due')
    def test_notification_cycle_full_no_alerts(
        self,
        mock_cleanup,
        mock_bulk_upsert,
        mock_insider_trades,
        mock_largedeal,
        mock_losers,
        mock_gainers,
        mock_volume,
        mock_low52,
        mock_high52,
        mock_seen_today,
        mock_watchlist_symbols,
    ):
        """Test that notification cycle does not create alerts when no triggers."""
        from app.backgroundtasks import _notification_cycle_full
        
        # Setup mocks - no triggers
        mock_watchlist_symbols.return_value = {1: ["TEST"]}
        mock_seen_today.return_value = set()
        mock_high52.return_value = {"data": []}
        mock_low52.return_value = {"data": []}
        mock_volume.return_value = {"data": []}
        mock_gainers.return_value = None
        mock_losers.return_value = None
        mock_largedeal.return_value = {}
        mock_insider_trades.return_value = []
        
        # Run the cycle
        _notification_cycle_full()
        
        # Should not call bulk_upsert
        mock_bulk_upsert.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])