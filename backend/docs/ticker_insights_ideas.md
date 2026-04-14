# Ticker Warehouse — Ideas for Extracting Insights (v2)

> **Changelog from v1:** Logic errors corrected (VWAP renamed, RS formula fixed, gap fill clarified, row-offset date lookups flagged). New sections added: Momentum Scoring, Price Structure, Intraday Range Quality, Delivery Percentage, Volume Profile, Rolling Sharpe, Streak Tracking, Peer Ranking, ATH Drawdown, Event Scanner (split from Notifications). Priority table updated.

---

## 1. Data Model Summary

### Current Schema: `ticker_daily`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| symbol | VARCHAR(32) | NSE ticker symbol |
| date | DATE | Trading date |
| series | VARCHAR(4) | EQ, BE, etc. (default EQ) |
| open | FLOAT | Opening price |
| high | FLOAT | Intraday high |
| low | FLOAT | Intraday low |
| close | FLOAT | Closing price |
| volume | BIGINT | Total traded quantity |
| value | FLOAT | Total traded value (₹) |
| deliverable_qty | BIGINT | Deliverable quantity (if available in bhavcopy — check schema) |
| source | VARCHAR(32) | bhavcopy or equity_history |
| created_at | DATETIME | Row creation timestamp |

> **Note:** `deliverable_qty` may already exist in the bhavcopy source. Verify before assuming it needs to be added. If present, it unlocks delivery % analysis (§17).

### Available Metadata (Joinable)

1. **stock_universe**
   - `symbol`, `company_name`
   - `industry_info` (JSON: macro, sector, industry, basicIndustry)
   - `symbol_pe` (PE ratio, available for ~678 symbols)
   - `fair_value` (currently empty — planned Morningstar data)

2. **market_category_stocks**
   - `symbol`, `company_name`, `exchange`
   - `curr_price`, `per_change`
   - `market_cap`, `ttm_pe`
   - `tech_trend` (Bullish, Bearish, Neutral, Very Bullish, Very Bearish)

### Implementation Note: Date Lookups vs Row Offsets

All period-based calculations (1W, 1M, 3M, etc.) **must use date-based lookups**, not row offsets like `close_20d` (i.e., the 20th prior row). Row offsets break for recently listed stocks, symbols with trading halts, or suspensions. Use: find the row with the closest date to `current_date - N calendar days` within the symbol's history.

---

## 2. Technical Indicators

Computed on the fly from OHLCV. No additional storage needed.

### 2.1 Moving Averages

| Indicator | Formula | Use |
|-----------|---------|-----|
| SMA 20 | mean(close, 20) | Short-term trend |
| SMA 50 | mean(close, 50) | Medium-term trend |
| SMA 200 | mean(close, 200) | Long-term trend |
| EMA 12 | exponential moving average (Wilder smoothing) | Fast MACD component |
| EMA 26 | exponential moving average (Wilder smoothing) | Slow MACD component |

**Signals:**
- Price above SMA50 → medium-term bullish
- Price above SMA200 → long-term bullish
- SMA50 crossing above SMA200 → Golden Cross (bullish)
- SMA50 crossing below SMA200 → Death Cross (bearish)

### 2.2 MACD (Moving Average Convergence Divergence)

| Component | Formula |
|-----------|---------|
| MACD Line | EMA12 - EMA26 |
| Signal Line | EMA9(MACD) |
| Histogram | MACD - Signal |

**Signals:**
- MACD crosses above Signal → bullish momentum
- MACD crosses below Signal → bearish momentum
- Histogram expanding → strengthening momentum

> **Implementation note:** EMA26 needs ~52 bars to stabilise (2× period rule). Do not serve MACD for symbols with fewer than 60 rows.

### 2.3 RSI (Relative Strength Index)

| Parameter | Formula |
|-----------|---------|
| RSI 14 | 100 - 100/(1 + RS), where RS = avg gain / avg loss over 14 periods |

**Interpretation:**
- RSI > 70: Overbought, potential reversal
- RSI < 30: Oversold, potential bounce
- RSI > 50: Bullish bias
- RSI < 50: Bearish bias

> **Implementation note:** Use Wilder's smoothing (exponential, not simple average) when computing RS. Simple averaging produces incorrect values. Warm up with at least 28 periods before trusting output.

### 2.4 Bollinger Bands

| Component | Formula |
|-----------|---------|
| Middle | SMA20 |
| Upper | Middle + 2 × stddev(close, 20) |
| Lower | Middle - 2 × stddev(close, 20) |
| BB Width | (Upper - Lower) / Middle |

