"""Valuation models router — Graham Number, DCF, DDM, EV/EBITDA, PEG.

Data strategy: screener.in primary, yfinance fallback.
- Screener provides most fields (eps, book_value, dividend_yield, growth rates,
  pre-computed Graham number, EV/EBITDA ratio, EBITDA, debt, market cap).
- yfinance is called only for fields screener lacks (FCF, forward EPS, shares
  outstanding, total cash) or when screener session is unavailable.
Results are cached for 30 minutes.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.cache import nse_cache
from app.services.screener_client import screener_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/valuation", tags=["valuation"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class DcfAssumptions(BaseModel):
    base_fcf_cr: float | None       # Base FCF in Crores INR
    stage1_growth_pct: float        # % e.g. 12.5
    stage2_growth_pct: float        # % e.g. 6.25
    terminal_growth_pct: float      # % e.g. 5.0
    wacc_pct: float                 # % e.g. 12.0
    projection_years: int = 10


class ValuationResult(BaseModel):
    symbol: str
    cmp: float | None
    currency: str = "INR"

    graham_number: float | None = None
    graham_upside_pct: float | None = None

    dcf_value: float | None = None
    dcf_upside_pct: float | None = None
    dcf_assumptions: DcfAssumptions | None = None

    ddm_value: float | None = None
    ddm_upside_pct: float | None = None

    ev_ebitda_value: float | None = None
    ev_ebitda_upside_pct: float | None = None

    peg_value: float | None = None
    peg_upside_pct: float | None = None

    data_source: str = "screener+yfinance"
    fetched_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upside(fair: float, cmp: float) -> float | None:
    if fair is None or cmp is None or cmp == 0:
        return None
    return round((fair - cmp) / cmp * 100, 2)


def _graham_number(eps: float | None, book_value: float | None) -> float | None:
    """Benjamin Graham formula: √(22.5 × EPS × Book Value Per Share)."""
    if eps is None or book_value is None or eps <= 0 or book_value <= 0:
        return None
    return round(math.sqrt(22.5 * eps * book_value), 2)


def _dcf_value(
    fcf_annual: float | None,    # in INR (not Cr) per share
    stage1_g: float,             # decimal e.g. 0.125
    wacc: float,                 # decimal e.g. 0.12
    terminal_g: float,           # decimal e.g. 0.05
    years: int = 10,
) -> float | None:
    """Simplified 2-stage DCF returning intrinsic value per share."""
    if fcf_annual is None or fcf_annual <= 0:
        return None
    if wacc <= terminal_g:
        return None  # Gordon Growth Model breaks down

    stage2_g = stage1_g / 2
    pv = 0.0
    fcf = fcf_annual
    for t in range(1, years + 1):
        g = stage1_g if t <= 5 else stage2_g
        fcf = fcf * (1 + g)
        pv += fcf / (1 + wacc) ** t

    # Terminal value at year 10
    terminal_fcf = fcf * (1 + terminal_g)
    terminal_value = terminal_fcf / (wacc - terminal_g)
    pv += terminal_value / (1 + wacc) ** years

    return round(pv, 2)


def _ddm_value(
    dividend: float | None,       # annual dividend per share
    growth: float,                # decimal growth rate
    discount_rate: float,         # decimal discount rate
) -> float | None:
    """Gordon Growth DDM."""
    if dividend is None or dividend <= 0:
        return None
    effective_growth = min(growth, 0.15)  # cap at 15%
    if discount_rate <= effective_growth:
        return None
    return round(dividend * (1 + effective_growth) / (discount_rate - effective_growth), 2)


def _parse_screener_num(val: str | None) -> float | None:
    """Strip Cr, %, ₹, commas from screener strings and return float."""
    if not val:
        return None
    cleaned = val.replace("₹", "").replace(",", "").replace("%", "").replace("Cr.", "").replace("Cr", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Data fetching: screener-first, yfinance fallback
# ---------------------------------------------------------------------------


def _fetch_yfinance(symbol: str) -> dict:
    """Fetch yfinance info synchronously. Run via asyncio.to_thread."""
    import yfinance as yf
    ticker = yf.Ticker(f"{symbol}.NS")
    info = ticker.info or {}

    # Free cash flow from cashflow statement
    fcf_per_share = None
    try:
        cf = ticker.cashflow
        if cf is not None and not cf.empty:
            ocf_row = cf.loc["Operating Cash Flow"] if "Operating Cash Flow" in cf.index else None
            capex_row = cf.loc["Capital Expenditure"] if "Capital Expenditure" in cf.index else None
            if ocf_row is not None and capex_row is not None:
                ocf = float(ocf_row.iloc[0])
                capex = float(capex_row.iloc[0])  # capex is negative in yfinance
                fcf_total = ocf + capex           # capex already negative, so this is OCF - abs(capex)
                shares = info.get("sharesOutstanding")
                if shares and shares > 0:
                    fcf_per_share = fcf_total / shares
    except Exception:
        pass

    return {
        "info": info,
        "fcf_per_share": fcf_per_share,
    }


async def _fetch_valuation_data(symbol: str) -> dict:
    """Fetch valuation inputs: screener first, yfinance fallback.

    Returns a dict with all raw fields needed for the 5 models.
    """
    symbol = symbol.upper()
    result: dict[str, Any] = {
        "cmp": None,
        "eps": None,
        "book_value": None,
        "dividend_rate": None,
        "dividend_yield": None,
        "earnings_growth": None,
        "revenue_growth": None,
        "forward_eps": None,
        "shares_outstanding": None,
        "ebitda": None,
        "total_debt": None,
        "total_cash": None,
        "fcf_per_share": None,
        "graham_precomputed": None,
        "evebitda_ratio": None,
        "source": "screener",
    }

    # ── Step 1: Try screener.in ────────────────────────────────────────────
    screener_ok = False
    try:
        await screener_client.init()
        screener_data = await screener_client.get_company(symbol)
        screener_ok = True
        ratios = screener_data.get("ratios", {})

        # CMP
        result["cmp"] = _parse_screener_num(ratios.get("price")) or _parse_screener_num(ratios.get("current_price"))

        # EPS (screener provides as plain number, e.g. "59.7")
        result["eps"] = _parse_screener_num(ratios.get("eps"))

        # Book Value
        result["book_value"] = _parse_screener_num(ratios.get("book_value"))

        # Dividend
        result["dividend_yield"] = _parse_screener_num(ratios.get("dividend_yield"))

        # Growth rates (screener provides as %, e.g. "17.5%")
        result["earnings_growth"] = _parse_screener_num(ratios.get("profit_growth"))
        if result["earnings_growth"] is not None:
            result["earnings_growth"] = result["earnings_growth"] / 100
        result["revenue_growth"] = _parse_screener_num(ratios.get("sales_growth"))
        if result["revenue_growth"] is not None:
            result["revenue_growth"] = result["revenue_growth"] / 100

        # Pre-computed Graham number
        result["graham_precomputed"] = _parse_screener_num(ratios.get("graham"))

        # EV/EBITDA ratio
        result["evebitda_ratio"] = _parse_screener_num(ratios.get("evebitda"))

        # EBITDA = EBIT + Depreciation
        ebit = _parse_screener_num(ratios.get("ebit"))
        dep = _parse_screener_num(ratios.get("dep_ann"))
        if ebit is not None and dep is not None:
            result["ebitda"] = (ebit + dep) * 1e7  # Convert Cr to INR

        # Debt
        result["total_debt"] = _parse_screener_num(ratios.get("debt"))
        if result["total_debt"] is not None:
            result["total_debt"] = result["total_debt"] * 1e7  # Convert Cr to INR

        # Market cap → shares outstanding = MktCap / Price
        mkt_cap = _parse_screener_num(ratios.get("market_cap"))
        if mkt_cap is not None and result["cmp"] and result["cmp"] > 0:
            result["shares_outstanding"] = (mkt_cap * 1e7) / result["cmp"]

        logger.info("valuation: screener data for %s — CMP=%s eps=%s bv=%s",
                    symbol, result["cmp"], result["eps"], result["book_value"])

    except Exception as exc:
        logger.warning("valuation: screener failed for %s: %s", symbol, exc)

    # ── Step 2: yfinance fallback for ALL fields ────────────────────────────
    # Always call yfinance to ensure we have the richest dataset.
    # Any field already populated by screener is kept; yfinance fills gaps.
    try:
        yf_data = await asyncio.to_thread(_fetch_yfinance, symbol)
        info = yf_data["info"]
        result["source"] = "screener+yfinance" if screener_ok else "yfinance"

        def _yf(field: str) -> Any:
            return info.get(field)

        # CMP
        if result["cmp"] is None:
            result["cmp"] = _yf("currentPrice") or _yf("regularMarketPrice")

        # EPS
        if result["eps"] is None:
            result["eps"] = _yf("epsTrailingTwelveMonths")

        # Book Value
        if result["book_value"] is None:
            result["book_value"] = _yf("bookValue")

        # Dividend
        if result["dividend_rate"] is None:
            result["dividend_rate"] = _yf("dividendRate")
        if result["dividend_yield"] is None:
            dy = _yf("dividendYield")
            if dy:
                result["dividend_yield"] = dy * 100  # yfinance returns decimal

        # Growth
        if result["earnings_growth"] is None:
            result["earnings_growth"] = _yf("earningsGrowth")
        if result["revenue_growth"] is None:
            result["revenue_growth"] = _yf("revenueGrowth")

        # Forward EPS
        if result["forward_eps"] is None:
            result["forward_eps"] = _yf("forwardEps")

        # Shares outstanding
        if result["shares_outstanding"] is None:
            result["shares_outstanding"] = _yf("sharesOutstanding")

        # EBITDA
        if result["ebitda"] is None:
            result["ebitda"] = _yf("ebitda")

        # Debt / Cash
        if result["total_debt"] is None:
            result["total_debt"] = _yf("totalDebt")
        if result["total_cash"] is None:
            result["total_cash"] = _yf("totalCash")

        # FCF per share (yfinance only source)
        if result["fcf_per_share"] is None:
            result["fcf_per_share"] = yf_data.get("fcf_per_share")

        logger.info("valuation: yfinance data for %s — CMP=%s eps=%s fcf=%s",
                    symbol, result["cmp"], result["eps"], result["fcf_per_share"])

    except Exception as exc:
        logger.warning("valuation: yfinance failed for %s: %s", symbol, exc)
        if not screener_ok:
            raise HTTPException(status_code=502, detail=f"Both screener and yfinance failed for {symbol}: {exc}")

    return result


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/{symbol}", response_model=ValuationResult)
async def get_valuation(
    symbol: str,
    wacc: float = Query(default=0.12, ge=0.05, le=0.30, description="Weighted avg cost of capital (decimal, e.g. 0.12)"),
    terminal_growth: float = Query(default=0.05, ge=0.02, le=0.10, description="Terminal growth rate (decimal)"),
    stage1_growth: float | None = Query(default=None, description="Override stage 1 DCF growth. Auto-computed if omitted."),
) -> ValuationResult:
    """Return intrinsic value estimates for an NSE stock using multiple valuation models."""
    symbol = symbol.upper()
    cache_key = f"{symbol}:{wacc}:{terminal_growth}:{stage1_growth}"

    cached = nse_cache.get(cache_key)
    if cached:
        return cached

    data = await _fetch_valuation_data(symbol)

    cmp: float | None = data["cmp"]
    eps: float | None = data["eps"]
    book_value: float | None = data["book_value"]
    dividend_rate: float | None = data["dividend_rate"]
    dividend_yield_pct: float | None = data["dividend_yield"]
    earnings_growth: float | None = data["earnings_growth"]
    revenue_growth: float | None = data["revenue_growth"]
    forward_eps: float | None = data["forward_eps"]
    shares_outstanding: float | None = data["shares_outstanding"]
    ebitda: float | None = data["ebitda"]
    total_debt: float | None = data["total_debt"]
    total_cash: float | None = data["total_cash"]
    fcf_per_share: float | None = data["fcf_per_share"]
    graham_precomputed: float | None = data["graham_precomputed"]
    evebitda_ratio: float | None = data["evebitda_ratio"]
    source: str = data["source"]

    # Derive dividend rate from yield if missing
    if dividend_rate is None and dividend_yield_pct is not None and cmp and cmp > 0:
        dividend_rate = round(dividend_yield_pct / 100 * cmp, 2)

    # Graham Number — prefer screener pre-computed, else compute
    graham = graham_precomputed if graham_precomputed is not None else _graham_number(eps, book_value)

    # DCF
    if stage1_growth is None:
        raw_g = revenue_growth if revenue_growth is not None else (earnings_growth or 0.10)
        auto_g = max(0.05, min(0.25, raw_g))
    else:
        auto_g = max(0.01, min(0.30, stage1_growth))

    dcf = _dcf_value(
        fcf_annual=fcf_per_share,
        stage1_g=auto_g,
        wacc=wacc,
        terminal_g=terminal_growth,
    )
    dcf_assumptions = DcfAssumptions(
        base_fcf_cr=round(fcf_per_share * (shares_outstanding or 0) / 1e7, 2) if fcf_per_share and shares_outstanding else None,
        stage1_growth_pct=round(auto_g * 100, 2),
        stage2_growth_pct=round(auto_g / 2 * 100, 2),
        terminal_growth_pct=round(terminal_growth * 100, 2),
        wacc_pct=round(wacc * 100, 2),
    )

    # DDM
    effective_eg = earnings_growth if earnings_growth is not None else 0.10
    ddm = _ddm_value(dividend=dividend_rate, growth=effective_eg, discount_rate=wacc)

    # EV/EBITDA implied price
    ev_ebitda_value = None
    if evebitda_ratio is not None and ebitda is not None and ebitda > 0 and shares_outstanding and shares_outstanding > 0:
        # screener provides evebitda as a ratio; use it directly
        implied_ev = evebitda_ratio * (ebitda / 1e7)  # ebitda back to Cr for ratio consistency
        net_debt = (total_debt or 0) - (total_cash or 0)
        implied_equity = (implied_ev * 1e7) - net_debt  # Convert Cr to INR
        if implied_equity > 0:
            ev_ebitda_value = round(implied_equity / shares_outstanding, 2)
    elif ebitda and shares_outstanding and ebitda > 0:
        # Fallback: use 12x median if no screener ratio
        NSE_MEDIAN_EV_EBITDA = 12.0
        implied_ev = NSE_MEDIAN_EV_EBITDA * ebitda
        net_debt = (total_debt or 0) - (total_cash or 0)
        implied_equity = implied_ev - net_debt
        if implied_equity > 0 and shares_outstanding > 0:
            ev_ebitda_value = round(implied_equity / shares_outstanding, 2)

    # PEG Fair Value: Forward EPS × EPS growth rate (as P/E = growth rule)
    peg_value = None
    if forward_eps and earnings_growth and earnings_growth > 0:
        lynch_pe = earnings_growth * 100  # growth rate as P/E (Lynch rule)
        peg_value = round(forward_eps * lynch_pe, 2)
    elif eps and earnings_growth and earnings_growth > 0:
        # Fallback: use TTM EPS if forward not available
        lynch_pe = earnings_growth * 100
        peg_value = round(eps * lynch_pe, 2)

    result = ValuationResult(
        symbol=symbol,
        cmp=cmp,
        graham_number=graham,
        graham_upside_pct=_upside(graham, cmp) if cmp else None,
        dcf_value=dcf,
        dcf_upside_pct=_upside(dcf, cmp) if cmp else None,
        dcf_assumptions=dcf_assumptions,
        ddm_value=ddm,
        ddm_upside_pct=_upside(ddm, cmp) if cmp else None,
        ev_ebitda_value=ev_ebitda_value,
        ev_ebitda_upside_pct=_upside(ev_ebitda_value, cmp) if cmp else None,
        peg_value=peg_value,
        peg_upside_pct=_upside(peg_value, cmp) if cmp else None,
        data_source=source,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )

    nse_cache[cache_key] = result
    return result
