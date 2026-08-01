"""Multi-period returns calculations with date-based lookups."""

from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import select

from app.models.ticker import TickerDaily
from app.models.stockuniverse import StockUniverse
from app.database import _SyncSessionLocal


TRADING_DAYS = {
    "1d": 1,
    "1w": 5,
    "1m": 20,
    "3m": 60,
    "6m": 120,
    "1y": 252,
}


def get_returns(symbol: str, target_date: Optional[date] = None) -> dict:
    """
    Calculate multi-period returns for a symbol.

    Args:
        symbol: NSE ticker symbol
        target_date: End date for calculations (default: today)

    Returns:
        Dict with 1d, 1w, 1m, 3m, 6m, 1y percentage returns and latest_date
    """
    if target_date is None:
        target_date = date.today()

    with _SyncSessionLocal() as db:
        stmt = (
            select(TickerDaily)
            .where(TickerDaily.symbol == symbol)
            .order_by(TickerDaily.date.desc())
            .limit(252)
        )
        rows = db.execute(stmt).scalars().all()

    if not rows:
        return {
            "symbol": symbol,
            "1d": None,
            "1w": None,
            "1m": None,
            "3m": None,
            "6m": None,
            "1y": None,
            "latest_date": None,
        }

    rows_sorted = sorted(rows, key=lambda r: r.date)
    df = pd.DataFrame([
        {"date": r.date, "close": r.close, "open": r.open, "high": r.high, "low": r.low, "volume": r.volume}
        for r in rows_sorted
    ])

    latest_date = rows_sorted[-1].date

    def get_return_for_period(days: int) -> Optional[float]:
        if len(df) < days + 1:
            return None
        target_idx = len(df) - 1
        start_idx = target_idx - days
        if start_idx < 0:
            return None
        start_price = df.iloc[start_idx]["close"]
        end_price = df.iloc[target_idx]["close"]
        if start_price is None or end_price is None or start_price == 0:
            return None
        return ((end_price - start_price) / start_price) * 100

    return {
        "symbol": symbol,
        "1d": get_return_for_period(1),
        "1w": get_return_for_period(TRADING_DAYS["1w"]),
        "1m": get_return_for_period(TRADING_DAYS["1m"]),
        "3m": get_return_for_period(TRADING_DAYS["3m"]),
        "6m": get_return_for_period(TRADING_DAYS["6m"]),
        "1y": get_return_for_period(TRADING_DAYS["1y"]),
        "latest_date": latest_date,
    }


def get_returns_bulk(symbols: list[str]) -> list[dict]:
    """Get returns for multiple symbols."""
    return [get_returns(symbol) for symbol in symbols]


def get_universe_returns(
    period: str = "1m",
    sort_by: str = "return",
    order: str = "desc",
    limit: int = 50,
) -> list[dict]:
    """
    Get returns for all symbols in universe, sorted and limited.

    Args:
        period: Return period (1d, 1w, 1m, 3m, 6m, 1y)
        sort_by: Field to sort by
        order: asc or desc
        limit: Max results to return
    """
    days = TRADING_DAYS.get(period)
    if not days:
        days = TRADING_DAYS["1m"]

    with _SyncSessionLocal() as db:
        symbols_stmt = select(TickerDaily.symbol).distinct()
        symbols = [s for s in db.execute(symbols_stmt).scalars().all()]

    results = []
    for symbol in symbols:
        ret = get_returns(symbol)
        ret_val = ret.get(period)
        if ret_val is not None:
            results.append({
                "symbol": symbol,
                "return": ret_val,
                "latest_date": ret["latest_date"],
            })

    results.sort(key=lambda x: x.get("return", 0) or 0, reverse=(order == "desc"))

    return results[:limit]


