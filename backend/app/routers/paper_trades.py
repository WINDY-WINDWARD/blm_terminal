"""FastAPI router for paper trading dummy positions with technical/fundamental enrichment."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.paper_trade import PaperTrade, PaperTradeLeg
from app.models.ticker import TickerScreenerSnapshot
from app.models.stockuniverse import StockUniverse

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class PaperTradeLegCreate(BaseModel):
    action: str = Field(..., description="'BUY' or 'SELL'")
    quantity: int = Field(..., gt=0, description="Quantity traded")
    price: float = Field(..., gt=0, description="Price per share")
    notes: Optional[str] = None


class PaperTradeLegUpdate(BaseModel):
    action: Optional[str] = None
    quantity: Optional[int] = Field(None, gt=0)
    price: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = None


class PaperTradeLegOut(BaseModel):
    id: int
    paper_trade_id: int
    action: str
    quantity: int
    price: float
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaperTradeCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)
    notes: Optional[str] = None


class PaperTradeOut(BaseModel):
    id: int
    symbol: str
    status: str
    created_at: datetime
    updated_at: datetime
    # Calculated position values
    total_buy_quantity: int
    total_sold_quantity: int
    remaining_quantity: int
    average_buy_price: float
    average_sell_price: Optional[float] = None
    realized_pnl: float
    legs: List[PaperTradeLegOut]
    # Enriched snapshot / fundamental fields
    company_name: Optional[str] = None
    pe: Optional[float] = None
    technical_state: str = "HOLD"  # 'VOLATILE', 'BUY', 'SELL', 'HOLD'
    last_close: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_technical_state(snapshot: Optional[TickerScreenerSnapshot]) -> tuple[Optional[float], str, Optional[float]]:
    """Determine PE, technical state (VOLATILE, BUY, SELL, HOLD), and last close.

    Rules:
    - High volatility: hv_20 > 40 or atr_percent_1d > 4.0 -> VOLATILE
    - Bullish momentum: macd_1d > macd_signal_1d and last_close > vwma_20_1d -> BUY
    - Bearish momentum: macd_1d < macd_signal_1d and last_close < vwma_20_1d -> SELL
    - Default: HOLD
    """
    if not snapshot:
        return None, "HOLD", None

    pe = snapshot.pe
    last_close = snapshot.last_close

    # Check volatility first
    is_volatile = False
    if snapshot.hv_20 is not None and snapshot.hv_20 > 40.0:
        is_volatile = True
    elif snapshot.atr_percent_1d is not None and snapshot.atr_percent_1d > 4.0:
        is_volatile = True

    if is_volatile:
        return pe, "VOLATILE", last_close

    # Trend / MACD check
    if snapshot.macd_1d is not None and snapshot.macd_signal_1d is not None:
        if snapshot.macd_1d > snapshot.macd_signal_1d:
            if snapshot.vwma_20_1d is None or (last_close is not None and last_close >= snapshot.vwma_20_1d):
                return pe, "BUY", last_close
        elif snapshot.macd_1d < snapshot.macd_signal_1d:
            if snapshot.vwma_20_1d is None or (last_close is not None and last_close <= snapshot.vwma_20_1d):
                return pe, "SELL", last_close

    return pe, "HOLD", last_close


def build_trade_out(
    trade: PaperTrade,
    snapshot: Optional[TickerScreenerSnapshot] = None,
    universe_stock: Optional[StockUniverse] = None,
) -> PaperTradeOut:
    legs = trade.legs or []
    buy_legs = [l for l in legs if l.action.upper() == "BUY"]
    sell_legs = [l for l in legs if l.action.upper() == "SELL"]

    total_buy_qty = sum(l.quantity for l in buy_legs)
    total_buy_val = sum(l.quantity * l.price for l in buy_legs)
    avg_buy_price = (total_buy_val / total_buy_qty) if total_buy_qty > 0 else 0.0

    total_sold_qty = sum(l.quantity for l in sell_legs)
    total_sell_val = sum(l.quantity * l.price for l in sell_legs)
    avg_sell_price = (total_sell_val / total_sold_qty) if total_sold_qty > 0 else None

    # Realized PnL = (avg_sell_price - avg_buy_price) * total_sold_qty
    realized_pnl = 0.0
    if total_sold_qty > 0 and avg_sell_price is not None:
        realized_pnl = (avg_sell_price - avg_buy_price) * total_sold_qty

    remaining_qty = max(0, total_buy_qty - total_sold_qty)

    pe, tech_state, last_close = compute_technical_state(snapshot)
    company_name = universe_stock.company_name if universe_stock else None

    # Fallback to universe_stock PE if snapshot doesn't have it
    if pe is None and universe_stock and universe_stock.symbol_pe:
        pe = universe_stock.symbol_pe

    return PaperTradeOut(
        id=trade.id,
        symbol=trade.symbol,
        status="CLOSED" if remaining_qty == 0 and total_buy_qty > 0 else trade.status,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
        total_buy_quantity=total_buy_qty,
        total_sold_quantity=total_sold_qty,
        remaining_quantity=remaining_qty,
        average_buy_price=round(avg_buy_price, 2),
        average_sell_price=round(avg_sell_price, 2) if avg_sell_price is not None else None,
        realized_pnl=round(realized_pnl, 2),
        legs=[PaperTradeLegOut.model_validate(l) for l in legs],
        company_name=company_name,
        pe=round(pe, 2) if pe is not None else None,
        technical_state=tech_state,
        last_close=round(last_close, 2) if last_close is not None else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=List[PaperTradeOut])
async def list_paper_trades(
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> List[PaperTradeOut]:
    """List all paper trade positions with enriched technical state and P/E."""
    q = select(PaperTrade).options(selectinload(PaperTrade.legs)).order_by(PaperTrade.created_at.desc())
    if status_filter:
        q = q.where(PaperTrade.status == status_filter.upper())

    res = await db.execute(q)
    trades = res.scalars().all()

    if not trades:
        return []

    symbols = list({t.symbol.upper() for t in trades})

    # Fetch snapshots
    snap_q = select(TickerScreenerSnapshot).where(TickerScreenerSnapshot.symbol.in_(symbols))
    snap_res = await db.execute(snap_q)
    snapshots = {s.symbol.upper(): s for s in snap_res.scalars().all()}

    # Fetch company names & PE from StockUniverse as fallback
    univ_q = select(StockUniverse).where(StockUniverse.symbol.in_(symbols))
    univ_res = await db.execute(univ_q)
    universe_stocks = {u.symbol.upper(): u for u in univ_res.scalars().all()}

    return [
        build_trade_out(
            t,
            snapshots.get(t.symbol.upper()),
            universe_stocks.get(t.symbol.upper()),
        )
        for t in trades
    ]


@router.post("", response_model=PaperTradeOut, status_code=status.HTTP_201_CREATED)
async def create_paper_trade(
    body: PaperTradeCreate,
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    """Create a new master paper trade position with the base BUY leg."""
    sym = body.symbol.strip().upper()
    trade = PaperTrade(
        symbol=sym,
        status="OPEN",
    )
    db.add(trade)
    await db.flush()  # populate trade.id

    base_leg = PaperTradeLeg(
        paper_trade_id=trade.id,
        action="BUY",
        quantity=body.quantity,
        price=body.price,
        notes=body.notes,
    )
    db.add(base_leg)
    await db.commit()

    # Re-query with relationship loaded
    q = select(PaperTrade).options(selectinload(PaperTrade.legs)).where(PaperTrade.id == trade.id)
    refreshed = (await db.execute(q)).scalar_one()

    # Enrich
    snap = (await db.execute(select(TickerScreenerSnapshot).where(TickerScreenerSnapshot.symbol == sym))).scalar_one_or_none()
    univ = (await db.execute(select(StockUniverse).where(StockUniverse.symbol == sym))).scalar_one_or_none()

    return build_trade_out(refreshed, snap, univ)


@router.post("/{trade_id}/legs", response_model=PaperTradeOut)
async def add_trade_leg(
    trade_id: int,
    body: PaperTradeLegCreate,
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    """Add a new leg to a position (e.g., BUY more to average up/down, or SELL to close/partial)."""
    q = select(PaperTrade).options(selectinload(PaperTrade.legs)).where(PaperTrade.id == trade_id)
    trade = (await db.execute(q)).scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Paper trade not found")

    action = body.action.strip().upper()
    if action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="Action must be BUY or SELL")

    # If action is SELL, ensure remaining quantity is sufficient
    buy_qty = sum(l.quantity for l in trade.legs if l.action.upper() == "BUY")
    sold_qty = sum(l.quantity for l in trade.legs if l.action.upper() == "SELL")
    remaining_qty = buy_qty - sold_qty

    if action == "SELL" and body.quantity > remaining_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot sell {body.quantity} shares. Only {remaining_qty} available.",
        )

    new_leg = PaperTradeLeg(
        paper_trade_id=trade.id,
        action=action,
        quantity=body.quantity,
        price=body.price,
        notes=body.notes,
    )
    db.add(new_leg)

    # Check if this sell completely closes the position
    if action == "SELL" and (sold_qty + body.quantity) >= buy_qty:
        trade.status = "CLOSED"
    elif action == "BUY" and trade.status == "CLOSED":
        trade.status = "OPEN"

    await db.commit()

    # Re-query with fresh session data
    refreshed_q = select(PaperTrade).options(selectinload(PaperTrade.legs)).execution_options(populate_existing=True).where(PaperTrade.id == trade_id)
    refreshed = (await db.execute(refreshed_q)).scalar_one()
    snap = (await db.execute(select(TickerScreenerSnapshot).where(TickerScreenerSnapshot.symbol == refreshed.symbol))).scalar_one_or_none()
    univ = (await db.execute(select(StockUniverse).where(StockUniverse.symbol == refreshed.symbol))).scalar_one_or_none()

    return build_trade_out(refreshed, snap, univ)


@router.put("/legs/{leg_id}", response_model=PaperTradeOut)
async def update_trade_leg(
    leg_id: int,
    body: PaperTradeLegUpdate,
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    """Edit an existing leg (change base order quantity/price or an addition's quantity/price)."""
    leg_q = select(PaperTradeLeg).where(PaperTradeLeg.id == leg_id)
    leg = (await db.execute(leg_q)).scalar_one_or_none()
    if not leg:
        raise HTTPException(status_code=404, detail="Trade leg not found")

    if body.action is not None:
        act = body.action.strip().upper()
        if act not in ("BUY", "SELL"):
            raise HTTPException(status_code=400, detail="Action must be BUY or SELL")
        leg.action = act

    if body.quantity is not None:
        leg.quantity = body.quantity
    if body.price is not None:
        leg.price = body.price
    if body.notes is not None:
        leg.notes = body.notes

    # Flush changes to verify quantities before final commit
    await db.flush()

    trade_q = select(PaperTrade).options(selectinload(PaperTrade.legs)).execution_options(populate_existing=True).where(PaperTrade.id == leg.paper_trade_id)
    trade = (await db.execute(trade_q)).scalar_one()

    buy_qty = sum(l.quantity for l in trade.legs if l.action.upper() == "BUY")
    sold_qty = sum(l.quantity for l in trade.legs if l.action.upper() == "SELL")

    if sold_qty > buy_qty:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Invalid update: Total sold quantity ({sold_qty}) exceeds total bought quantity ({buy_qty}).",
        )

    if sold_qty >= buy_qty and buy_qty > 0:
        trade.status = "CLOSED"
    else:
        trade.status = "OPEN"

    await db.commit()

    refreshed = (await db.execute(trade_q)).scalar_one()
    snap = (await db.execute(select(TickerScreenerSnapshot).where(TickerScreenerSnapshot.symbol == refreshed.symbol))).scalar_one_or_none()
    univ = (await db.execute(select(StockUniverse).where(StockUniverse.symbol == refreshed.symbol))).scalar_one_or_none()

    return build_trade_out(refreshed, snap, univ)