**Signals:**
- Price touching Upper → overbought
- Price touching Lower → oversold
- Squeeze: BB Width at N-period low → compression, potential breakout imminent

> **Squeeze definition:** explicitly define squeeze as BB Width being at its lowest point over the last 126 trading days (~6 months). "Narrowing bands" is too vague to implement consistently.

### 2.5 ATR (Average True Range)

| Component | Formula |
|-----------|---------|
| TR | max(high - low, \|high - prev_close\|, \|low - prev_close\|) |
| ATR 14 | mean(TR, 14) |
| ATR% | ATR14 / close × 100 |

**Use:** Normalise volatility for position sizing and cross-symbol comparison. Always use ATR% (normalised) rather than raw ATR — raw values are not comparable across different price levels.

### 2.6 Historical Volatility

| Component | Formula |
|-----------|---------|
| HV20 | stddev(log(close_t / close_(t-1))) × sqrt(252) × 100 |
| HV60 | stddev(log(close_t / close_(t-1))) × sqrt(252) × 100 |

**Use:** Options pricing, risk management. If HV20 > HV60, short-term volatility is elevated relative to recent history — potential for mean reversion or continued expansion.

### 2.7 OBV (On-Balance Volume)

| Component | Formula |
|-----------|---------|
| OBV | Cumulative sum: +volume when close > prev_close, -volume when close < prev_close |

**Use:** Volume-price divergence. Price falling but OBV rising = accumulation (bullish divergence). Most useful as a divergence signal rather than an absolute level. Expect noise with daily data — manage expectations accordingly.

### 2.8 VWMA (Volume-Weighted Moving Average of Close)

> **Renamed from VWAP.** True VWAP is an intraday concept that resets daily and requires tick or minute-level data. With daily OHLCV, what is computable is a volume-weighted moving average of close prices. Calling it VWAP is technically incorrect.

| Component | Formula |
|-----------|---------|
| VWMA (N days) | sum(close × volume, N days) / sum(volume, N days) |

**Use:** Fair value proxy weighted by traded activity. Price above VWMA = trading at a premium to recent volume-weighted activity.

---

## 3. Screener Filters

The most valuable terminal feature — filter the entire universe at once.

> **Performance note:** For a universe of 2000+ symbols, cache screener results after the daily update and invalidate the cache on the next update. Running screener queries on every request is expensive.

### 3.1 Price Action Filters

| Filter | Formula | Example |
|--------|---------|---------|
| % change today | (close - open) / open × 100 | > 3% |
| % change 1W | (close - close_5d) / close_5d × 100 | top 20 |
| % change 1M | (close - close_20d) / close_20d × 100 | top 20 |
| % change 3M | (close - close_60d) / close_60d × 100 | top 20 |
| % change 6M | (close - close_120d) / close_120d × 100 | top 20 |
| % change 1Y | (close - close_252d) / close_252d × 100 | top 20 |

> **Reminder:** Use date-based lookups, not row offsets (see §1 implementation note).

### 3.2 Volume Filters

| Filter | Formula | Threshold |
|--------|---------|-----------|
| Volume ratio | today_vol / avg_vol_20d | > 2.0 = unusual |
| Value traded | avg(value, 20d) | filter by liquidity |
| Value spike ratio | today_value / avg_value_20d | > 1.5 |

### 3.3 52-Week Position

| Filter | Formula | Interpretation |
|--------|---------|----------------|
| % from 52W high | (close - 52w_high) / 52w_high × 100 | < 5% = near breakout |
| % from 52W low | (close - 52w_low) / 52w_low × 100 | > 200% = recovered |
| 52W high flag | close >= 52w_high | At new 52W high |
| 52W low flag | close <= 52w_low | At new 52W low |

### 3.4 ATH (All-Time High) Position

| Filter | Formula | Interpretation |
|--------|---------|----------------|
| ATH drawdown | (close - max(close, all history)) / max(close, all history) × 100 | 0% = fresh ATH |
| ATH flag | close >= max(close, all history) | New all-time high |

> A stock making a 52W high but 40% below ATH is structurally very different from one making a fresh ATH. Both filters are needed.

### 3.5 Trend Filters

| Filter | Condition |
|--------|-----------|
| Above SMA50 | close > SMA50 |
| Below SMA50 | close < SMA50 |
| Golden Cross (recent) | SMA50 crossed above SMA200 within last N days |
| Death Cross (recent) | SMA50 crossed below SMA200 within last N days |
| Price structure uptrend | Higher highs + higher lows over last 3 swings (see §14) |

