"""Technical indicators calculations with proper smoothing and validation."""

from typing import Optional
import math

from sqlalchemy import select

from app.models.ticker import TickerDaily
from app.database import _SyncSessionLocal


def _wilder_smoothing(values: list[float], period: int) -> list[float]:
    """
    Apply Wilder's smoothing (exponential moving average with alpha = 1/period).
    
    This is the correct smoothing method for RSI calculation.
    """
    if not values or len(values) < period:
        return []
    
    alpha = 1.0 / period
    smoothed = [values[0]]
    
    for i in range(1, len(values)):
        ema = alpha * values[i] + (1 - alpha) * smoothed[-1]
        smoothed.append(ema)
    
    return smoothed


def _calculate_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Calculate RSI with Wilder's smoothing."""
    if len(closes) < period + 28:
        return None
    
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return None
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    smoothed_gains = _wilder_smoothing(gains[period:], period)
    smoothed_losses = _wilder_smoothing(losses[period:], period)
    
    for i, (g, l) in enumerate(zip(smoothed_gains, smoothed_losses)):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)


def _calculate_ema(values: list[float], period: int) -> list[float]:
    """Calculate Exponential Moving Average."""
    if len(values) < period:
        return []
    
    alpha = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    
    for i in range(period, len(values)):
        ema_val = alpha * values[i] + (1 - alpha) * ema[-1]
        ema.append(ema_val)
    
    return ema


def _calculate_macd(closes: list[float]) -> Optional[dict]:
    """Calculate MACD (EMA12 - EMA26, Signal = EMA9 of MACD)."""
    if len(closes) < 60:
        return None
    
    ema_12 = _calculate_ema(closes, 12)
    ema_26 = _calculate_ema(closes, 26)
    
    if len(ema_12) < 26 or len(ema_26) < 26:
        return None
    
    macd_line = [e12 - e26 for e12, e26 in zip(ema_12[-len(ema_26):], ema_26)]
    
    if len(macd_line) < 9:
        return None
    
    signal = _calculate_ema(macd_line, 9)
    
    if not signal:
        return None
    
    current_macd = macd_line[-1]
    current_signal = signal[-1]
    histogram = current_macd - current_signal
    
    return {
        "macd": round(current_macd, 2),
        "signal": round(current_signal, 2),
        "histogram": round(histogram, 2),
    }


def _calculate_bollinger_bands(closes: list[float], period: int = 20) -> Optional[dict]:
    """Calculate Bollinger Bands with width and squeeze detection."""
    if len(closes) < period + 1:
        return None
    
    recent = closes[-period:]
    sma = sum(recent) / period
    
    variance = sum((c - sma) ** 2 for c in recent) / period
    std_dev = math.sqrt(variance)
    
    upper = sma + 2 * std_dev
    lower = sma - 2 * std_dev
    
    width = (upper - lower) / sma * 100 if sma != 0 else 0
    
    squeeze = False
    if len(closes) >= 126:
        past_widths = []
        for i in range(len(closes) - 126, len(closes) - period):
            window = closes[i:i + period]
            w_sma = sum(window) / period
            w_var = sum((c - w_sma) ** 2 for c in window) / period
            w_std = math.sqrt(w_var)
            w_upper = w_sma + 2 * w_std
            w_lower = w_sma - 2 * w_std
            w_width = (w_upper - w_lower) / w_sma * 100 if w_sma != 0 else 0
            past_widths.append(w_width)
        
        if past_widths and width <= min(past_widths):
            squeeze = True
    
    return {
        "middle": round(sma, 2),
        "upper": round(upper, 2),
        "lower": round(lower, 2),
        "width": round(width, 2),
        "squeeze": squeeze,
    }


def _calculate_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[dict]:
    """Calculate ATR (Average True Range) with percentage."""
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None
    
    trs = []
    for i in range(1, len(highs)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        tr = max(high_low, high_close, low_close)
        trs.append(tr)
    
    if len(trs) < period:
        return None
    
    atr = sum(trs[:period]) / period
    smoothed_trs = trs[period:]
    for t in smoothed_trs:
        atr = (atr * (period - 1) + t) / period
    
    current_close = closes[-1]
    atr_pct = (atr / current_close) * 100 if current_close != 0 else 0
    
    return {
        "atr": round(atr, 2),
        "atr_percent": round(atr_pct, 2),
    }


def _calculate_vwma(closes: list[float], volumes: list[int], period: int = 20) -> Optional[float]:
    """Calculate Volume-Weighted Moving Average of close."""
    if len(closes) < period or len(volumes) < period:
        return None
    
    recent_close = closes[-period:]
    recent_vol = volumes[-period:]
    
    total_pv = sum(c * v for c, v in zip(recent_close, recent_vol))
    total_vol = sum(recent_vol)
    
    if total_vol == 0:
        return None
    
    vwma = total_pv / total_vol
    return round(vwma, 2)


def _calculate_historical_volatility(closes: list[float], period: int = 20) -> Optional[float]:
    """Calculate Historical Volatility (annualised std dev of log returns)."""
    if len(closes) < period + 1:
        return None
    
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i] > 0 and closes[i - 1] > 0:
            lr = math.log(closes[i] / closes[i - 1])
            log_returns.append(lr)
    
    if len(log_returns) < period:
        return None
    
    recent_returns = log_returns[-period:]
    mean_return = sum(recent_returns) / len(recent_returns)
    variance = sum((r - mean_return) ** 2 for r in recent_returns) / len(recent_returns)
    std_dev = math.sqrt(variance)
    
    hv = std_dev * math.sqrt(252) * 100
    return round(hv, 2)


