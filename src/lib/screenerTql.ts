/**
 * Ticker Query Language (TQL) — frontend tokenizer + autocomplete engine.
 *
 * The backend is authoritative; this module only tokenises the current query
 * to determine autocomplete context and produce suggestions.
 *
 * Syntax (mirrors backend tql_parser.py):
 *   FIELD OP VALUE
 *   FIELD IN (VALUE, ...)
 *   EXPR AND EXPR | EXPR OR EXPR | NOT EXPR | ( EXPR )
 *   Interval prefix: <interval>:FIELD  e.g.  1h:RSI > 60
 */

// ─── Field catalogue ─────────────────────────────────────────────────────────

export interface TqlValueExample {
  value: string;   // the literal to insert (no quotes)
  desc: string;    // shown as detail in the dropdown
}

export interface TqlField {
  name: string;
  /** One-line description shown in field autocomplete */
  desc: string;
  /** Extended explanation + scale shown in the hint bar when typing a value */
  hint: string;
  type: 'number' | 'string' | 'boolean';
  /** Whether this field accepts an interval prefix */
  supportsInterval?: boolean;
  /** Labelled example values — shown as suggestions when typing a value */
  valueExamples?: TqlValueExample[];
}

export const TQL_FIELDS: TqlField[] = [
  // ── Indicator fields (support interval prefix) ───────────────────────────
  {
    name: 'RSI', type: 'number', supportsInterval: true,
    desc: 'RSI(14) — momentum oscillator 0–100',
    hint: 'Relative Strength Index (14-period). Scale: 0–100. Below 30 = oversold, above 70 = overbought, 50 = neutral midline.',
    valueExamples: [
      { value: '30', desc: 'oversold threshold' },
      { value: '40', desc: 'weakening momentum' },
      { value: '50', desc: 'neutral midline' },
      { value: '60', desc: 'strengthening momentum' },
      { value: '70', desc: 'overbought threshold' },
    ],
  },
  {
    name: 'ATR', type: 'number', supportsInterval: true,
    desc: 'ATR % of price — volatility',
    hint: 'Average True Range expressed as % of price. Low-vol large-caps: 1–2%. Mid-cap active stocks: 2–4%. High-vol small-caps: 4%+.',
    valueExamples: [
      { value: '1',   desc: 'very low volatility' },
      { value: '2',   desc: 'low volatility (large-cap)' },
      { value: '3',   desc: 'moderate volatility' },
      { value: '5',   desc: 'high volatility' },
    ],
  },
  {
    name: 'MACD', type: 'number', supportsInterval: true,
    desc: 'MACD line (EMA12 − EMA26)',
    hint: 'MACD line = EMA(12) − EMA(26). Scale depends on stock price. Positive = bullish trend, negative = bearish trend. Cross above 0 is a classic buy signal.',
    valueExamples: [
      { value: '0', desc: 'zero-line crossover' },
    ],
  },
  {
    name: 'MACDSignal', type: 'number', supportsInterval: true,
    desc: 'MACD signal line — EMA(9) of MACD',
    hint: 'Signal line = EMA(9) of the MACD line. Compare against MACD: when MACD > MACDSignal the histogram is positive (bullish). Scale is price-dependent — use > 0 or < 0 for direction, or compare directly to MACD.',
    valueExamples: [
      { value: '0', desc: 'signal above/below zero' },
    ],
  },
  {
    name: 'MACDHist', type: 'number', supportsInterval: true,
    desc: 'MACD histogram (MACD − Signal)',
    hint: 'Histogram = MACD − Signal line. Positive = MACD above signal (bullish momentum building). Negative = MACD below signal. Widening histogram = accelerating trend.',
    valueExamples: [
      { value: '0', desc: 'histogram crosses zero' },
    ],
  },
  {
    name: 'BBWidth', type: 'number', supportsInterval: true,
    desc: 'Bollinger Band width %',
    hint: 'Band width as % of the middle band. Low width (< 5%) = price compression, potential breakout setup. High width (> 15%) = high volatility expansion.',
    valueExamples: [
      { value: '3',  desc: 'tight squeeze (< 3%)' },
      { value: '5',  desc: 'low compression' },
      { value: '10', desc: 'normal range' },
      { value: '15', desc: 'high expansion' },
    ],
  },
  {
    name: 'BBSqueeze', type: 'boolean', supportsInterval: true,
    desc: 'Bollinger Band squeeze — true/false',
    hint: 'Boolean flag. True when the bands are in a squeeze (low volatility contraction). Use: BBSqueeze  or  BBSqueeze = true',
    valueExamples: [],
  },
  {
    name: 'HV20', type: 'number', supportsInterval: true,
    desc: 'Historical volatility 20d (annualised %)',
    hint: 'Annualised historical volatility over 20 trading days. Low: < 20%. Medium: 20–40%. High: > 40%. Nifty50 stocks typically 15–35%.',
    valueExamples: [
      { value: '20', desc: 'low volatility' },
      { value: '30', desc: 'moderate' },
      { value: '40', desc: 'high volatility' },
    ],
  },
  {
    name: 'HV60', type: 'number', supportsInterval: true,
    desc: 'Historical volatility 60d (annualised %)',
    hint: 'Annualised historical volatility over 60 trading days. Smoother than HV20. Same scale: < 20% = calm, > 40% = volatile.',
    valueExamples: [
      { value: '20', desc: 'low' },
      { value: '30', desc: 'moderate' },
      { value: '40', desc: 'high' },
    ],
  },
  {
    name: 'Sharpe60', type: 'number', supportsInterval: true,
    desc: 'Sharpe ratio — 60d risk-adjusted return',
    hint: 'Risk-adjusted return over 60 trading days. > 1 = good, > 2 = excellent, < 0 = negative risk-adjusted return. Compares return to volatility.',
    valueExamples: [
      { value: '0',   desc: 'breakeven risk-adjusted' },
      { value: '0.5', desc: 'acceptable' },
      { value: '1',   desc: 'good' },
      { value: '2',   desc: 'excellent' },
    ],
  },
  {
    name: 'Sharpe126', type: 'number', supportsInterval: true,
    desc: 'Sharpe ratio — 126d (6-month)',
    hint: 'Risk-adjusted return over 126 trading days (~6 months). Same scale as Sharpe60 but smoother. > 1 = good performance relative to risk.',
    valueExamples: [
      { value: '0',   desc: 'breakeven' },
      { value: '0.5', desc: 'acceptable' },
      { value: '1',   desc: 'good' },
    ],
  },

  // ── Price / return fields ─────────────────────────────────────────────────
  {
    name: 'Change', type: 'number',
    desc: 'Today\'s % change (open → last)',
    hint: 'Intraday % change from open to last traded price. Typical range: −5% to +5%. Circuit-limit moves: ±10% or ±20%.',
    valueExamples: [
      { value: '-5',  desc: 'large down move' },
      { value: '-2',  desc: 'moderate decline' },
      { value: '0',   desc: 'flat' },
      { value: '2',   desc: 'moderate gain' },
      { value: '5',   desc: 'strong up move' },
    ],
  },
  {
    name: 'Volume', type: 'number',
    desc: 'Volume ratio (today ÷ 20-day avg)',
    hint: 'Today\'s volume divided by the 20-day average volume. 1.0 = average. > 2 = double avg volume (elevated interest). > 5 = very high volume surge.',
    valueExamples: [
      { value: '0.5', desc: 'below average' },
      { value: '1',   desc: 'average' },
      { value: '1.5', desc: 'above average' },
      { value: '2',   desc: 'double average' },
      { value: '5',   desc: 'volume surge' },
    ],
  },
  {
    name: 'Close', type: 'number',
    desc: 'Last traded price (₹)',
    hint: 'Last traded price in rupees. No normalised scale — depends on the stock.',
    valueExamples: [
      { value: '100',  desc: '₹100' },
      { value: '500',  desc: '₹500' },
      { value: '1000', desc: '₹1,000' },
    ],
  },
  {
    name: 'Return1w', type: 'number',
    desc: '1-week return %',
    hint: '% price change over the past 1 week. Typical: −3% to +3%. Strong movers: ±5–10%.',
    valueExamples: [
      { value: '-5', desc: 'weak week' },
      { value: '0',  desc: 'flat' },
      { value: '3',  desc: 'decent gain' },
      { value: '5',  desc: 'strong week' },
    ],
  },
  {
    name: 'Return1m', type: 'number',
    desc: '1-month return %',
    hint: '% price change over the past 1 month. Market average: ±2%. Outperformers: > 5%. Strong bull: > 10%.',
    valueExamples: [
      { value: '-10', desc: 'weak month' },
      { value: '0',   desc: 'flat' },
      { value: '5',   desc: 'solid gain' },
      { value: '10',  desc: 'strong month' },
      { value: '15',  desc: 'breakout month' },
    ],
  },
  {
    name: 'Return3m', type: 'number',
    desc: '3-month return %',
    hint: '% price change over the past 3 months. Market average: ±5%. Momentum stocks: > 15–20%.',
    valueExamples: [
      { value: '0',  desc: 'flat quarter' },
      { value: '10', desc: 'solid quarter' },
      { value: '20', desc: 'momentum' },
      { value: '30', desc: 'strong momentum' },
    ],
  },
  {
    name: 'Return6m', type: 'number',
    desc: '6-month return %',
    hint: '% price change over 6 months. Market average: ±8%. Strong momentum: > 20%.',
    valueExamples: [
      { value: '0',  desc: 'flat' },
      { value: '15', desc: 'solid' },
      { value: '25', desc: 'strong' },
      { value: '40', desc: 'exceptional' },
    ],
  },
  {
    name: 'Return1y', type: 'number',
    desc: '1-year return %',
    hint: '% price change over 1 year. Nifty average: ~10–15% per year. Outperformers: > 25%. Multibaggers: > 50%.',
    valueExamples: [
      { value: '0',  desc: 'flat year' },
      { value: '15', desc: 'market-rate return' },
      { value: '30', desc: 'outperformer' },
      { value: '50', desc: 'strong outperformer' },
    ],
  },
  {
    name: 'From52wHigh', type: 'number',
    desc: '% below 52-week high (usually ≤ 0)',
    hint: 'How far the stock is below its 52-week high, as a %. 0 = at the high. −5 = 5% below. −20 = 20% below. Use > −5 to find stocks near their highs.',
    valueExamples: [
      { value: '0',   desc: 'at 52w high' },
      { value: '-3',  desc: 'within 3% of high' },
      { value: '-5',  desc: 'within 5% of high' },
      { value: '-10', desc: 'within 10% of high' },
      { value: '-20', desc: 'within 20% of high' },
    ],
  },
  {
    name: 'From52wLow', type: 'number',
    desc: '% above 52-week low (≥ 0)',
    hint: 'How far the stock has risen from its 52-week low, as a %. 0 = at the low. 20 = 20% above the low. Use < 10 to find stocks near their lows.',
    valueExamples: [
      { value: '0',  desc: 'at 52w low' },
      { value: '5',  desc: 'just above low' },
      { value: '20', desc: '20% off low' },
      { value: '50', desc: 'well above low' },
    ],
  },
  {
    name: 'PE', type: 'number',
    desc: 'Price-to-earnings ratio',
    hint: 'P/E ratio. < 15 = cheap/value, 15–25 = fair value, > 30 = expensive/growth. Nifty trailing P/E is typically 18–24.',
    valueExamples: [
      { value: '10', desc: 'deep value' },
      { value: '15', desc: 'value territory' },
      { value: '20', desc: 'fair value' },
      { value: '30', desc: 'growth premium' },
      { value: '50', desc: 'high growth / expensive' },
    ],
  },
  {
    name: 'MomentumScore', type: 'number',
    desc: 'Composite momentum score 0–100',
    hint: 'Internal composite score combining multi-period returns, RSI, and volume. 0–100 scale. > 60 = good momentum, > 80 = strong momentum.',
    valueExamples: [
      { value: '40', desc: 'weak momentum' },
      { value: '60', desc: 'decent momentum' },
      { value: '70', desc: 'good momentum' },
      { value: '80', desc: 'strong momentum' },
    ],
  },
  {
    name: 'DataPoints', type: 'number',
    desc: 'Number of daily candles available',
    hint: 'How many daily candles exist in the database for this stock. 252 ≈ 1 year. Use > 200 to exclude recently listed stocks from results.',
    valueExamples: [
      { value: '60',  desc: '~3 months of data' },
      { value: '120', desc: '~6 months of data' },
      { value: '200', desc: '~10 months of data' },
      { value: '252', desc: '~1 full year' },
    ],
  },

  // ── String fields ─────────────────────────────────────────────────────────
  {
    name: 'Sector', type: 'string',
    desc: 'NSE sector name',
    hint: 'NSE sector classification. Use = for exact match or IN for multiple sectors. Tab to see available sectors.',
    valueExamples: [],
  },
  {
    name: 'Industry', type: 'string',
    desc: 'Industry sub-category (partial match)',
    hint: 'Industry sub-category within a sector. Partial match — "Private" matches "Private Sector Bank".',
    valueExamples: [],
  },
  {
    name: 'Symbol', type: 'string',
    desc: 'Ticker symbol',
    hint: 'NSE ticker symbol in uppercase. Example: Symbol = "RELIANCE"',
    valueExamples: [],
  },
];