### 3.6 Volatility Filters

| Filter | Formula | Example |
|--------|---------|---------|
| ATR% | ATR14 / close × 100 | < 2% = low vol |
| ATR% rank | Percentile rank of ATR% across universe | < 20% = consolidating |
| BB Squeeze | BB Width at 126-day low | True/False |

### 3.7 Valuation Filters (Join with stock_universe)

| Filter | Field |
|--------|-------|
| PE less than | symbol_pe < 15 |
| PE greater than | symbol_pe > 25 |
| PE in range | 15 <= symbol_pe <= 25 |

### 3.8 Sector/Industry Filters (Join with stock_universe)

| Filter | Field |
|--------|-------|
| Sector equals | industry_info->>'$.sector' = 'IT' |
| Industry contains | industry_info->>'$.industry' LIKE '%Banking%' |
| Macro sector | industry_info->>'$.macro' = 'Financial Services' |
| Basic industry | industry_info->>'$.basicIndustry' = 'Private Sector Bank' |

### 3.9 Technical Trend Filters (Join with market_category_stocks)

| Filter | Field |
|--------|-------|
| Tech trend | tech_trend = 'Bullish' |
| Tech trend | tech_trend IN ('Bullish', 'Very Bullish') |

### 3.10 Momentum Score Filter (see §13)

| Filter | Field |
|--------|-------|
| Momentum score min | momentum_score >= 70 |
| Momentum rank | top N by momentum_score |

### 3.11 Composite Screener (Example Payload)

```json
GET /api/ticker/screener?filters={
  "pct_change_1m_min": 5,
  "volume_ratio_min": 1.5,
  "pct_from_52w_high_max": 10,
  "atr_pct_max": 3.0,
  "sector": "IT",
  "sort_by": "pct_change_1m",
  "order": "desc",
  "limit": 20
}
```

---

## 4. Multi-Period Returns

Single endpoint to retrieve all standard return periods for one symbol or bulk for multiple.

### 4.1 Return Periods

| Period | Trading Days |
|--------|-------------|
| 1D | 1 |
| 1W | 5 |
| 1M | 20 |
| 3M | 60 |
| 6M | 120 |
| 1Y | 252 |

### 4.2 Endpoints

```json
GET /api/ticker/returns/{symbol}
// Response:
{
  "symbol": "RELIANCE",
  "1d": 1.23,
  "1w": -2.45,
  "1m": 5.67,
  "3m": 12.34,
  "6m": 23.45,
  "1y": 45.67,
  "latest_date": "2026-04-10"
}

GET /api/ticker/returns-bulk?symbols=RELIANCE,TCS,INFY
// Returns array of return objects for multiple symbols
```

### 4.3 Universe Return Heatmap

```json
GET /api/ticker/universe-returns?period=1m&sort_by=return&order=desc&limit=50
// Top 50 performers ranked by 1-month return
```

### 4.4 Sector Return Aggregation

Join `ticker_daily` → `stock_universe` → extract `industry_info->>'$.sector'` as sector.

```json
GET /api/ticker/sector-returns?period=1m
// Response:
[
  { "sector": "IT", "avg_return": 4.5, "median_return": 3.8, "count": 45 },
  { "sector": "Financial Services", "avg_return": 2.3, "median_return": 1.9, "count": 89 }
]
```

> Include median alongside average — sector averages can be skewed by a single outlier stock.

---

## 5. Relative Strength

### 5.1 Relative Strength vs Index

> **Formula corrected from v1.** The ratio formula `(symbol_return / index_return) - 1` breaks when the index return is negative (produces misleading RS). Use return spread instead.

| Metric | Formula |
|--------|---------|
| RS spread (N days) | symbol_return_Nd - index_return_Nd |
| Mansfield RS | (symbol / SMA(symbol, 52w)) / (index / SMA(index, 52w)) - 1 |

- RS spread > 0: Outperforming the index
- RS spread < 0: Underperforming
- Mansfield RS normalises for trend, preferred for absolute ranking

### 5.2 Sector Relative Strength

Within a sector, compare each stock's return to the sector average return over the same period.

### 5.3 Intra-Industry Peer Ranking (New in v2)

Using `basicIndustry` from `industry_info` (more granular than sector), rank each stock by 3M return within its immediate peer group. A stock in the top quartile of its 15–20 peers is a more precise signal than being in the top quartile of 500 IT stocks.