@router.delete("/legs/{leg_id}", response_model=PaperTradeOut)
async def delete_trade_leg(
    leg_id: int,
    db: AsyncSession = Depends(get_db),
) -> PaperTradeOut:
    """Delete an individual leg."""
    leg = (await db.execute(select(PaperTradeLeg).where(PaperTradeLeg.id == leg_id))).scalar_one_or_none()
    if not leg:
        raise HTTPException(status_code=404, detail="Trade leg not found")

    trade_id = leg.paper_trade_id
    await db.delete(leg)
    await db.flush()

    trade_q = select(PaperTrade).options(selectinload(PaperTrade.legs)).execution_options(populate_existing=True).where(PaperTrade.id == trade_id)
    trade = (await db.execute(trade_q)).scalar_one_or_none()
    if not trade or not trade.legs:
        # If no legs remain, delete the entire paper trade
        if trade:
            await db.delete(trade)
        await db.commit()
        raise HTTPException(status_code=200, detail="Trade deleted because all legs were removed")

    # Validate that remaining buy quantity covers sold quantity
    buy_qty = sum(l.quantity for l in trade.legs if l.action.upper() == "BUY")
    sold_qty = sum(l.quantity for l in trade.legs if l.action.upper() == "SELL")

    if sold_qty > buy_qty:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete leg: Remaining buy quantity ({buy_qty}) would be less than sold quantity ({sold_qty}).",
        )

    # Recalculate status
    if sold_qty >= buy_qty and buy_qty > 0:
        trade.status = "CLOSED"
    else:
        trade.status = "OPEN"

    await db.commit()

    refreshed = (await db.execute(trade_q)).scalar_one()
    snap = (await db.execute(select(TickerScreenerSnapshot).where(TickerScreenerSnapshot.symbol == refreshed.symbol))).scalar_one_or_none()
    univ = (await db.execute(select(StockUniverse).where(StockUniverse.symbol == refreshed.symbol))).scalar_one_or_none()

    return build_trade_out(refreshed, snap, univ)


@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper_trade(
    trade_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a paper trade position and all its legs."""
    trade = (await db.execute(select(PaperTrade).where(PaperTrade.id == trade_id))).scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Paper trade not found")

    await db.delete(trade)
    await db.commit()