export const TQL_FIELD_NAMES = TQL_FIELDS.map((f) => f.name);

export const VALID_INTERVALS = ['1d', '1h', 'W', 'M'];

// ─── Token types ─────────────────────────────────────────────────────────────

type TokType =
  | 'FIELD'
  | 'OP'
  | 'IN'
  | 'AND'
  | 'OR'
  | 'NOT'
  | 'LPAREN'
  | 'RPAREN'
  | 'COMMA'
  | 'STRING'
  | 'NUMBER'
  | 'BOOL'
  | 'PARTIAL'   // incomplete token at cursor
  | 'UNKNOWN';

interface Token {
  type: TokType;
  value: string;
  start: number;
  end: number;
}

// ─── Simple tokeniser ─────────────────────────────────────────────────────────

const KEYWORDS = new Set(['AND', 'OR', 'NOT', 'IN', 'TRUE', 'FALSE']);
const OPS = new Set(['>=', '<=', '!=', '>', '<', '=']);

function tokenise(text: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;

  while (i < text.length) {
    // skip whitespace
    if (/\s/.test(text[i])) { i++; continue; }

    // two-char operators
    if (i + 1 < text.length && OPS.has(text.slice(i, i + 2))) {
      const v = text.slice(i, i + 2);
      tokens.push({ type: 'OP', value: v, start: i, end: i + 2 });
      i += 2;
      continue;
    }

    // one-char operators
    if (OPS.has(text[i])) {
      tokens.push({ type: 'OP', value: text[i], start: i, end: i + 1 });
      i++;
      continue;
    }

    if (text[i] === '(') { tokens.push({ type: 'LPAREN', value: '(', start: i, end: i + 1 }); i++; continue; }
    if (text[i] === ')') { tokens.push({ type: 'RPAREN', value: ')', start: i, end: i + 1 }); i++; continue; }
    if (text[i] === ',') { tokens.push({ type: 'COMMA',  value: ',', start: i, end: i + 1 }); i++; continue; }

    // quoted string
    if (text[i] === '"' || text[i] === "'") {
      const q = text[i];
      const start = i;
      i++;
      let s = '';
      while (i < text.length && text[i] !== q) { s += text[i++]; }
      if (i < text.length) i++; // closing quote
      tokens.push({ type: 'STRING', value: s, start, end: i });
      continue;
    }

    // number
    if (/[-\d]/.test(text[i]) && (text[i] !== '-' || /\d/.test(text[i + 1] ?? ''))) {
      const start = i;
      let s = '';
      if (text[i] === '-') { s += text[i++]; }
      while (i < text.length && /[\d.]/.test(text[i])) { s += text[i++]; }
      tokens.push({ type: 'NUMBER', value: s, start, end: i });
      continue;
    }

    // identifier / keyword
    if (/[A-Za-z_]/.test(text[i])) {
      const start = i;
      let s = '';
      // allow colon and dot inside identifiers for interval-prefixed fields like "1h:RSI"
      while (i < text.length && /[A-Za-z0-9_:.]/.test(text[i])) { s += text[i++]; }
      const upper = s.toUpperCase();
      let type: TokType = 'FIELD';
      if (upper === 'AND') type = 'AND';
      else if (upper === 'OR') type = 'OR';
      else if (upper === 'NOT') type = 'NOT';
      else if (upper === 'IN') type = 'IN';
      else if (upper === 'TRUE' || upper === 'FALSE') type = 'BOOL';
      tokens.push({ type, value: s, start, end: i });
      continue;
    }

    // unknown
    tokens.push({ type: 'UNKNOWN', value: text[i], start: i, end: i + 1 });
    i++;
  }

  return tokens;
}