def _calculate_obv(closes: list[float], volumes: list[int]) -> Optional[int]:
    """Calculate On-Balance Volume (cumulative)."""
    if len(closes) < 2 or len(volumes) < 2:
        return None
    
    obv = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
    
    return obv


def _calculate_sharpe(closes: list[float], period: int = 60) -> Optional[float]:
    """Calculate Rolling Sharpe Ratio proxy (mean return / stddev * sqrt(252))."""
    if len(closes) < period + 1:
        return None
    
    daily_returns = []
    for i in range(1, len(closes)):
        if closes[i] > 0 and closes[i - 1] > 0:
            lr = (closes[i] - closes[i - 1]) / closes[i - 1]
            daily_returns.append(lr)
    
    if len(daily_returns) < period:
        return None
    
    recent = daily_returns[-period:]
    mean_ret = sum(recent) / len(recent)
    variance = sum((r - mean_ret) ** 2 for r in recent) / len(recent)
    std_dev = math.sqrt(variance)
    
    if std_dev == 0:
        return None
    
    sharpe = (mean_ret / std_dev) * math.sqrt(252)
    return round(sharpe, 2)


def get_indicators(symbol: str) -> dict:
    """
    Calculate all technical indicators for a symbol.
    
    Returns:
        Dict with all indicators, or error info if insufficient data.
    """
    with _SyncSessionLocal() as db:
        stmt = (
            select(TickerDaily)
            .where(TickerDaily.symbol == symbol)
            .order_by(TickerDaily.date.asc())
        )
        rows = list(db.execute(stmt).scalars().all())
    
    if not rows:
        return {
            "symbol": symbol,
            "error": "No data available",
            "data_points": 0,
        }
    
    row_count = len(rows)
    
    if row_count < 60:
        return {
            "symbol": symbol,
            "error": f"Insufficient data ({row_count} rows, need 60+)",
            "data_points": row_count,
        }
    
    closes = [r.close for r in rows if r.close is not None]
    highs = [r.high for r in rows if r.high is not None]
    lows = [r.low for r in rows if r.low is not None]
    volumes = [r.volume for r in rows if r.volume is not None]
    
    if len(closes) < 60:
        return {
            "symbol": symbol,
            "error": f"Insufficient close prices ({len(closes)}), need 60+",
            "data_points": len(closes),
        }
    
    result = {
        "symbol": symbol,
        "data_points": row_count,
        "latest_date": rows[-1].date.isoformat() if rows else None,
        "close": closes[-1] if closes else None,
    }
    
    rsi = _calculate_rsi(closes, 14)
    if rsi is not None:
        result["rsi_14"] = rsi
    
    macd = _calculate_macd(closes)
    if macd:
        result["macd"] = macd["macd"]
        result["macd_signal"] = macd["signal"]
        result["macd_histogram"] = macd["histogram"]
    
    bb = _calculate_bollinger_bands(closes, 20)
    if bb:
        result["bb_middle"] = bb["middle"]
        result["bb_upper"] = bb["upper"]
        result["bb_lower"] = bb["lower"]
        result["bb_width"] = bb["width"]
        result["bb_squeeze"] = bb["squeeze"]
    
    atr = _calculate_atr(highs, lows, closes, 14)
    if atr:
        result["atr_14"] = atr["atr"]
        result["atr_percent"] = atr["atr_percent"]
    
    vwma = _calculate_vwma(closes, volumes, 20)
    if vwma is not None:
        result["vwma_20"] = vwma
    
    hv20 = _calculate_historical_volatility(closes, 20)
    if hv20 is not None:
        result["hv_20"] = hv20
    
    if len(closes) >= 60:
        hv60 = _calculate_historical_volatility(closes, 60)
        if hv60 is not None:
            result["hv_60"] = hv60
    
    obv = _calculate_obv(closes, volumes)
    if obv is not None:
        result["obv"] = obv
    
    sharpe_60 = _calculate_sharpe(closes, 60)
    if sharpe_60 is not None:
        result["sharpe_60"] = sharpe_60
    
    if len(closes) >= 126:
        sharpe_126 = _calculate_sharpe(closes, 126)
        if sharpe_126 is not None:
            result["sharpe_126"] = sharpe_126
    
    return result