/**
 * BLM Script Lab v1 — shared types.
 * Normative spec: docs/specs/chart-scripts-v1.md
 */

export const SCRIPT_SPEC_VERSION = 1;
export const MAX_CODE_BYTES = 64 * 1024;
export const MAX_PARAMS = 24;
export const MAX_OUTPUTS = 8;
export const MAX_BARS_PER_RUN = 2000;
export const EXEC_TIMEOUT_MS = 2000;

export type ScriptParamType = 'int' | 'number' | 'bool' | 'select' | 'color' | 'source';
export type ScriptSourceValue =
  | 'open' | 'high' | 'low' | 'close' | 'hlc3' | 'hl2' | 'ohlc4' | 'volume';
export type ScriptOutputKind = 'line' | 'histogram' | 'markers' | 'priceline' | 'band';

export interface ScriptParam {
  key: string;
  label?: string;
  type: ScriptParamType;
  default: number | boolean | string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

export interface ScriptOutput {
  id: string;
  kind: ScriptOutputKind;
  overlay?: boolean;
  pane?: string;
  upper?: string;
  lower?: string;
  color?: string;
}

export interface ScriptManifest {
  name: string;
  version: number;
  description?: string;
  params?: ScriptParam[];
  outputs: ScriptOutput[];
  needs_fundamentals?: boolean;
}

export interface ScriptBar {
  time: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  live?: boolean;
}

export interface ScriptQuarterlyRow {
  period: string;
  sales?: number | null;
  opProfit?: number | null;
  netProfit?: number | null;
  eps?: number | null;
}

export interface ScriptRatios {
  pe?: number | null;
  roe?: number | null;
  roce?: number | null;
  marketCapCr?: number | null;
}

export interface ScriptFundamentals {
  quarterly: ScriptQuarterlyRow[];
  ratios: ScriptRatios;
}

export interface ScriptCtx {
  bars: ScriptBar[];
  params: Record<string, number | boolean | string>;
  fundamentals?: ScriptFundamentals;
  symbol: string;
  exchange: string;
  interval: string;
}

export interface ScriptMarker {
  pos: 'aboveBar' | 'belowBar';
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text?: string;
  color?: string;
}

export type ScriptSeriesValues = (number | null | ScriptLinePoint)[];

/** Per-bar line point: value + optional segment color (#rrggbb). */
export interface ScriptLinePoint {
  value: number | null;
  color?: string;
}
export type ScriptMarkerValues = ScriptMarker[][];

export type ScriptOutputValues =
  | ScriptSeriesValues
  | ScriptMarkerValues
  | number;

export interface ScriptRunOk {
  ok: true;
  values: Record<string, ScriptOutputValues>;
  stats: { bars: number; ms: number };
}

export interface ScriptRunError {
  ok: false;
  code: string;
  message: string;
  line?: number;
}

export type ScriptRunResult = ScriptRunOk | ScriptRunError;

export interface ScriptValidation {
  valid: boolean;
  errors: string[];
  manifest: ScriptManifest | null;
  stats?: { bars: number; ms: number; outputs: string[] };
}

export interface SavedScriptSummary {
  id: number;
  name: string;
  description: string;
  is_builtin: boolean;
  head_rev_no: number | null;
  updated_at: string | null;
}

export interface ScriptRevisionData {
  rev_no: number;
  manifest: ScriptManifest;
  code: string;
  note: string;
  chat_session_id: number | null;
  created_at: string | null;
}

export interface SavedScriptDetail extends SavedScriptSummary {
  head: ScriptRevisionData | null;
  history: ScriptRevisionData[];
}

export interface ScriptChartSlot {
  script_id: number;
  enabled: boolean;
  param_values: Record<string, number | boolean | string>;
  name: string;
  head_rev_no: number | null;
}