// ─── Autocomplete context detection ──────────────────────────────────────────

export type AutocompleteContext =
  | { kind: 'field'; prefix: string; intervalPrefix?: string }
  | { kind: 'operator'; field: string }
  | { kind: 'value'; field: string; partial: string }
  | { kind: 'logical' }
  | { kind: 'none' };

/**
 * Determine the autocomplete context given the full query text and cursor position.
 */
export function getContext(text: string, cursor: number): AutocompleteContext {
  const textToCursor = text.slice(0, cursor);
  const tokens = tokenise(textToCursor);

  if (tokens.length === 0) return { kind: 'field', prefix: '' };

  const last = tokens[tokens.length - 1];

  // Cursor is right after an identifier token?
  const inIdent = last.type === 'FIELD' && last.end === cursor;
  const partial = inIdent ? last.value : '';
  const before = inIdent ? tokens.slice(0, -1) : tokens;
  const lastTok = before.length > 0 ? before[before.length - 1] : null;
  const lastType = lastTok?.type ?? null;

  // Helper: find the field token that precedes the nearest IN keyword
  const findInField = (): string => {
    const inIdx = before.map((t) => t.type).lastIndexOf('IN');
    const ft = inIdx > 0 ? before[inIdx - 1] : null;
    return ft?.type === 'FIELD' ? ft.value : '';
  };

  // Inside IN ( ... ) list — LPAREN or COMMA before partial
  if (lastType === 'LPAREN' || lastType === 'COMMA') {
    // Only treat as value context if there was an IN keyword before the LPAREN
    const inIdx = before.map((t) => t.type).lastIndexOf('IN');
    if (inIdx >= 0) {
      return { kind: 'value', field: findInField(), partial };
    }
    // Otherwise plain ( after AND/OR — suggest field
    if (partial.includes(':')) {
      const [ivPart, fieldPart] = partial.split(':', 2);
      return { kind: 'field', prefix: fieldPart, intervalPrefix: ivPart };
    }
    return { kind: 'field', prefix: partial };
  }

  // After AND / OR / NOT / start of query → suggest field
  if (!lastTok || lastType === 'AND' || lastType === 'OR' || lastType === 'NOT') {
    if (partial.includes(':')) {
      const [ivPart, fieldPart] = partial.split(':', 2);
      return { kind: 'field', prefix: fieldPart, intervalPrefix: ivPart };
    }
    return { kind: 'field', prefix: partial };
  }

  // After a field → suggest operator (unless partial is being typed = more field)
  if (lastType === 'FIELD') {
    if (partial) {
      if (partial.includes(':')) {
        const [ivPart, fieldPart] = partial.split(':', 2);
        return { kind: 'field', prefix: fieldPart, intervalPrefix: ivPart };
      }
      return { kind: 'field', prefix: partial };
    }
    return { kind: 'operator', field: lastTok.value };
  }

  // After an operator → suggest value
  if (lastType === 'OP') {
    const fieldTok = before.length >= 2 ? before[before.length - 2] : null;
    const fieldName = fieldTok?.type === 'FIELD' ? fieldTok.value : '';
    return { kind: 'value', field: fieldName, partial };
  }

  // After a value (STRING / NUMBER / RPAREN / BOOL) → suggest AND/OR
  if (
    lastType === 'STRING' ||
    lastType === 'NUMBER' ||
    lastType === 'RPAREN' ||
    lastType === 'BOOL'
  ) {
    return { kind: 'logical' };
  }

  return { kind: 'field', prefix: partial };
}

