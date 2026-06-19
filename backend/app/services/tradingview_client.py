import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

SCANNER_URL = "https://scanner.tradingview.com/india/scan"

TV_COLUMNS = [
    "name",
    "description",
    "close",
    "average_volume_10d_calc",
    "price_earnings_ttm",
    "earnings_per_share_basic_ttm",
    "price_revenue_ttm",
    "price_book_fq",
    "price_free_cash_flow_ttm",
    "dividends_yield",
    "dividend_payout_ratio_ttm",
    "gross_margin_ttm",
    "operating_margin_ttm",
    "net_margin_ttm",
    "return_on_assets_fq",
    "return_on_equity_fq",
    "return_on_invested_capital_fq",
    "debt_to_equity_fq",
    "current_ratio_fq",
    "quick_ratio_fq",
    "total_revenue_fq",
    "gross_profit_fq",
    "operating_income_fq",
    "net_income_fq",
    "ebitda_fq",
    "total_assets_fq",
    "total_current_assets_fq",
    "total_liabilities_fq",
    "total_current_liabilities_fq",
    "total_equity_fq",
    "cash_n_short_term_invest_fq",
    "cash_n_equivalents_fq",
    "total_debt_fq",
    "free_cash_flow_fq",
    "capital_expenditures_fq",
    "cash_f_operating_activities_fq",
    "cash_f_investing_activities_fq",
    "cash_f_financing_activities_fq",
    "enterprise_value_fq"
]

async def fetch_tradingview_fundamentals(symbol: str) -> Dict[str, Any]:
    """Fetch point-in-time fundamental metrics from TradingView scanner."""
    payload = {
        "filter": [{"left": "name", "operation": "equal", "right": symbol.upper()}],
        "options": {"active_symbols_only": True},
        "columns": TV_COLUMNS
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(SCANNER_URL, json=payload, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get("data") or len(data["data"]) == 0:
                logger.warning(f"No TradingView data found for symbol {symbol}")
                return {}
                
            matches = data["data"]
            best_match = matches[0]
            for match in matches:
                if match.get("s", "").startswith("NSE:"):
                    best_match = match
                    break
                    
            raw_values = best_match.get("d", [])
            
            result = {}
            for i, col in enumerate(TV_COLUMNS):
                if i < len(raw_values):
                    result[col] = raw_values[i]
                    
            return result
            
        except Exception as e:
            logger.error(f"Failed to fetch TradingView fundamentals for {symbol}: {e}")
            return {}