def get_sector_returns(period: str = "1m") -> list[dict]:
    """
    Calculate average and median returns by sector.

    Args:
        period: Return period (1d, 1w, 1m, 3m, 6m, 1y)
    """
    from app.models.stockuniverse import StockUniverse
    import json

    days = TRADING_DAYS.get(period)
    if not days:
        days = TRADING_DAYS["1m"]

    with _SyncSessionLocal() as db:
        stmt = select(StockUniverse.symbol, StockUniverse.industry_info)
        rows = db.execute(stmt).fetchall()

    symbol_sector = {}
    for row in rows:
        symbol, industry_info = row
        if industry_info:
            try:
                info = json.loads(industry_info) if isinstance(industry_info, str) else industry_info
                sector = info.get("sector", "Unknown")
            except (json.JSONDecodeError, TypeError):
                sector = "Unknown"
        else:
            sector = "Unknown"
        symbol_sector[symbol] = sector

    sector_data: dict[str, list[float]] = {}
    for symbol in symbol_sector:
        ret = get_returns(symbol)
        ret_val = ret.get(period)
        if ret_val is not None:
            sector = symbol_sector[symbol]
            if sector not in sector_data:
                sector_data[sector] = []
            sector_data[sector].append(ret_val)

    results = []
    for sector, returns in sector_data.items():
        if returns:
            results.append({
                "sector": sector,
                "avg_return": sum(returns) / len(returns),
                "median_return": sorted(returns)[len(returns) // 2] if returns else 0,
                "count": len(returns),
            })

    results.sort(key=lambda x: x["avg_return"], reverse=True)
    return results


def get_52w_position(symbol: str) -> dict:
    """
    Get 52-week high/low position for a symbol using pre-calculated data from stock_universe.

    Returns:
        Dict with high_52w, low_52w, high_52w_date, low_52w_date, current_close, 
        pct_from_52w_high, pct_from_52w_low, is_52w_high, is_52w_low
    """
    with _SyncSessionLocal() as db:
        stock = db.get(StockUniverse, symbol.upper())
        
        if not stock:
            return {
                "symbol": symbol.upper(),
                "high_52w": None,
                "low_52w": None,
                "high_52w_date": None,
                "low_52w_date": None,
                "current_close": None,
                "pct_from_52w_high": None,
                "pct_from_52w_low": None,
                "is_52w_high": False,
                "is_52w_low": False,
            }
        
        high_52w = stock.high_52w
        low_52w = stock.low_52w
        high_52w_date = stock.high_52w_date
        low_52w_date = stock.low_52w_date
        
        stmt = (
            select(TickerDaily.close)
            .where(TickerDaily.symbol == symbol.upper())
            .order_by(TickerDaily.date.desc())
            .limit(1)
        )
        row = db.execute(stmt).scalar_one_or_none()
        current_close = row
    
    if current_close is None:
        return {
            "symbol": symbol.upper(),
            "high_52w": high_52w,
            "low_52w": low_52w,
            "high_52w_date": high_52w_date,
            "low_52w_date": low_52w_date,
            "current_close": None,
            "pct_from_52w_high": None,
            "pct_from_52w_low": None,
            "is_52w_high": False,
            "is_52w_low": False,
        }
    
    pct_from_high = ((current_close - high_52w) / high_52w) * 100 if high_52w else None
    pct_from_low = ((current_close - low_52w) / low_52w) * 100 if low_52w else None

    return {
        "symbol": symbol.upper(),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "high_52w_date": high_52w_date,
        "low_52w_date": low_52w_date,
        "current_close": current_close,
        "pct_from_52w_high": round(pct_from_high, 2) if pct_from_high else None,
        "pct_from_52w_low": round(pct_from_low, 2) if pct_from_low else None,
        "is_52w_high": current_close >= high_52w if high_52w else False,
        "is_52w_low": current_close <= low_52w if low_52w else False,
    }


def get_streak_tracking(symbol: str) -> dict:
    """
    Calculate streak metrics for a symbol.

    Returns:
        Dict with consecutive_up_days, consecutive_down_days, consecutive_volume_up_days,
        days_since_52w_high (from stock_universe)
    """
    with _SyncSessionLocal() as db:
        stock = db.get(StockUniverse, symbol.upper())
        high_52w_date = stock.high_52w_date if stock else None
        
        stmt = (
            select(TickerDaily)
            .where(TickerDaily.symbol == symbol.upper())
            .order_by(TickerDaily.date.desc())
            .limit(252)
        )
        rows = list(db.execute(stmt).scalars().all())

    if not rows:
        return {
            "symbol": symbol.upper(),
            "consecutive_up_days": 0,
            "consecutive_down_days": 0,
            "consecutive_volume_up_days": 0,
            "days_since_52w_high": None,
        }

    rows_sorted = sorted(rows, key=lambda r: r.date)
    closes = [r.close for r in rows_sorted if r.close is not None]
    volumes = [r.volume for r in rows_sorted if r.volume is not None]

    if len(closes) < 2 or len(volumes) < 21:
        return {
            "symbol": symbol.upper(),
            "consecutive_up_days": 0,
            "consecutive_down_days": 0,
            "consecutive_volume_up_days": 0,
            "days_since_52w_high": None,
        }

    up_days = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            up_days += 1
        else:
            break

    down_days = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            down_days += 1
        else:
            break

    avg_vol_20 = sum(volumes[-21:-1]) / 20
    volume_up_days = 0
    for i in range(len(volumes) - 1, 0, -1):
        if volumes[i] > avg_vol_20:
            volume_up_days += 1
        else:
            break

    days_since_52w_high = None
    if high_52w_date:
        today = rows_sorted[-1].date
        days_since_52w_high = (today - high_52w_date).days

    return {
        "symbol": symbol.upper(),
        "consecutive_up_days": up_days,
        "consecutive_down_days": down_days,
        "consecutive_volume_up_days": volume_up_days,
        "days_since_52w_high": days_since_52w_high,
    }