// ─── Field info lookup ────────────────────────────────────────────────────────

/**
 * Return the field definition for the field currently being typed a value for.
 * Used by the widget to show a hint bar below the input.
 */
export function getFieldInfo(text: string, cursor: number): TqlField | null {
  const ctx = getContext(text, cursor);
  if (ctx.kind !== 'value' && ctx.kind !== 'operator') return null;
  const fieldLower = (ctx.field ?? '').toLowerCase().split(':').pop() ?? '';
  return TQL_FIELDS.find((f) => f.name.toLowerCase() === fieldLower) ?? null;
}

// ─── Suggestion generator ─────────────────────────────────────────────────────

export interface TqlSuggestion {
  label: string;
  /** What to insert at cursor (replaces partial) */
  insert: string;
  detail?: string;
  kind: 'field' | 'operator' | 'value' | 'keyword';
}

const OPERATORS: TqlSuggestion[] = [
  { label: '>', insert: '> ', detail: 'greater than', kind: 'operator' },
  { label: '<', insert: '< ', detail: 'less than', kind: 'operator' },
  { label: '>=', insert: '>= ', detail: 'greater than or equal', kind: 'operator' },
  { label: '<=', insert: '<= ', detail: 'less than or equal', kind: 'operator' },
  { label: '=', insert: '= ', detail: 'equal to', kind: 'operator' },
  { label: '!=', insert: '!= ', detail: 'not equal to', kind: 'operator' },
  { label: 'IN', insert: 'IN (', detail: 'one of list', kind: 'operator' },
];

