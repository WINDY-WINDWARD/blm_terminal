"""Technical alert evaluation helpers (audit C.8).

Extracted from ``app/workers/notification_cycles.py`` and
``app/workers/global_scan_cycle.py`` where the same per-symbol
technical evaluation logic was duplicated across 3 cycle functions.

Public functions:
- ``evaluate_technical_alerts(symbol, latest, prev, cfg, ...)``
  — daily-level alerts (used by daily notification + global scan).
- ``evaluate_intraday_alerts(symbol, latest, prev, cfg, interval)``
  — intraday-level alerts with interval suffix.

Both are pure functions: no DB or HTTP calls, all inputs passed in.
"""
from __future__ import annotations

from typing import Any


def evaluate_technical_alerts(
    symbol: str,
    latest: Any | None,
    prev: Any | None,
    cfg: dict[str, float],
    *,
    ts: Any | None = None,
    up_streak: int = 0,
    dn_streak: int = 0,
    pct_from_52w_high: float | None = None,
    pct_from_52w_low: float | None = None,
) -> list[tuple[str, str]]:
    """Evaluate all daily-level technical alert types for a single symbol.

    Returns a list of ``(trigger_type, message)`` tuples, ready to be
    wrapped into notification dicts by the caller.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. "RELIANCE").
    latest : TickerDaily | None
        Most recent daily row (must have indicator columns populated).
    prev : TickerDaily | None
        Previous daily row (needed for MACD crossover detection).
    cfg : dict[str, float]
        Notification threshold config (keys like ``notif.rsi_oversold_threshold``; values are float).
    ts : TickerScore | None
        Pre-computed momentum/return scores (optional, skips those alerts).
    up_streak : int
        Consecutive up-day count (0 = none).
    dn_streak : int
        Consecutive down-day count (0 = none).
    pct_from_52w_high : float | None
        Percentage away from 52W high (negative = below).
    pct_from_52w_low : float | None
        Percentage away from 52W low (positive = above).

    Returns
    -------
    list[tuple[str, str]]
        Each element is ``(trigger_type, message)``.
    """
    alerts: list[tuple[str, str]] = []

    if latest is None:
        return alerts

    rsi_oversold_thr   = float(cfg.get("notif.rsi_oversold_threshold", "30"))
    rsi_overbought_thr = float(cfg.get("notif.rsi_overbought_threshold", "70"))
    vol_spike_ratio    = float(cfg.get("notif.volatility_spike_ratio", "1.5"))
    atr_exp_thr        = float(cfg.get("notif.atr_expansion_threshold", "4.0"))
    momentum_thr       = float(cfg.get("notif.momentum_surge_threshold", "70"))
    return_1w_thr      = float(cfg.get("notif.return_1w_spike_threshold", "5.0"))
    streak_thr         = int(cfg.get("notif.streak_days_threshold", "3"))
    near52w_thr        = float(cfg.get("notif.near_52w_threshold", "2.0"))

    # RSI
    if latest.rsi_14 is not None:
        if latest.rsi_14 < rsi_oversold_thr:
            alerts.append(("rsi_oversold",
                f"{symbol} RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
        elif latest.rsi_14 > rsi_overbought_thr:
            alerts.append(("rsi_overbought",
                f"{symbol} RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

    # MACD crossover
    if prev and latest.macd_histogram is not None and prev.macd_histogram is not None:
        if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
            alerts.append(("macd_bullish_cross",
                f"{symbol} MACD bullish crossover "
                f"({prev.macd_histogram:.4f} → {latest.macd_histogram:.4f})"))
        elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
            alerts.append(("macd_bearish_cross",
                f"{symbol} MACD bearish crossover "
                f"({prev.macd_histogram:.4f} → {latest.macd_histogram:.4f})"))

    # Bollinger Bands
    if latest.bb_squeeze == "Y":
        alerts.append(("bb_squeeze_alert",
            f"{symbol} Bollinger Band squeeze detected (bb_width={latest.bb_width})"))
    if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
        alerts.append(("bb_upper_break",
            f"{symbol} close \u20b9{latest.close} broke above BB upper \u20b9{latest.bb_upper}"))
    if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
        alerts.append(("bb_lower_break",
            f"{symbol} close \u20b9{latest.close} broke below BB lower \u20b9{latest.bb_lower}"))

    # Volatility
    if (latest.hv_20 is not None and latest.hv_60 is not None
            and latest.hv_60 > 0
            and latest.hv_20 > latest.hv_60 * vol_spike_ratio):
        alerts.append(("volatility_spike",
            f"{symbol} HV20 {latest.hv_20:.1f}% > {vol_spike_ratio}\u00d7 HV60 {latest.hv_60:.1f}%"))
    if latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
        alerts.append(("atr_expansion",
            f"{symbol} ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

    # Momentum / returns (from pre-computed TickerScore cache)
    if ts is not None:
        if ts.momentum_score is not None and ts.momentum_score > momentum_thr:
            alerts.append(("momentum_surge",
                f"{symbol} momentum score {ts.momentum_score:.1f} > {momentum_thr}"))
        if ts.return_1w is not None and ts.return_1w > return_1w_thr:
            alerts.append(("return_1w_spike",
                f"{symbol} 1W return {ts.return_1w:+.1f}% > {return_1w_thr}%"))

    # Streaks
    if up_streak >= streak_thr:
        alerts.append(("streak_up_5d",
            f"{symbol} up {up_streak} consecutive days"))
    if dn_streak >= streak_thr:
        alerts.append(("streak_down_5d",
            f"{symbol} down {dn_streak} consecutive days"))

    # 52W proximity
    if pct_from_52w_high is not None and -near52w_thr <= pct_from_52w_high <= 0:
        alerts.append(("near_52w_high",
            f"{symbol} within {near52w_thr}% of 52W high ({pct_from_52w_high:+.1f}%)"))
    if pct_from_52w_low is not None and 0 <= pct_from_52w_low <= near52w_thr:
        alerts.append(("near_52w_low",
            f"{symbol} within {near52w_thr}% of 52W low ({pct_from_52w_low:+.1f}%)"))

    return alerts


def evaluate_intraday_alerts(
    symbol: str,
    latest: Any | None,
    prev: Any | None,
    cfg: dict[str, float],
    interval: str,
) -> list[tuple[str, str]]:
    """Evaluate intraday-level technical alerts for a single symbol x interval.

    Like ``evaluate_technical_alerts`` but adds ``_{interval}`` suffix to
    trigger types and ``[{interval}]`` to messages.
    """
    alerts: list[tuple[str, str]] = []

    if latest is None:
        return alerts

    rsi_oversold_thr   = float(cfg.get("notif.rsi_oversold_threshold", "30"))
    rsi_overbought_thr = float(cfg.get("notif.rsi_overbought_threshold", "70"))
    atr_exp_thr        = float(cfg.get("notif.atr_expansion_threshold", "4.0"))
    sfx = f"_{interval}"

    # RSI
    if latest.rsi_14 is not None:
        if latest.rsi_14 < rsi_oversold_thr:
            alerts.append((f"rsi_oversold{sfx}",
                f"{symbol} [{interval}] RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
        elif latest.rsi_14 > rsi_overbought_thr:
            alerts.append((f"rsi_overbought{sfx}",
                f"{symbol} [{interval}] RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

    # MACD crossover
    if prev and latest.macd_histogram is not None and prev.macd_histogram is not None:
        if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
            alerts.append((f"macd_bullish_cross{sfx}",
                f"{symbol} [{interval}] MACD bullish crossover"))
        elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
            alerts.append((f"macd_bearish_cross{sfx}",
                f"{symbol} [{interval}] MACD bearish crossover"))

    # Bollinger Bands
    if latest.bb_squeeze == "Y":
        alerts.append((f"bb_squeeze_alert{sfx}",
            f"{symbol} [{interval}] BB squeeze (width={latest.bb_width})"))
    if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
        alerts.append((f"bb_upper_break{sfx}",
            f"{symbol} [{interval}] close > BB upper"))
    if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
        alerts.append((f"bb_lower_break{sfx}",
            f"{symbol} [{interval}] close < BB lower"))

    # ATR expansion (1h only — meaningful for intraday)
    if interval == "1h" and latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
        alerts.append((f"atr_expansion{sfx}",
            f"{symbol} [1h] ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

    return alerts


def evaluate_mtf_alignment(
    symbol: str,
    daily_rsi: float | None,
    weekly_rsi: float | None,
    monthly_rsi: float | None,
) -> list[tuple[str, str]]:
    """Check multi-timeframe RSI alignment.
    
    Returns alerts when all three timeframes agree (all > 50 bull, all < 50 bear).
    """
    alerts: list[tuple[str, str]] = []
    if daily_rsi is not None and weekly_rsi is not None and monthly_rsi is not None:
        if daily_rsi > 50 and weekly_rsi > 50 and monthly_rsi > 50:
            alerts.append(("mtf_bullish_alignment",
                f"{symbol} MTF bullish: D={daily_rsi:.1f} W={weekly_rsi:.1f} M={monthly_rsi:.1f} all > 50"))
        elif daily_rsi < 50 and weekly_rsi < 50 and monthly_rsi < 50:
            alerts.append(("mtf_bearish_alignment",
                f"{symbol} MTF bearish: D={daily_rsi:.1f} W={weekly_rsi:.1f} M={monthly_rsi:.1f} all < 50"))
    return alerts
