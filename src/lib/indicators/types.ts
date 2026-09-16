/** Indicator type system — frontend-only chart overlays (no backend dependency). */

export type IndicatorType =
  | 'SMA'
  | 'EMA'
  | 'BB'
  | 'VWAP'
  | 'VOLUME'
  | 'RSI'
  | 'MACD'
  | 'STOCH'
  | 'ATR'
  | 'OBV';

export type PaneKind = 'overlay' | 'oscillator';

export interface ActiveIndicator {
  id: string;
  type: IndicatorType;
  /** Tunable params, e.g. { period: 20 } — always clamped via presets. */
  params: Record<string, number>;
  color: string;
  visible: boolean;
}

export interface IndicatorDef {
  type: IndicatorType;
  label: string;
  pane: PaneKind;
  /** Param names this indicator accepts, in menu order. */
  paramKeys: string[];
  /** True when the indicator is meaningless on the given interval. */
  disabledOn?: (interval: string) => boolean;
  disabledReason?: string;
}

/** Single candle shape shared by daily + intraday pipelines (time = unix seconds). */
export interface IndicatorCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
