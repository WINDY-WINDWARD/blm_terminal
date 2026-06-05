"""Portfolio optimization router.

Uses PyPortfolioOpt for mean-variance and hierarchical risk parity optimization.
Historical price data is fetched from the local ticker_daily warehouse.
If data is insufficient, an NSE backfill is triggered automatically.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import ticker_warehouse
from app.services.cache import nse_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _period_to_dates(period: str) -> tuple[date, date]:
    """Map '1y'|'2y'|'3y' to (from_date, to_date)."""
    to_date = date.today()
    mapping = {"1y": 365, "2y": 730, "3y": 1095}
    days = mapping.get(period, 730)
    from_date = to_date - timedelta(days=days + 30)  # +30 buffer for backfill
    return from_date, to_date


def _expected_trading_days(period: str) -> int:
    """Approximate trading days for the period (≈ 250 per year)."""
    mapping = {"1y": 250, "2y": 500, "3y": 750}
    return mapping.get(period, 500)


def _fetch_prices_from_db(symbols: list[str], from_date: date, to_date: date) -> pd.DataFrame:
    """Build a close-price DataFrame from ticker_daily. Returns DataFrame indexed by date."""
    all_data: dict[str, pd.Series] = {}

    for sym in symbols:
        candles = ticker_warehouse.get_ohlcv(sym, from_date, to_date)
        if not candles:
            continue
        df_sym = pd.DataFrame(candles)
        df_sym["date"] = pd.to_datetime(df_sym["date"])
        df_sym = df_sym.set_index("date").sort_index()
        all_data[sym] = df_sym["close"]

    if not all_data:
        return pd.DataFrame()

    prices = pd.DataFrame(all_data)
    return prices


def _ensure_prices(symbols: list[str], period: str) -> tuple[pd.DataFrame, list[str]]:
    """Fetch prices from DB, backfill if short, return (prices_df, failed_symbols)."""
    from_date, to_date = _period_to_dates(period)
    expected = _expected_trading_days(period)
    min_required = max(30, expected // 4)  # at least 30 days or 25% of expected

    # First pass: query DB
    prices = _fetch_prices_from_db(symbols, from_date, to_date)
    failed: list[str] = []

    # Identify symbols needing backfill
    need_backfill: list[str] = []
    for sym in symbols:
        if sym not in prices.columns:
            need_backfill.append(sym)
        else:
            count = prices[sym].notna().sum()
            if count < min_required:
                need_backfill.append(sym)

    # Trigger backfill for short symbols
    if need_backfill:
        backfill_days = {"1y": 400, "2y": 800, "3y": 1200}.get(period, 800)
        for sym in need_backfill:
            try:
                logger.info("portfolio: backfilling %s (%d days)", sym, backfill_days)
                rows = ticker_warehouse.backfill_symbol(sym, days=backfill_days)
                logger.info("portfolio: backfilled %s → %d rows", sym, rows)
            except Exception as exc:
                logger.warning("portfolio: backfill failed for %s: %s", sym, exc)

        # Re-query after backfill
        prices = _fetch_prices_from_db(symbols, from_date, to_date)

    # Final check: mark truly failed symbols
    for sym in symbols:
        if sym not in prices.columns:
            failed.append(sym)
        else:
            count = prices[sym].notna().sum()
            if count < 10:  # absolute minimum for any stats
                failed.append(sym)

    # Drop failed symbols
    valid_cols = [c for c in prices.columns if c not in failed]
    prices = prices[valid_cols].dropna(how="all")
    rows_before = len(prices)
    prices = prices.dropna(how="any")
    rows_after = len(prices)
    if rows_before > rows_after:
        logger.info(
            "portfolio: dropped %d/%d rows with any NaN after backfill "
            "(circuit breakers / trading halts / irregular listing dates)",
            rows_before - rows_after,
            rows_before,
        )

    return prices, failed


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PortfolioOptimizeRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=3, max_length=30, description="NSE symbols (no .NS suffix needed)")
    period: str = Field(default="2y", description="Lookback period: '1y', '2y', '3y'")
    objective: str = Field(default="max_sharpe", description="'max_sharpe' | 'min_volatility' | 'risk_parity'")
    risk_free_rate: float = Field(default=0.065, ge=0.0, le=0.15, description="Risk-free rate (decimal), default approx RBI repo rate")


class IndividualStats(BaseModel):
    annual_return: float
    annual_volatility: float
    sharpe: float


class PortfolioOptimizeResult(BaseModel):
    weights: dict[str, float]
    expected_annual_return: float
    expected_annual_volatility: float
    sharpe_ratio: float
    correlation_matrix: dict[str, dict[str, float]]
    individual_stats: dict[str, IndividualStats]
    period_used: str
    objective_used: str
    symbols_used: list[str]
    symbols_failed: list[str]
    computed_at: str


class WatchlistPreviewItem(BaseModel):
    symbol: str
    annual_return_1y: float | None
    annual_volatility_1y: float | None
    current_price: float | None


# ---------------------------------------------------------------------------
# Core computation (sync — run in thread pool)
# ---------------------------------------------------------------------------


def _run_optimization_sync(request: PortfolioOptimizeRequest) -> PortfolioOptimizeResult:
    from pypfopt import expected_returns, risk_models, EfficientFrontier, HRPOpt

    symbols = [s.upper() for s in request.symbols]
    prices, failed = _ensure_prices(symbols, request.period)

    valid_cols = list(prices.columns)

    if len(valid_cols) < 2:
        raise ValueError(f"Insufficient valid symbols ({len(valid_cols)}). Failed: {failed}")

    # Per-symbol stats
    daily_returns = prices.pct_change().dropna()
    individual_stats: dict[str, IndividualStats] = {}
    for sym in valid_cols:
        dr = daily_returns[sym].dropna()
        ann_ret = float((1 + dr.mean()) ** 252 - 1)
        ann_vol = float(dr.std() * np.sqrt(252))
        sharpe = (ann_ret - request.risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
        individual_stats[sym] = IndividualStats(
            annual_return=round(ann_ret, 4),
            annual_volatility=round(ann_vol, 4),
            sharpe=round(sharpe, 3),
        )

    # Correlation matrix
    corr = daily_returns.corr()
    corr_dict: dict[str, dict[str, float]] = {
        sym: {sym2: round(float(corr.loc[sym, sym2]), 3) for sym2 in valid_cols}
        for sym in valid_cols
    }

    # Optimization
    mu = expected_returns.mean_historical_return(prices)
    S = risk_models.sample_cov(prices)

    weights: dict[str, float] = {}
    exp_ret = 0.0
    exp_vol = 0.0
    sharpe_r = 0.0

    if request.objective == "risk_parity":
        hrp = HRPOpt(daily_returns)
        hrp.optimize()
        raw_weights = hrp.clean_weights()
        weights = {k: round(float(v), 4) for k, v in raw_weights.items() if v > 0.001}
        # Compute portfolio stats from weights
        w = np.array([weights.get(s, 0) for s in valid_cols])
        port_ret = float(mu.values @ w)
        port_vol = float(np.sqrt(w @ S.values @ w))
        exp_ret = round(port_ret, 4)
        exp_vol = round(port_vol, 4)
        sharpe_r = round((exp_ret - request.risk_free_rate) / exp_vol if exp_vol > 0 else 0, 3)
    else:
        ef = EfficientFrontier(mu, S, weight_bounds=(0, 1))
        try:
            if request.objective == "max_sharpe":
                ef.max_sharpe(risk_free_rate=request.risk_free_rate)
            else:  # min_volatility
                ef.min_volatility()

            raw_weights = ef.clean_weights()
            weights = {k: round(float(v), 4) for k, v in raw_weights.items() if v > 0.001}
            perf = ef.portfolio_performance(risk_free_rate=request.risk_free_rate)
            exp_ret = round(float(perf[0]), 4)
            exp_vol = round(float(perf[1]), 4)
            sharpe_r = round(float(perf[2]), 3)
        except ValueError as exc:
            # max_sharpe fails when no asset exceeds risk-free rate.
            # Fall back to equal-weight portfolio with computed stats.
            logger.warning("portfolio: %s failed (%s), falling back to equal weights", request.objective, exc)
            n = len(valid_cols)
            weights = {s: round(1.0 / n, 4) for s in valid_cols}
            w = np.array([weights[s] for s in valid_cols])
            exp_ret = round(float(mu.values @ w), 4)
            exp_vol = round(float(np.sqrt(w @ S.values @ w)), 4)
            sharpe_r = round((exp_ret - request.risk_free_rate) / exp_vol if exp_vol > 0 else 0, 3)

    return PortfolioOptimizeResult(
        weights=weights,
        expected_annual_return=exp_ret,
        expected_annual_volatility=exp_vol,
        sharpe_ratio=sharpe_r,
        correlation_matrix=corr_dict,
        individual_stats=individual_stats,
        period_used=request.period,
        objective_used=request.objective,
        symbols_used=valid_cols,
        symbols_failed=failed,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/optimize", response_model=PortfolioOptimizeResult)
async def optimize_portfolio(request: PortfolioOptimizeRequest) -> PortfolioOptimizeResult:
    """Run portfolio optimization on a list of NSE symbols."""
    symbols_key = ",".join(sorted(s.upper() for s in request.symbols))
    cache_key = f"{symbols_key}:{request.period}:{request.objective}:{request.risk_free_rate}"

    cached = nse_cache.get(cache_key)
    if cached:
        return cached  # type: ignore

    try:
        result = await asyncio.to_thread(_run_optimization_sync, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Portfolio optimization failed")
        raise HTTPException(status_code=502, detail=f"Optimization failed: {exc}")

    nse_cache[cache_key] = result
    return result


@router.get("/watchlist-preview", response_model=list[WatchlistPreviewItem])
async def watchlist_preview(symbols: str) -> list[WatchlistPreviewItem]:
    """Quick 1Y stats for a comma-separated list of NSE symbols (for the selection UI).

    Usage: GET /portfolio/watchlist-preview?symbols=RELIANCE,TCS,HDFCBANK
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=422, detail="No symbols provided")

    cache_key = "preview:" + ",".join(sorted(symbol_list))
    cached = nse_cache.get(cache_key)
    if cached:
        return cached  # type: ignore

    def _fetch():
        from_date = date.today() - timedelta(days=395)
        to_date = date.today()

        results = []
        for sym in symbol_list:
            candles = ticker_warehouse.get_ohlcv(sym, from_date, to_date)
            if not candles:
                # Try backfill
                try:
                    ticker_warehouse.backfill_symbol(sym, days=400)
                    candles = ticker_warehouse.get_ohlcv(sym, from_date, to_date)
                except Exception:
                    pass

            if not candles:
                results.append(WatchlistPreviewItem(symbol=sym, annual_return_1y=None, annual_volatility_1y=None, current_price=None))
                continue

            df = pd.DataFrame(candles)
            df = df.sort_values("date")
            closes = df["close"].astype(float)
            if len(closes) < 5:
                results.append(WatchlistPreviewItem(symbol=sym, annual_return_1y=None, annual_volatility_1y=None, current_price=None))
                continue

            dr = closes.pct_change().dropna()
            ann_ret = float((1 + dr.mean()) ** 252 - 1)
            ann_vol = float(dr.std() * np.sqrt(252))
            results.append(WatchlistPreviewItem(
                symbol=sym,
                annual_return_1y=round(ann_ret * 100, 2),
                annual_volatility_1y=round(ann_vol * 100, 2),
                current_price=round(float(closes.iloc[-1]), 2),
            ))
        return results

    try:
        result = await asyncio.to_thread(_fetch)
    except Exception as exc:
        logger.exception("Portfolio preview failed")
        raise HTTPException(status_code=502, detail=str(exc))

    nse_cache[cache_key] = result
    return result
