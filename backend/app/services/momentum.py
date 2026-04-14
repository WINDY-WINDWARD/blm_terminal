"""Momentum score calculation service."""

from typing import Optional
import pandas as pd
from sqlalchemy import select, func

from app.models.ticker import TickerDaily
from app.database import _SyncSessionLocal
from app.services import returns as returns_service


def _get_all_symbols_with_data() -> list[str]:
    """Get all symbols with at least 60 days of data."""
    with _SyncSessionLocal() as db:
        stmt = (
            select(TickerDaily.symbol, func.count(TickerDaily.id).label("cnt"))
            .group_by(TickerDaily.symbol)
            .having(func.count(TickerDaily.id) >= 60)
        )
        rows = db.execute(stmt).fetchall()
    return [r[0] for r in rows]


def _calculate_returns_for_symbols(symbols: list[str]) -> dict[str, dict]:
    """Calculate all return periods for a list of symbols."""
    return {symbol: returns_service.get_returns(symbol) for symbol in symbols}


def _calculate_volume_ratio(symbol: str, days: int = 20) -> Optional[float]:
    """Calculate today's volume / average volume over last N days."""
    with _SyncSessionLocal() as db:
        stmt = (
            select(TickerDaily)
            .where(TickerDaily.symbol == symbol)
            .order_by(TickerDaily.date.desc())
            .limit(days + 1)
        )
        rows = list(db.execute(stmt).scalars().all())
    
    if len(rows) < days + 1:
        return None
    
    rows = sorted(rows, key=lambda r: r.date)
    volumes = [r.volume for r in rows if r.volume is not None]
    
    if len(volumes) < days:
        return None
    
    current_vol = volumes[-1]
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1])
    
    if avg_vol == 0:
        return None
    
    return current_vol / avg_vol


def _percentile_rank(value: float, all_values: list[float]) -> float:
    """Calculate percentile rank (0-100) of a value in a list."""
    if not all_values:
        return 50.0
    sorted_vals = sorted(all_values)
    rank = sum(1 for v in sorted_vals if v < value)
    return (rank / len(sorted_vals)) * 100


def get_momentum_score(symbol: str) -> dict:
    """
    Calculate composite momentum score for a symbol.

    Returns:
        Dict with score (0-100), component scores, and rank
    """
    symbols = _get_all_symbols_with_data()
    universe_size = len(symbols)
    
    if symbol.upper() not in symbols:
        return {
            "symbol": symbol.upper(),
            "score": None,
            "rank": None,
            "universe_size": universe_size,
            "reason": "Insufficient data (< 60 days)",
        }
    
    all_returns = _calculate_returns_for_symbols(symbols)
    
    returns_3m = {s: all_returns[s].get("3m") for s in symbols}
    returns_6m = {s: all_returns[s].get("6m") for s in symbols}
    volume_ratios = {}
    for s in symbols:
        vr = _calculate_volume_ratio(s)
        volume_ratios[s] = vr
    
    valid_3m = {s: v for s, v in returns_3m.items() if v is not None}
    valid_6m = {s: v for s, v in returns_6m.items() if v is not None}
    valid_vol = {s: v for s, v in volume_ratios.items() if v is not None}
    
    if not valid_3m or not valid_6m:
        return {
            "symbol": symbol.upper(),
            "score": None,
            "rank": None,
            "universe_size": universe_size,
            "reason": "Insufficient return data",
        }
    
    values_3m = list(valid_3m.values())
    values_6m = list(valid_6m.values())
    values_vol = list(valid_vol.values())
    
    symbol_3m = returns_3m.get(symbol.upper())
    symbol_6m = returns_6m.get(symbol.upper())
    symbol_vol = volume_ratios.get(symbol.upper())
    
    rank_3m = _percentile_rank(symbol_3m, values_3m) if symbol_3m is not None else 50
    rank_6m = _percentile_rank(symbol_6m, values_6m) if symbol_6m is not None else 50
    rank_vol = _percentile_rank(symbol_vol, values_vol) if symbol_vol is not None else 50
    
    score = (
        0.30 * rank_3m +
        0.30 * rank_6m +
        0.20 * rank_vol
    )
    
    all_scores = []
    for s in symbols:
        s_3m = returns_3m.get(s)
        s_6m = returns_6m.get(s)
        s_vol = volume_ratios.get(s)
        if s_3m is not None and s_6m is not None:
            s_rank_3m = _percentile_rank(s_3m, values_3m)
            s_rank_6m = _percentile_rank(s_6m, values_6m)
            s_rank_vol = _percentile_rank(s_vol, values_vol) if s_vol is not None else 50
            s_score = 0.30 * s_rank_3m + 0.30 * s_rank_6m + 0.20 * s_rank_vol
            all_scores.append((s, s_score))
    
    all_scores.sort(key=lambda x: x[1], reverse=True)
    rank = None
    for i, (s, _) in enumerate(all_scores):
        if s == symbol.upper():
            rank = i + 1
            break
    
    return {
        "symbol": symbol.upper(),
        "score": round(score, 1),
        "rank": rank,
        "universe_size": universe_size,
        "components": {
            "rank_3m_return": round(rank_3m, 1),
            "rank_6m_return": round(rank_6m, 1),
            "rank_volume_ratio": round(rank_vol, 1),
        },
    }


def get_momentum_leaderboard(limit: int = 50) -> list[dict]:
    """
    Get top N symbols by momentum score.

    Args:
        limit: Max number of results (default 50)

    Returns:
        List of dicts with symbol, score, rank
    """
    symbols = _get_all_symbols_with_data()
    universe_size = len(symbols)
    
    all_returns = _calculate_returns_for_symbols(symbols)
    
    volume_ratios = {}
    for s in symbols:
        vr = _calculate_volume_ratio(s)
        volume_ratios[s] = vr
    
    values_3m = [v for v in (all_returns[s].get("3m") for s in symbols) if v is not None]
    values_6m = [v for v in (all_returns[s].get("6m") for s in symbols) if v is not None]
    values_vol = [v for v in volume_ratios.values() if v is not None]
    
    scores = []
    for s in symbols:
        s_3m = all_returns[s].get("3m")
        s_6m = all_returns[s].get("6m")
        s_vol = volume_ratios.get(s)
        
        if s_3m is None or s_6m is None:
            continue
        
        rank_3m = _percentile_rank(s_3m, values_3m)
        rank_6m = _percentile_rank(s_6m, values_6m)
        rank_vol = _percentile_rank(s_vol, values_vol) if s_vol is not None else 50
        
        score = 0.30 * rank_3m + 0.30 * rank_6m + 0.20 * rank_vol
        scores.append({
            "symbol": s,
            "score": round(score, 1),
            "rank_3m": round(rank_3m, 1),
            "rank_6m": round(rank_6m, 1),
            "rank_volume": round(rank_vol, 1),
        })
    
    scores.sort(key=lambda x: x["score"], reverse=True)
    
    results = []
    for i, item in enumerate(scores[:limit]):
        results.append({
            "rank": i + 1,
            "symbol": item["symbol"],
            "score": item["score"],
        })
    
    return results