const LOGICAL_KEYWORDS: TqlSuggestion[] = [
  { label: 'AND', insert: ' AND ', detail: 'both conditions', kind: 'keyword' },
  { label: 'OR',  insert: ' OR ',  detail: 'either condition', kind: 'keyword' },
];

/**
 * Generate autocomplete suggestions.
 *
 * @param text     Full query text
 * @param cursor   Cursor position (0-based character index)
 * @param sectors  Sector values fetched from /api/py/ticker/screener/sectors
 */
export function getSuggestions(
  text: string,
  cursor: number,
  sectors: string[],
): TqlSuggestion[] {
  const ctx = getContext(text, cursor);

  switch (ctx.kind) {
    case 'field': {
      const prefix = (ctx.prefix ?? '').toLowerCase();
      const results: TqlSuggestion[] = [];

      // If they've typed an interval prefix but no colon yet, suggest interval prefixes
      if (!prefix.includes(':') && VALID_INTERVALS.some((iv) => iv.toLowerCase().startsWith(prefix) && prefix.length > 0 && prefix.length < iv.length)) {
        for (const iv of VALID_INTERVALS) {
          if (iv.toLowerCase().startsWith(prefix)) {
            results.push({ label: `${iv}:`, insert: `${iv}:`, detail: `${iv} interval prefix`, kind: 'keyword' });
          }
        }
      }

      // Field names
      for (const f of TQL_FIELDS) {
        const fieldSearch = ctx.intervalPrefix
          ? f.name.toLowerCase()
          : f.name.toLowerCase();
        if (fieldSearch.startsWith(prefix)) {
          const insertName = ctx.intervalPrefix
            ? `${ctx.intervalPrefix}:${f.name} `
            : `${f.name} `;
          results.push({
            label: ctx.intervalPrefix ? `${ctx.intervalPrefix}:${f.name}` : f.name,
            insert: insertName,
            detail: f.desc,
            kind: 'field',
          });
        }
      }

      return results.slice(0, 12);
    }

    case 'operator': {
      const fieldLower = ctx.field.toLowerCase().split(':').pop() ?? '';
      const fieldDef = TQL_FIELDS.find((f) => f.name.toLowerCase() === fieldLower);
      if (fieldDef?.type === 'boolean') {
        // BBSqueeze doesn't need an operator — but we still offer = true/false
        return [
          { label: '= true', insert: '= true ', kind: 'operator' },
          { label: '= false', insert: '= false ', kind: 'operator' },
        ];
      }
      if (fieldDef?.type === 'string') {
        return [
          { label: '=', insert: '= "', detail: 'equal to', kind: 'operator' },
          { label: '!=', insert: '!= "', detail: 'not equal to', kind: 'operator' },
          { label: 'IN', insert: 'IN ("', detail: 'one of list', kind: 'operator' },
        ];
      }
      return OPERATORS;
    }

    case 'value': {
      const fieldLower = (ctx.field ?? '').toLowerCase().split(':').pop() ?? '';
      const partial = (ctx.partial ?? '').toLowerCase();

      const fieldDef = TQL_FIELDS.find((f) => f.name.toLowerCase() === fieldLower);

      // Boolean fields
      if (fieldDef?.type === 'boolean') {
        return [
          { label: 'true',  insert: 'true ',  detail: 'squeeze active',   kind: 'value' },
          { label: 'false', insert: 'false ', detail: 'squeeze not active', kind: 'value' },
        ];
      }

      // Sector — live values from API
      if (fieldLower === 'sector') {
        return sectors
          .filter((s) => s.toLowerCase().startsWith(partial))
          .map((s) => ({
            label: s,
            insert: `"${s}" `,
            detail: 'sector',
            kind: 'value' as const,
          }))
          .slice(0, 12);
      }

      // Symbol / Industry — user types freely
      if (fieldLower === 'symbol' || fieldLower === 'industry') {
        return [];
      }

      // Numeric fields — return labelled example values filtered by what's been typed
      if (fieldDef?.type === 'number' && fieldDef.valueExamples?.length) {
        return fieldDef.valueExamples
          .filter((ex) => ex.value.startsWith(partial) || partial === '')
          .map((ex) => ({
            label: ex.value,
            insert: `${ex.value} `,
            detail: ex.desc,
            kind: 'value' as const,
          }));
      }

      return [];
    }

    case 'logical':
      return LOGICAL_KEYWORDS;

    default:
      return [];
  }
}

