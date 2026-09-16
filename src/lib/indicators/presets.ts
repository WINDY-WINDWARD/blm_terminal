/**
 * Indicator presets — TradingView-like defaults, clamp ranges, palette.
 * VWAP is session-based and meaningless on D/W/M (menu disables it there).
 */
import type { ActiveIndicator, IndicatorDef, IndicatorType } from './types';

/** Cap on VISIBLE indicators (chart footprint). Hidden entries persist as a library. */
export const MAX_INDICATORS = 6;

export const INDICATOR_DEFS: IndicatorDef[] = [
  { type: 'SMA', label: 'Moving Average (SMA)', pane: 'overlay', paramKeys: ['period'] },
  { type: 'EMA', label: 'Moving Average (EMA)', pane: 'overlay', paramKeys: ['period'] },
  { type: 'BB', label: 'Bollinger Bands', pane: 'overlay', paramKeys: ['period', 'mult'] },
  {
    type: 'VWAP', label: 'Session VWAP', pane: 'overlay', paramKeys: [],
    disabledOn: (iv) => iv === 'D' || iv === 'W' || iv === 'M',
    disabledReason: 'Session VWAP needs intraday sessions — hidden on D/W/M',
  },
  { type: 'VOLUME', label: 'Volume', pane: 'overlay', paramKeys: [] },
  { type: 'RSI', label: 'RSI', pane: 'oscillator', paramKeys: ['period'] },
  { type: 'MACD', label: 'MACD', pane: 'oscillator', paramKeys: ['fast', 'slow', 'signal'] },
  { type: 'STOCH', label: 'Stochastic', pane: 'oscillator', paramKeys: ['k', 'slowing', 'd'] },
  { type: 'ATR', label: 'ATR', pane: 'oscillator', paramKeys: ['period'] },
  { type: 'OBV', label: 'On-Balance Volume', pane: 'oscillator', paramKeys: [] },
];

/** Hard cap on stored entries (the library) — one per type, all 10 allowed. */
export const MAX_STORED_INDICATORS = INDICATOR_DEFS.length;

const DEFAULT_PARAMS: Record<IndicatorType, Record<string, number>> = {
  SMA: { period: 20 },
  EMA: { period: 20 },
  BB: { period: 20, mult: 2 },
  VWAP: {},
  VOLUME: {},
  RSI: { period: 14 },
  MACD: { fast: 12, slow: 26, signal: 9 },
  STOCH: { k: 14, slowing: 3, d: 3 },
  ATR: { period: 14 },
  OBV: {},
};

/** Inclusive clamp ranges shown as hints in the settings popovers. */
const PARAM_LIMITS: Record<string, { min: number; max: number; step: number }> = {
  period: { min: 2, max: 200, step: 1 },
  mult: { min: 0.5, max: 4, step: 0.1 },
  fast: { min: 2, max: 50, step: 1 },
  slow: { min: 5, max: 100, step: 1 },
  signal: { min: 2, max: 30, step: 1 },
  k: { min: 5, max: 30, step: 1 },
  slowing: { min: 1, max: 9, step: 1 },
  d: { min: 1, max: 9, step: 1 },
};

export function paramLimits(key: string): { min: number; max: number; step: number } {
  return PARAM_LIMITS[key] ?? { min: 1, max: 500, step: 1 };
}

const PALETTE = ['#FFB900', '#2962FF', '#00E5A0', '#FF6D00', '#B388FF', '#F23645'];

export function defaultParams(type: IndicatorType): Record<string, number> {
  return { ...DEFAULT_PARAMS[type] };
}

export function paletteColor(index: number): string {
  return PALETTE[index % PALETTE.length];
}

export function makeIndicator(type: IndicatorType, index: number): ActiveIndicator {
  return {
    id: `${type}-${Date.now().toString(36)}-${index}`,
    type,
    params: defaultParams(type),
    color: paletteColor(index),
    visible: true,
  };
}

/** Clamp unknown/corrupt persisted state back into a valid indicator list. */
export function clampIndicators(raw: unknown): ActiveIndicator[] {
  if (!Array.isArray(raw)) return [];
  const validTypes = new Set(INDICATOR_DEFS.map((d) => d.type));
  const out: ActiveIndicator[] = [];
  const seen = new Set<IndicatorType>();
  for (const item of raw.slice(0, MAX_STORED_INDICATORS)) {
    if (typeof item !== 'object' || item === null) continue;
    const rec = item as Record<string, unknown>;
    if (typeof rec.id !== 'string' || !validTypes.has(rec.type as IndicatorType)) continue;
    const type = rec.type as IndicatorType;
    if (seen.has(type)) continue; // one entry per type (checkbox menu)
    seen.add(type);
    const def = INDICATOR_DEFS.find((d) => d.type === type);
    const params: Record<string, number> = {};
    for (const key of def?.paramKeys ?? []) {
      const limits = paramLimits(key);
      const v = Number(rec.params && (rec.params as Record<string, unknown>)[key]);
      params[key] = Number.isFinite(v)
        ? Math.min(limits.max, Math.max(limits.min, v))
        : (DEFAULT_PARAMS[type][key] ?? limits.min);
    }
    out.push({
      id: rec.id,
      type,
      params,
      color: typeof rec.color === 'string' ? rec.color : paletteColor(out.length),
      visible: rec.visible !== false,
    });
  }
  return out;
}