```json
GET /api/ticker/peer-rank/{symbol}?period=3m
// Response:
{
  "symbol": "HDFCBANK",
  "basic_industry": "Private Sector Bank",
  "peer_count": 18,
  "rank": 3,
  "percentile": 83.3,
  "period": "3m"
}
```

### 5.4 Endpoints

```json
GET /api/ticker/relative-strength/{symbol}?vs=NIFTY50&period=3m
// Response: { "symbol": "RELIANCE", "vs": "NIFTY50", "period": "3m", "rs_spread": 0.15, "mansfield_rs": 0.08 }

GET /api/ticker/peer-rank/{symbol}?period=3m
```

---

## 6. Volume Analysis

### 6.1 Volume Spike Detection

| Metric | Formula | Threshold |
|--------|---------|-----------|
| Volume ratio | today_vol / mean(volume, last 20 days) | > 2.0 = unusual |
| Volume spike flag | volume_ratio > 2.0 | True/False |
| Unusual volume alert | volume_ratio > 3.0 | True/False |

### 6.2 Value Traded (Liquidity Proxy)

| Metric | Formula |
|--------|---------|
| Avg daily value | sum(value, last 20 days) / 20 |
| Value rank | Percentile rank of avg_daily_value across universe |

Use as a minimum liquidity filter on screener results (e.g., avg_daily_value > ₹10 Cr).

### 6.3 Money Flow

| Metric | Formula |
|--------|---------|
| Value spike | today_value / avg_value_20d - 1 |
| Distribution signal | close < open AND volume_ratio > 2.0 → potential smart money selling |
| Accumulation signal | close > open AND volume_ratio > 2.0 → potential smart money buying |

### 6.4 Delivery Percentage (New in v2 — if data available)

> NSE bhavcopy includes `deliverable_qty` for EQ series. If present in your bhavcopy pulls, this is high-value data. Check your source before assuming it needs to be sourced separately.

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| Delivery % | deliverable_qty / volume × 100 | High = genuine buying |
| Delivery spike | delivery_pct >> 20-day avg delivery_pct | Conviction move |

A high delivery % on a breakout day indicates institutional or delivery-based buying rather than intraday speculation. This is a signal professional traders in India specifically look for and is rare in retail terminals.

---

## 7. Gap Analysis

### 7.1 Gap Calculation

| Metric | Formula |
|--------|---------|
| Gap % | (open - prev_close) / prev_close × 100 |
| Gap type | Gap up (> 0.5%), Gap down (< -0.5%), No gap |

### 7.2 Gap Fill Detection

> **Corrected from v1.** Distinguish between intraday fill and closing fill — they have different implications.

| Metric | Condition | Meaning |
|--------|-----------|---------|
| Intraday fill (gap up) | low <= prev_close | Gap touched during session |
| Close fill (gap up) | close <= prev_close | Gap fully erased by EOD |
| Gap retained | close remains above prev_close (for gap up) | Momentum held |

A gap that is touched intraday but closed above is a bullish sign (buyers stepped in). A gap that closes below is bearish. Treat these as distinct signals.

### 7.3 Gap Statistics per Symbol

| Metric | Formula |
|--------|---------|
| Gap frequency | % of days with \|gap%\| > 0.5% |
| Avg gap size | mean(\|gap%\|) for gap days only |
| Intraday fill rate | % of gap days where gap was touched intraday |
| Close fill rate | % of gap days where gap was fully closed by EOD |

### 7.4 Endpoint

```json
GET /api/ticker/gaps/{symbol}?last=30
// Response includes both intraday and close fill flags per gap
```

---

## 8. Candle Pattern Detection

### 8.1 Basic Patterns

| Pattern | Condition |
|---------|-----------|
| Doji | \|open - close\| < 0.3% of close AND body/range < 0.1 |
| Hammer | Body in upper 25% of range; lower wick > 2× body size |
| Shooting Star | Body in lower 25% of range; upper wick > 2× body size |
| Marubozu | Body > 90% of total range |

> **Doji fix from v1:** Pure ratio threshold of 0.1 is too loose on high-range days. Add an absolute cap: `|open - close| < 0.3% of close`. This prevents a ₹10 move being classified as a doji on a ₹5 stock.

### 8.2 Multi-Day Patterns