// ─── Partial replacement helper ────────────────────────────────────────────────

/**
 * Apply a suggestion to the current query text.
 * Returns the new query string and new cursor position.
 */
export function applySuggestion(
  text: string,
  cursor: number,
  suggestion: TqlSuggestion,
): { text: string; cursor: number } {
  const tokens = tokenise(text.slice(0, cursor));
  const last = tokens[tokens.length - 1];

  let replaceStart = cursor;
  if (
    last &&
    last.end === cursor &&
    (last.type === 'FIELD' || last.type === 'UNKNOWN')
  ) {
    replaceStart = last.start;
  }

  const before = text.slice(0, replaceStart);
  const after = text.slice(cursor);
  const newText = before + suggestion.insert + after;
  const newCursor = replaceStart + suggestion.insert.length;

  return { text: newText, cursor: newCursor };
}

// ─── Query validation ─────────────────────────────────────────────────────────

export function validateTql(text: string): string | null {
  if (!text.trim()) return null;
  const tokens = tokenise(text);
  // Basic checks: no dangling operators
  if (tokens.length === 0) return null;
  const last = tokens[tokens.length - 1];
  if (last.type === 'OP' || last.type === 'AND' || last.type === 'OR' || last.type === 'NOT') {
    return 'Incomplete expression';
  }
  return null;
}
