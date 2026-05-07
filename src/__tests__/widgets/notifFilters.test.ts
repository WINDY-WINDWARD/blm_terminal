/**
 * Tests for NotifWidget and ScanWidget sub-filter logic.
 *
 * Covers:
 *  - parseStreakDays — message parsing for streak numeric filter
 *  - coarse tab filter (TAB_TRIGGERS)
 *  - sub-filter bubble multi-select (OR logic)
 *  - streak numeric filter (≥ N days, floor = 5)
 *  - combined filter pipeline
 */

import { describe, it, expect } from 'vitest';
import { parseStreakDays } from '@/components/widgets/NotifWidget';

// ─── Mirror the constants from the widgets so tests don't depend on internals ──

const TAB_TRIGGERS: Record<string, string[]> = {
  all: [],
  breakout: ['52w_high_breakout', '52w_low_breakout', 'near_52w_high', 'near_52w_low'],
  volume: ['volume_breakout'],
  movers: ['top_gainer', 'top_loser'],
  deals: ['bulk_deal', 'block_deal', 'short_deal'],
  insider: ['insider_buy', 'insider_sell'],
  technical: [
    'rsi_oversold',
    'rsi_overbought',
    'macd_bullish_cross',
    'macd_bearish_cross',
    'bb_squeeze_alert',
    'bb_upper_break',
    'bb_lower_break',
  ],
  momentum: ['momentum_surge', 'return_1w_spike'],
  volatility: ['volatility_spike', 'atr_expansion'],
  streaks: ['streak_up_5d', 'streak_down_5d'],
  results: ['results_upcoming'],
};

const STREAK_TRIGGER_TYPES = new Set(['streak_up_5d', 'streak_down_5d']);
const STREAK_MIN = 5;

/** Mirrors the filtering pipeline from NotifWidget / ScanWidget */
function applyFilters(
  notifications: Array<{ trigger_type: string; message: string; symbol?: string }>,
  opts: {
    activeTab: string;
    activeSubFilters: string[];
    streakMinDays: number;
    symbolQuery?: string;
  },
) {
  const { activeTab, activeSubFilters, streakMinDays, symbolQuery } = opts;
  return notifications.filter((n) => {
    // Coarse tab filter
    if (activeTab !== 'all' && !TAB_TRIGGERS[activeTab]?.includes(n.trigger_type)) return false;
    // Sub-filter bubbles (OR — match any selected type)
    if (activeSubFilters.length > 0 && !activeSubFilters.includes(n.trigger_type)) return false;
    // Streak numeric filter
    if (STREAK_TRIGGER_TYPES.has(n.trigger_type) && streakMinDays > STREAK_MIN) {
      const days = parseStreakDays(n.message);
      if (days === null || days < streakMinDays) return false;
    }
    // Symbol search (ScanWidget)
    if (symbolQuery && !n.symbol?.toUpperCase().includes(symbolQuery.toUpperCase())) return false;
    return true;
  });
}

// ─── Test data fixtures ───────────────────────────────────────────────────────

const NOTIFICATIONS = [
  { trigger_type: 'rsi_oversold', message: 'INFY RSI 28 oversold', symbol: 'INFY' },
  { trigger_type: 'rsi_overbought', message: 'TCS RSI 72 overbought', symbol: 'TCS' },
  { trigger_type: 'macd_bullish_cross', message: 'RELIANCE MACD cross', symbol: 'RELIANCE' },
  { trigger_type: 'streak_up_5d', message: 'HDFC up 5 consecutive days', symbol: 'HDFC' },
  { trigger_type: 'streak_up_5d', message: 'WIPRO up 8 consecutive days', symbol: 'WIPRO' },
  { trigger_type: 'streak_down_5d', message: 'ITC down 7 consecutive days', symbol: 'ITC' },
  { trigger_type: 'streak_down_5d', message: 'BAJAJ down 5 days', symbol: 'BAJAJ' },
  { trigger_type: '52w_high_breakout', message: 'SBIN 52W high', symbol: 'SBIN' },
  { trigger_type: 'volume_breakout', message: 'TITAN volume surge', symbol: 'TITAN' },
  { trigger_type: 'results_upcoming', message: 'HDFCBANK results upcoming', symbol: 'HDFCBANK' },
];