| Pattern | Condition |
|---------|-----------|
| Inside Bar | high_t < high_(t-1) AND low_t > low_(t-1) |
| Outside Bar | high_t > high_(t-1) AND low_t < low_(t-1) |
| NR7 | Today's range = minimum of the last 7 days' ranges |
| Bullish Engulfing | Bearish candle followed by bullish candle whose body fully engulfs prior body |
| Bearish Engulfing | Bullish candle followed by bearish candle whose body fully engulfs prior body |

> NR7 (Narrow Range 7) is an effective compression/consolidation signal — price coiling before a directional move. Underused in retail terminals.

### 8.3 Intraday Range Quality (New in v2)

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| Range quality | (close - open) / (high - low) | Near +1.0 = strong bull candle |
| 5-day avg range quality | mean(range_quality, 5) | Directional conviction score |

- +1.0: Closed at high, maximum bullish
- -1.0: Closed at low, maximum bearish
- ~0: Indecision / doji-like

Aggregate over 5 days to produce a directional conviction score. More nuanced than counting up/down days.

### 8.4 Endpoint

```json
GET /api/ticker/patterns/{symbol}?days=30
// Response: { "symbol": "RELIANCE", "patterns": [{ "date": "2026-04-10", "pattern": "hammer", "range_quality": 0.82 }] }
```

---

## 9. Sector / Industry Aggregation

### 9.1 Sector Breadth

For each sector, what % of stocks are above their SMA50?

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| % above SMA50 | count(close > SMA50) / count(sector) × 100 | > 60% = strong sector |
| % above SMA200 | count(close > SMA200) / count(sector) × 100 | Long-term health |

### 9.2 Sector Rotation Heatmap

Rank sectors by average 1M return. Identify which macro sectors are leading/lagging.

```json
GET /api/ticker/sector-rotation?period=1m
// Response: [ { "sector": "IT", "avg_return": 4.5, "median_return": 3.8, "breadth_pct": 68 } ... ]
```

### 9.3 Intra-Sector Relative Strength

Within each sector, rank stocks by 3M return vs sector average.

---

## 10. Price Structure Analysis (New in v2)

More meaningful than moving average crossovers for trend classification.

### 10.1 Higher Highs / Lower Lows

Detect whether a stock is in a structural uptrend or downtrend by comparing recent swing points:

| Structure | Condition |
|-----------|-----------|
| Structural uptrend | Last 3 swing highs each higher than previous; last 3 swing lows each higher than previous |
| Structural downtrend | Last 3 swing highs each lower than previous; last 3 swing lows each lower than previous |
| Sideways / inconclusive | Neither pattern confirmed |

**Swing point detection:** A swing high is a day whose high exceeds the 3 days on either side. A swing low is the inverse. Use 3-bar lookback as default, configurable.

### 10.2 Screener Filter

```json
{ "price_structure": "uptrend" }
// Returns only symbols with confirmed structural uptrend
```

---

## 11. Fair Value Overlay

> **Note:** `stock_universe.fair_value` is currently empty. This section activates when Morningstar data is populated. Flag the data staleness date alongside any MOS figures — Morningstar fair values update quarterly and can be significantly lagged.

### 11.1 Margin of Safety

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| Margin of Safety (MOS) | (fair_value - close) / fair_value × 100 | > 20% = undervalued |
| Data age flag | days since fair_value was last updated | Show if > 90 days old |

- MOS > 20%: Meaningfully undervalued
- MOS > 50%: Deep value (verify data freshness before acting)

### 11.2 Screener Addition

```json
GET /api/ticker/screener?filters={ "mos_min": 20, "rs_3m_min": 0 }
// Undervalued + positive momentum = value + catalyst
```

---

## 12. Event Scanner (Split from Notifications)

> **Structural change from v1:** Separate the *Event Scanner* (what happened today, push-driven, runs post-EOD) from the *Screener* (query-driven, user filters). They share calculation logic but have different UX and update cadence. The scanner should run automatically as a background job after each daily update.

### 12.1 Price-Based Events

| Event | Condition |
|-------|-----------|
| 52W high breakout | close > max(close, 252 trading days) |
| ATH breakout | close > max(close, all history) |
| 52W low breakdown | close < min(close, 252 trading days) |
| Gap up > 3% | gap_pct > 3% |
| Gap down > 3% | gap_pct < -3% |

### 12.2 Volume-Based Events

| Event | Condition |
|-------|-----------|
| Volume spike | today_vol / avg_vol_20d > 3.0 |
| Volume collapse | today_vol / avg_vol_20d < 0.2 |
| High delivery breakout | delivery_pct > 70% AND volume_ratio > 2.0 |

