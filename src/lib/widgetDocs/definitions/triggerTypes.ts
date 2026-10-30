import type { DocField } from '../types';

export const TRIGGER_TYPE_DOCS: DocField[] = [
  // 52-Week
  {
    name: '52w_high_breakout',
    desc: 'Stock touched a new 52-week high today. Signals strong bullish momentum; often a continuation pattern when volume confirms.',
  },
  {
    name: '52w_low_breakout',
    desc: 'Stock hit a new 52-week low today. Can indicate capitulation or a breakdown — check sector context before acting.',
  },
  {
    name: 'near_52w_high',
    desc: 'Price is within 3% of its 52-week high. Watch for breakout or rejection at resistance.',
  },
  {
    name: 'near_52w_low',
    desc: 'Price is within 3% of its 52-week low. Potential support zone; elevated risk of further downside.',
  },
  // Volume
  {
    name: 'volume_breakout',
    desc: 'Today\'s volume is significantly above the weekly average. Validates price moves — high volume on a rally is bullish; on a decline is bearish.',
  },
  // Repeated Breakouts
  {
    name: 'repeated_52w_high',
    desc: 'Stock appeared in the 52W HIGH list multiple times in the last 10 calendar days. Persistent bullish momentum — consistent buying interest across sessions.',
  },
  {
    name: 'repeated_52w_low',
    desc: 'Stock appeared in the 52W LOW list multiple times in the last 10 calendar days. Persistent bearish pressure — sustained selling across sessions.',
  },
  {
    name: 'repeated_volume_breakout',
    desc: 'Stock appeared in the volume gainers list multiple times in the last 10 calendar days. Sustained unusual trading activity — may indicate accumulation or distribution.',
  },
  // Movers
  {
    name: 'top_gainer',
    desc: 'Among the top percentage gainers on NSE today. Could signal news, results, or sector rotation — investigate the catalyst.',
  },
  {
    name: 'top_loser',
    desc: 'Among the top percentage losers on NSE today. May reflect negative news, results, or broader selling pressure.',
  },
  // Deals
  {
    name: 'bulk_deal',
    desc: 'A bulk deal was reported: a single entity traded ≥0.5% of shares outstanding in one session. Often indicates institutional conviction.',
  },
  {
    name: 'block_deal',
    desc: 'A block deal was reported: a large negotiated trade (≥500,000 shares or ₹5 Cr) executed via the block window. Institutional change of hands.',
  },
  {
    name: 'short_deal',
    desc: 'A significant short position or short-covering deal was detected. Elevated if deal size is large relative to market cap.',
  },
  // Insider
  {
    name: 'insider_buy',
    desc: 'A promoter, director, or key management person bought shares. Insiders buying with their own money is a classic bullish signal.',
  },
  {
    name: 'insider_sell',
    desc: 'An insider sold shares. Can be for personal liquidity reasons; more meaningful when multiple insiders sell concurrently.',
  },
  // Technical — RSI
  {
    name: 'rsi_oversold',
    desc: 'RSI (14-day) dropped below 30. Historically a mean-reversion zone — but can remain oversold in strong downtrends. Combine with price action.',
  },
  {
    name: 'rsi_overbought',
    desc: 'RSI (14-day) exceeded 70. Momentum is stretched; watch for reversal signals, but trend-following strategies may stay long.',
  },
  // Technical — MACD
  {
    name: 'macd_bullish_cross',
    desc: 'MACD line crossed above the signal line. A lagging momentum buy signal; more reliable when it occurs below zero.',
  },
  {
    name: 'macd_bearish_cross',
    desc: 'MACD line crossed below the signal line. A lagging momentum sell signal; more reliable when it occurs above zero.',
  },
  // Technical — Bollinger Bands
  {
    name: 'bb_squeeze_alert',
    desc: 'Bollinger Band width is at a multi-month low. Low volatility periods (squeezes) often precede large directional moves — direction is unknown.',
  },
  {
    name: 'bb_upper_break',
    desc: 'Price closed above the upper Bollinger Band (2σ). Can signal a breakout continuation or an overextension depending on context.',
  },
  {
    name: 'bb_lower_break',
    desc: 'Price closed below the lower Bollinger Band (2σ). Indicates a potential oversold condition or a strong downside breakout.',
  },
  // Volatility
  {
    name: 'volatility_spike',
    desc: 'Historical volatility (20-day HV) is significantly higher than the 60-day baseline. Elevated risk environment — widen stops or size down.',
  },
  {
    name: 'atr_expansion',
    desc: 'Average True Range (ATR) has expanded sharply. Day ranges are widening; be prepared for larger intraday swings.',
  },
  // Momentum
  {
    name: 'momentum_surge',
    desc: 'Composite momentum score exceeded 70 (top percentile). Multi-factor signal combining price change, volume, and returns.',
  },
  {
    name: 'return_1w_spike',
    desc: '1-week return is in the top percentile of the NSE universe. Sharp short-term outperformance — check if it is driven by news or a structural shift.',
  },
  // Streaks
  {
    name: 'streak_up_5d',
    desc: 'Stock has closed higher for 5+ consecutive sessions. Sustained buying pressure; can indicate trend establishment or short-term exhaustion.',
  },
  {
    name: 'streak_down_5d',
    desc: 'Stock has closed lower for 5+ consecutive sessions. Persistent selling; monitor for capitulation or support-level reactions.',
  },
  // Results
  {
    name: 'results_upcoming',
    desc: 'NSE board meeting scheduled to announce quarterly / annual financial results. Expect increased volatility around the event date.',
  },
];
