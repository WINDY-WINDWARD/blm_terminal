"""SQLALCHEMY ORM MODEL for NSE daily OHLCV ticker warehouse"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TickerDaily(Base):
    """ORM model for daily OHLCV tick data from NSE.

    Indicator columns (rsi_14 … indicators_updated_at) are nullable and
    populated by the indicator backfill / nightly update jobs.  Early candles
    that have insufficient historical lookback will have NULL values.
    """

    __tablename__ = "ticker_daily"

    # --- core identity ---
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(4), nullable=False, server_default="EQ")

    # --- OHLCV ---
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    # --- Technical indicators (computed nightly, NULL until first backfill) ---
    rsi_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # "Y" = squeeze active, "N" = no squeeze, NULL = not yet computed
    bb_squeeze: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # timestamp set when indicator columns are written for this row
    indicators_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("symbol", "date", "series", name="uq_ticker_symbol_date_series"),
    )


class TickerScore(Base):
    """Pre-computed returns and momentum scores for all NSE symbols.

    Computed once per day via _ticker_scores_sync(). Used by _global_scan_cycle()
    to evaluate momentum_surge and return_1w_spike triggers without O(N²) queries.
    """

    __tablename__ = "ticker_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    compute_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    return_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_1w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_1m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_3m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_6m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_1y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    momentum_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    momentum_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    universe_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    volume_ratio_20d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", name="uq_ticker_scores_symbol"),
    )


class TickerScreenerSnapshot(Base):
    """Pre-computed denormalized screener row per symbol.

    One row per symbol holding every field the TQL screener can filter on,
    plus 1h/W/M latest closes for interval-prefixed indicator queries.
    Refreshed nightly + post-bhavcopy by extending _ticker_scores_sync().

    Joins with TickerScore for period returns and momentum.
    """

    __tablename__ = "ticker_screener_snapshot"

    # --- identity ---
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    compute_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    # --- last daily OHLCV ---
    last_close: Mapped[float] = mapped_column(Float, nullable=False)
    last_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_open: Mapped[float] = mapped_column(Float, nullable=False)
    last_high: Mapped[float] = mapped_column(Float, nullable=False)
    last_low: Mapped[float] = mapped_column(Float, nullable=False)

    # --- 1d indicators (TickerDaily columns) ---
    rsi_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_squeeze_1d: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 52-week distance (computed from 252d window) ---
    high_52w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_52w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_from_52w_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_from_52w_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- universe fields ---
    sector: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fair_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 1h indicators (TickerIntraday where interval='1h') ---
    intraday_close_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_squeeze_1h: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126_1h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- W indicators (TickerIntraday where interval='W') ---
    intraday_close_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_squeeze_W: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126_W: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- M indicators (TickerIntraday where interval='M') ---
    intraday_close_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_squeeze_M: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126_M: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_snapshot_sector_pe", "sector", "pe"),
        Index("ix_snapshot_compute_date", "compute_date"),
    )


class TickerIntraday(Base):
    """ORM model for intraday/weekly/monthly OHLCV candles from NSE charting API.

    Stores 1h, W, and M intervals. Uses a UTC DateTime timestamp instead of
    a Date column so that hourly candles can be distinguished by time-of-day.
    """

    __tablename__ = "ticker_intraday"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # UTC datetime of candle open
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    # "1h", "W", "M"
    interval: Mapped[str] = mapped_column(String(4), nullable=False)

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="nse_charting")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    # --- Technical indicators (computed post-backfill, NULL until first run) ---
    rsi_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_squeeze: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    indicators_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", "interval", name="uq_ticker_intraday_sym_ts_interval"),
        Index("ix_ticker_intraday_symbol_interval", "symbol", "interval"),
    )