### 12.3 Technical Indicator Events

| Event | Condition |
|-------|-----------|
| RSI crosses below 30 | RSI_(t-1) >= 30 AND RSI_t < 30 (entering oversold) |
| RSI crosses above 70 | RSI_(t-1) <= 70 AND RSI_t > 70 (entering overbought) |
| Golden Cross | SMA50_t > SMA200_t AND SMA50_(t-1) <= SMA200_(t-1) |
| Death Cross | SMA50_t < SMA200_t AND SMA50_(t-1) >= SMA200_(t-1) |
| Price crosses SMA200 up | close_t > SMA200 AND close_(t-1) <= SMA200 |
| Price crosses SMA200 down | close_t < SMA200 AND close_(t-1) >= SMA200 |
| BB Squeeze breakout | BB squeeze resolves with price moving outside bands |

### 12.4 Streak Events

| Event | Condition |
|-------|-----------|
| Consecutive up closes | N-th consecutive day of close > prev_close (alert at 5, 7, 10) |
| Consecutive down closes | N-th consecutive day of close < prev_close |
| New momentum streak | First day above SMA50 after > 10 days below |

### 12.5 Implementation

Background worker runs post-EOD update, checks all conditions across universe, inserts into `notifications` table with `symbol`, `event_type`, `date`, `value`.

```json
POST /api/ticker/run-event-scan
// Triggers background scan for all event types across all symbols
```

---

## 13. Momentum Scoring (New in v2)

A single composite score per symbol (0–100) that enables ranking without requiring the user to configure filters. Useful for "top momentum stocks" widgets and default screener sorts.

### 13.1 Score Components

| Component | Weight | Metric |
|-----------|--------|--------|
| 3M return rank | 30% | Percentile rank of 3M return across universe |
| 6M return rank | 30% | Percentile rank of 6M return across universe |
| 1M volume ratio | 20% | Percentile rank of avg volume ratio (1M) |
| RS vs Nifty50 (3M) | 20% | Percentile rank of RS spread |

**Score = 0.30 × rank_3m + 0.30 × rank_6m + 0.20 × rank_vol + 0.20 × rank_rs**

All ranks are 0–100 percentiles within the universe. Score of 80+ = top momentum tier.

> Weights are a starting point — backtest against 20-day forward returns and tune. The framework matters more than the exact weights.

### 13.2 Endpoint

```json
GET /api/ticker/momentum-score/{symbol}
// Response: { "symbol": "TCS", "score": 84.2, "rank": 45, "universe_size": 2100 }

GET /api/ticker/momentum-leaderboard?limit=50
// Top 50 by momentum score
```

---

## 14. Streak Tracking (New in v2)

Low-effort to compute, high-value for UI and event scanning.

| Metric | Formula |
|--------|---------|
| Consecutive up closes | Count of trailing days where close > prev_close |
| Consecutive down closes | Count of trailing days where close < prev_close |
| Consecutive above-average volume | Count of trailing days where volume > avg_vol_20d |
| Days since last 52W high | Calendar days since max(close) was set over trailing 252 trading days |
| Days since last new high (ATH) | Calendar days since all-time high was set |

These feed directly into UI display ("8th consecutive up day") and notification triggers naturally.

---

## 15. Rolling Sharpe Proxy (New in v2)

Allows return-per-unit-of-risk comparison across symbols, not just raw return.

| Metric | Formula |
|--------|---------|
| Sharpe proxy (N days) | mean(daily_returns, N) / stddev(daily_returns, N) × sqrt(252) |

No risk-free rate adjustment is needed for a relative ranking tool — the goal is comparison, not absolute risk-adjusted return. Use N = 60 (3M) and N = 126 (6M) as standard windows.

A stock up 30% with half the volatility of one up 35% is the better risk-adjusted hold. Raw return screeners miss this.

```json
GET /api/ticker/indicators/{symbol}
// Include sharpe_60 and sharpe_126 in response
```

---

## 16. Correlation & Portfolio Tools

### 16.1 Correlation Matrix

> **Implementation constraint:** 2000+ symbols = ~2M pairs. Must be a background job, not an on-request computation. Recommend computing only for a curated universe (Nifty500 or similar) unless compute is not a concern.

| Metric | Formula |
|--------|---------|
| Pairwise correlation | correlation(symbol_a_daily_returns, symbol_b_daily_returns) over 60 days |

**Use:** Pairs trading (high correlation), hedging (inverse correlation).