// ─── parseStreakDays ──────────────────────────────────────────────────────────

describe('parseStreakDays', () => {
  it('parses "up N consecutive days" format (watchlist notif)', () => {
    expect(parseStreakDays('RELIANCE up 7 consecutive days')).toBe(7);
    expect(parseStreakDays('HDFC up 5 consecutive days')).toBe(5);
    expect(parseStreakDays('WIPRO up 12 consecutive days')).toBe(12);
  });

  it('parses "down N consecutive days" format', () => {
    expect(parseStreakDays('ITC down 7 consecutive days')).toBe(7);
    expect(parseStreakDays('BAJAJ down 5 consecutive days')).toBe(5);
  });

  it('parses "up N days" short format (global scan notif)', () => {
    expect(parseStreakDays('SBIN up 6 days')).toBe(6);
    expect(parseStreakDays('TCS down 5 days')).toBe(5);
  });

  it('handles case-insensitive direction words', () => {
    expect(parseStreakDays('INFY UP 9 consecutive days')).toBe(9);
    expect(parseStreakDays('HCL DOWN 6 days')).toBe(6);
  });

  it('returns null for unparseable messages', () => {
    expect(parseStreakDays('RELIANCE RSI oversold')).toBeNull();
    expect(parseStreakDays('')).toBeNull();
    expect(parseStreakDays('no numbers here')).toBeNull();
  });

  it('returns null for messages with numbers but wrong format', () => {
    // "3x above 20-day average" should not match
    expect(parseStreakDays('TITAN volume 3x above 20-day average')).toBeNull();
  });
});

// ─── Coarse tab filter ────────────────────────────────────────────────────────

describe('coarse tab filter', () => {
  it('"all" tab passes every notification', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'all',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(NOTIFICATIONS.length);
  });

  it('"technical" tab shows only technical trigger types', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'technical',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result.map((n) => n.trigger_type)).toEqual([
      'rsi_oversold',
      'rsi_overbought',
      'macd_bullish_cross',
    ]);
  });

  it('"streaks" tab shows only streak trigger types', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'streaks',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(4);
    expect(result.every((n) => STREAK_TRIGGER_TYPES.has(n.trigger_type))).toBe(true);
  });

  it('"breakout" tab shows 52W types only', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'breakout',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(1);
    expect(result[0].trigger_type).toBe('52w_high_breakout');
  });

  it('"results" tab shows results_upcoming only', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'results',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(1);
    expect(result[0].trigger_type).toBe('results_upcoming');
  });
});

// ─── Sub-filter bubble (multi-select OR) ─────────────────────────────────────

describe('sub-filter bubbles', () => {
  it('no sub-filters selected — shows all for the tab', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'technical',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(3); // rsi_oversold, rsi_overbought, macd_bullish_cross
  });

  it('single sub-filter narrows to only that type', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'technical',
      activeSubFilters: ['rsi_oversold'],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(1);
    expect(result[0].trigger_type).toBe('rsi_oversold');
  });

  it('multiple sub-filters use OR logic (shows any matching type)', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'technical',
      activeSubFilters: ['rsi_oversold', 'macd_bullish_cross'],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(2);
    expect(result.map((n) => n.trigger_type).sort()).toEqual([
      'macd_bullish_cross',
      'rsi_oversold',
    ]);
  });

  it('sub-filters on "all" tab work across all categories', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'all',
      activeSubFilters: ['rsi_oversold', 'volume_breakout'],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(2);
    const types = result.map((n) => n.trigger_type);
    expect(types).toContain('rsi_oversold');
    expect(types).toContain('volume_breakout');
  });

  it('sub-filter for a type not in active tab returns empty (impossible selection guard)', () => {
    // If user somehow selects a non-technical type while on technical tab,
    // the coarse tab filter removes it before sub-filter runs
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'technical',
      activeSubFilters: ['volume_breakout'], // not in technical tab
      streakMinDays: 5,
    });
    expect(result).toHaveLength(0);
  });

  it('streak sub-filters on all tab show only streak types', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'all',
      activeSubFilters: ['streak_up_5d', 'streak_down_5d'],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(4);
    expect(result.every((n) => STREAK_TRIGGER_TYPES.has(n.trigger_type))).toBe(true);
  });
});