### 16.2 Beta to Nifty

| Metric | Formula |
|--------|---------|
| Beta | covariance(symbol_returns, nifty_returns) / variance(nifty_returns) over 252 days |

- Beta > 1: Aggressive (amplifies market moves)
- Beta < 1: Defensive (dampens market moves)
- Beta < 0: Inverse (rare for equities, useful for hedging)

### 16.3 Drawdown Analysis

| Metric | Formula |
|--------|---------|
| Max Drawdown (52W) | (peak - trough) / peak × 100 for trailing 252 trading days |
| ATH Drawdown | (close - max(close, all history)) / max(close, all history) × 100 |
| Days to Recovery | Days from trough back to previous peak (if recovered) |

```json
GET /api/ticker/drawdowns/{symbol}?window=252
```

---

## 17. Volume Profile (New in v2)

Higher complexity but high differentiation — largely absent from Indian retail terminals.

### 17.1 Concept

Bucket all closing prices over the last 252 trading days into N bins (e.g., 50 bins between the 52W low and 52W high). Accumulate total volume traded at each price bin.

| Metric | Description |
|--------|-------------|
| High Volume Node (HVN) | Price bins with above-average accumulated volume = strong support/resistance |
| Low Volume Node (LVN) | Price bins with below-average accumulated volume = areas where price moves fast |
| Point of Control (POC) | Price bin with highest accumulated volume = strongest fair value magnet |

### 17.2 Use Cases

- Identifying key support/resistance levels from actual traded volume, not arbitrary chart lines
- POC acts as a gravitational center — price tends to return to it
- LVNs explain why price sometimes moves through a level quickly with little resistance

### 17.3 Implementation Notes

- Compute as a background job post-EOD, store per symbol
- Expose as a chart overlay via the indicators endpoint
- Use 252-day rolling window, recalculate weekly rather than daily to reduce compute

```json
GET /api/ticker/volume-profile/{symbol}?window=252
// Response: { "poc": 1245.5, "hvn": [1220-1240, 1280-1300], "lvn": [1250-1260] }
```

---

## 18. Earnings Context Flags (New in v2)

Adds context to all technical signals — a breakout into earnings is very different from one post-results.

### 18.1 Data Source

NSE / BSE corporate calendar (available via NSE API or scraped). Store in a separate `earnings_calendar` table: `symbol`, `results_date`, `quarter`.

### 18.2 Flags

| Flag | Condition |
|------|-----------|
| Pre-earnings (< 2 weeks) | results_date - today < 14 days |
| Post-earnings (< 2 weeks) | today - results_date < 14 days |
| Earnings vol expansion | HV20 >> HV60 within pre-earnings window |

### 18.3 Screener Addition

```json
{ "exclude_pre_earnings": true }
// Remove stocks within 14 days of results from screener output
```

---

## 19. Implementation Priority

Updated ordering by value-to-effort ratio.

| Priority | Feature | Complexity | Value |
|----------|---------|------------|-------|
| 1 | Multi-period returns endpoint | Low | High |
| 2 | Screener (price / volume / 52W / ATH) | Medium | Very High |
| 3 | 52W + ATH high/low position | Low | High |
| 4 | Momentum composite score | Low | Very High |
| 5 | Volume spike detection → Event Scanner | Low | High |
| 6 | Technical indicators endpoint (RSI, MACD, BB, ATR) | Medium | High |
| 7 | Streak tracking | Low | Medium |
| 8 | Sector aggregation + breadth | Medium | High |
| 9 | Sector rotation heatmap | Medium | High |
| 10 | Intra-industry peer ranking | Low | High |
| 11 | Rolling Sharpe proxy | Low | High |
| 12 | Multi-symbol returns heatmap | Low | Medium |
| 13 | Price structure (HH/HL detection) | Medium | High |
| 14 | Intraday range quality score | Low | Medium |
| 15 | Gap analysis (with corrected fill logic) | Low | Medium |
| 16 | Candle patterns | Medium | Medium |
| 17 | Relative strength vs index (corrected formula) | Medium | Medium |
| 18 | Delivery % integration | Low (if data exists) | Very High |
| 19 | MA crossover notifications (Golden/Death cross) | Medium | High |
| 20 | Earnings context flags | Medium | High |
| 21 | Beta to Nifty | Medium | Medium |
| 22 | Drawdown analysis | Medium | Medium |
| 23 | Correlation matrix | High | Medium |
| 24 | Volume profile (price-at-volume) | High | High (differentiator) |
| 25 | Fair value overlay | Low (when data exists) | Very High |