// ─── Streak numeric filter ────────────────────────────────────────────────────

describe('streak numeric filter', () => {
  const streakNotifs = NOTIFICATIONS.filter((n) => STREAK_TRIGGER_TYPES.has(n.trigger_type));

  it('streakMinDays = 5 (default floor) — passes all streak notifications', () => {
    const result = applyFilters(streakNotifs, {
      activeTab: 'streaks',
      activeSubFilters: [],
      streakMinDays: 5,
    });
    expect(result).toHaveLength(4); // 5-day HDFC, 8-day WIPRO, 7-day ITC, 5-day BAJAJ
  });

  it('streakMinDays = 6 — filters out exactly-5-day streaks', () => {
    const result = applyFilters(streakNotifs, {
      activeTab: 'streaks',
      activeSubFilters: [],
      streakMinDays: 6,
    });
    // HDFC (5 days) and BAJAJ (5 days) excluded
    expect(result).toHaveLength(2);
    const symbols = result.map((n) => n.symbol);
    expect(symbols).toContain('WIPRO'); // 8 days
    expect(symbols).toContain('ITC');   // 7 days
    expect(symbols).not.toContain('HDFC');
    expect(symbols).not.toContain('BAJAJ');
  });

  it('streakMinDays = 8 — only 8-day+ streaks pass', () => {
    const result = applyFilters(streakNotifs, {
      activeTab: 'streaks',
      activeSubFilters: [],
      streakMinDays: 8,
    });
    expect(result).toHaveLength(1);
    expect(result[0].symbol).toBe('WIPRO');
  });

  it('streakMinDays = 10 — no notifications pass', () => {
    const result = applyFilters(streakNotifs, {
      activeTab: 'streaks',
      activeSubFilters: [],
      streakMinDays: 10,
    });
    expect(result).toHaveLength(0);
  });

  it('streak filter is skipped for non-streak trigger types', () => {
    // Mixing technical with streak notifs on "all" tab with high streakMinDays
    // — technical notifications should NOT be filtered by the streak day count
    const mixed = [
      { trigger_type: 'rsi_oversold', message: 'INFY RSI oversold', symbol: 'INFY' },
      { trigger_type: 'streak_up_5d', message: 'WIPRO up 8 consecutive days', symbol: 'WIPRO' },
      { trigger_type: 'streak_up_5d', message: 'HDFC up 5 consecutive days', symbol: 'HDFC' },
    ];
    const result = applyFilters(mixed, {
      activeTab: 'all',
      activeSubFilters: [],
      streakMinDays: 7,
    });
    // rsi_oversold passes (not a streak type)
    // WIPRO (8 days) passes
    // HDFC (5 days) fails (5 < 7)
    expect(result).toHaveLength(2);
    const symbols = result.map((n) => n.symbol);
    expect(symbols).toContain('INFY');
    expect(symbols).toContain('WIPRO');
    expect(symbols).not.toContain('HDFC');
  });

  it('streak filter also applies when streak type is in sub-filter on all tab', () => {
    const mixed = [
      { trigger_type: 'streak_up_5d', message: 'WIPRO up 8 consecutive days', symbol: 'WIPRO' },
      { trigger_type: 'streak_up_5d', message: 'HDFC up 5 consecutive days', symbol: 'HDFC' },
      { trigger_type: 'rsi_oversold', message: 'INFY RSI oversold', symbol: 'INFY' },
    ];
    const result = applyFilters(mixed, {
      activeTab: 'all',
      activeSubFilters: ['streak_up_5d'],
      streakMinDays: 7,
    });
    // Sub-filter keeps only streak_up_5d; streak filter then removes HDFC (5 < 7)
    expect(result).toHaveLength(1);
    expect(result[0].symbol).toBe('WIPRO');
  });
});

// ─── Streak stepper floor enforcement ────────────────────────────────────────

describe('streak stepper floor (STREAK_MIN = 5)', () => {
  it('STREAK_MIN constant is 5', () => {
    expect(STREAK_MIN).toBe(5);
  });

  it('Math.max(STREAK_MIN, x) never goes below 5', () => {
    // This is the logic used in onStreakMinDaysChange handler
    const clamp = (x: number) => Math.max(STREAK_MIN, x);
    expect(clamp(5)).toBe(5);
    expect(clamp(4)).toBe(5); // would-be decrement below floor
    expect(clamp(1)).toBe(5);
    expect(clamp(0)).toBe(5);
    expect(clamp(6)).toBe(6);
    expect(clamp(10)).toBe(10);
  });
});

// ─── Symbol search filter (ScanWidget) ───────────────────────────────────────

describe('symbol search filter', () => {
  it('filters by symbol prefix (case-insensitive)', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'all',
      activeSubFilters: [],
      streakMinDays: 5,
      symbolQuery: 'inf',
    });
    expect(result).toHaveLength(1);
    expect(result[0].symbol).toBe('INFY');
  });

  it('empty symbol query returns all', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'all',
      activeSubFilters: [],
      streakMinDays: 5,
      symbolQuery: '',
    });
    expect(result).toHaveLength(NOTIFICATIONS.length);
  });

  it('symbol filter works with tab filter combined', () => {
    const result = applyFilters(NOTIFICATIONS, {
      activeTab: 'streaks',
      activeSubFilters: [],
      streakMinDays: 5,
      symbolQuery: 'WIPRO',
    });
    expect(result).toHaveLength(1);
    expect(result[0].symbol).toBe('WIPRO');
  });
});

// ─── Full pipeline (tab + sub-filter + streak + symbol) ──────────────────────

describe('combined filter pipeline', () => {
  it('applies all filters in correct order', () => {
    const notifs = [
      { trigger_type: 'rsi_oversold', message: 'INFY RSI oversold', symbol: 'INFY' },
      { trigger_type: 'rsi_overbought', message: 'WIPRO RSI overbought', symbol: 'WIPRO' },
      { trigger_type: 'streak_up_5d', message: 'HDFC up 8 consecutive days', symbol: 'HDFC' },
      { trigger_type: 'streak_up_5d', message: 'SBIN up 5 consecutive days', symbol: 'SBIN' },
      { trigger_type: '52w_high_breakout', message: 'TCS 52W high', symbol: 'TCS' },
    ];
    // Tab: technical — sub-filter: rsi_oversold — streak: N/A — symbol: INFY
    const result = applyFilters(notifs, {
      activeTab: 'technical',
      activeSubFilters: ['rsi_oversold'],
      streakMinDays: 5,
      symbolQuery: 'INFY',
    });
    expect(result).toHaveLength(1);
    expect(result[0].symbol).toBe('INFY');
    expect(result[0].trigger_type).toBe('rsi_oversold');
  });

  it('streak filter + sub-filter on all tab, symbol search', () => {
    const notifs = [
      { trigger_type: 'streak_up_5d', message: 'WIPRO up 9 consecutive days', symbol: 'WIPRO' },
      { trigger_type: 'streak_up_5d', message: 'HDFC up 5 consecutive days', symbol: 'HDFC' },
      { trigger_type: 'streak_down_5d', message: 'BAJAJ down 7 consecutive days', symbol: 'BAJAJ' },
      { trigger_type: 'rsi_oversold', message: 'INFY RSI', symbol: 'INFY' },
    ];
    const result = applyFilters(notifs, {
      activeTab: 'all',
      activeSubFilters: ['streak_up_5d'],
      streakMinDays: 7,
      symbolQuery: 'WI',
    });
    // Sub-filter: only streak_up_5d
    // Streak: ≥ 7 days → HDFC (5) excluded
    // Symbol: WI → only WIPRO matches
    expect(result).toHaveLength(1);
    expect(result[0].symbol).toBe('WIPRO');
  });
});