---

## 20. File Locations

### Backend Files

| File | Purpose |
|------|---------|
| `app/models/ticker.py` | ORM model |
| `app/schemas/ticker.py` | Pydantic schemas |
| `app/routers/ticker.py` | HTTP endpoints |
| `app/services/ticker_warehouse.py` | Data access layer |
| `app/backgroundtasks.py` | Background workers |

### Planned New Files

| File | Purpose |
|------|---------|
| `app/services/indicators.py` | Technical indicator calculations (RSI w/ Wilder smoothing, MACD, BB, ATR, VWMA, OBV) |
| `app/services/screener.py` | Screener logic with caching |
| `app/services/returns.py` | Multi-period returns (date-based lookups) |
| `app/services/momentum.py` | Momentum score calculation |
| `app/services/scanner.py` | Event scanner (post-EOD background job) |
| `app/services/patterns.py` | Candle pattern detection + range quality |
| `app/services/structure.py` | Price structure / swing point detection |
| `app/services/volume_profile.py` | Volume profile / POC computation |
| `app/services/notifications.py` | Notification dispatch |
| `app/routers/screener.py` | Screener endpoint |
| `app/routers/returns.py` | Returns endpoint |
| `app/routers/indicators.py` | Indicators endpoint |
| `app/routers/scanner.py` | Event scanner endpoint |

---

## 21. API Design Summary

### Existing Endpoints

| Endpoint | Returns |
|----------|--------|
| `GET /api/ticker/ohlcv/{symbol}` | OHLCV rows in date range |
| `GET /api/ticker/ohlcv/{symbol}/latest` | Single latest candle |
| `GET /api/ticker/status` | Warehouse statistics |
| `POST /api/ticker/trigger-backfill` | Trigger background backfill |
| `POST /api/ticker/trigger-daily-update` | Trigger background update |

### Proposed Endpoints

| Endpoint | Returns |
|----------|--------|
| `GET /api/ticker/returns/{symbol}` | Multi-period returns |
| `GET /api/ticker/returns-bulk` | Returns for multiple symbols |
| `GET /api/ticker/universe-returns` | Ranked returns heatmap |
| `GET /api/ticker/sector-returns` | Average + median returns by sector |
| `GET /api/ticker/screener` | Filtered symbol list (cached) |
| `GET /api/ticker/indicators/{symbol}` | Technical indicators (RSI, MACD, BB, ATR, VWMA, HV, OBV, Sharpe) |
| `GET /api/ticker/momentum-score/{symbol}` | Composite momentum score |
| `GET /api/ticker/momentum-leaderboard` | Top N by momentum score |
| `GET /api/ticker/gaps/{symbol}` | Gap analysis (intraday + close fill) |
| `GET /api/ticker/patterns/{symbol}` | Candle patterns + range quality |
| `GET /api/ticker/relative-strength/{symbol}` | RS spread + Mansfield RS vs index |
| `GET /api/ticker/peer-rank/{symbol}` | Intra-industry peer ranking |
| `GET /api/ticker/drawdowns/{symbol}` | Max drawdown + ATH drawdown |
| `GET /api/ticker/volume-profile/{symbol}` | POC, HVN, LVN |
| `POST /api/ticker/run-event-scan` | Trigger post-EOD event scanner |

---

## 22. Notes

- All period calculations assume ~252 trading days/year, ~21/month, ~5/week. Use date-based lookups throughout — row offsets break for halted/recently listed symbols.
- RSI: use Wilder's smoothing, warm up 28 bars minimum. MACD: do not serve for symbols with < 60 rows.
- VWAP is renamed VWMA throughout. Do not use the VWAP name for daily-bar calculations.
- Relative strength formula uses return spread or Mansfield, not ratio (ratio breaks on negative index returns).
- Gap fills are tracked separately as intraday fill (low touched prev_close) and close fill (close crossed prev_close).
- Screener results must be cached after daily update and invalidated on next update. Do not run full-universe screener per request.
- Correlation matrix: background job only, Nifty500 universe recommended, not full 2000+ symbol set.
- Volume profile: background job, weekly recompute sufficient.
- Momentum score weights (0.30 / 0.30 / 0.20 / 0.20) are a starting point — validate against forward returns and adjust.
- Delivery %: check bhavcopy source first; the data may already be available without schema changes.

---

*Document prepared for BLM Terminal. v1: 2026-04-11. v2: 2026-04-13.*