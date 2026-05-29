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

export interface TqlField {
  name: string;
  desc: string;
  type: 'number' | 'string' | 'boolean';
  /** Hint shown in autocomplete detail */
  example?: string;
  /** Whether this field accepts an interval prefix */
  supportsInterval?: boolean;
}

export const TQL_FIELDS: TqlField[] = [
  // Indicator fields (support interval prefix)
  { name: 'RSI',          desc: 'RSI(14)',                          type: 'number',  example: 'RSI > 60',                supportsInterval: true },
  { name: 'ATR',          desc: 'ATR % of price',                   type: 'number',  example: 'ATR < 3',                 supportsInterval: true },
  { name: 'MACD',         desc: 'MACD line',                        type: 'number',  example: 'MACD > 0',                supportsInterval: true },
  { name: 'MACDSignal',   desc: 'MACD signal line',                 type: 'number',  example: 'MACDSignal > 0',          supportsInterval: true },
  { name: 'MACDHist',     desc: 'MACD histogram',                   type: 'number',  example: 'MACDHist > 0',            supportsInterval: true },
  { name: 'BBWidth',      desc: 'Bollinger Band width',             type: 'number',  example: 'BBWidth < 5',             supportsInterval: true },
  { name: 'BBSqueeze',    desc: 'Bollinger Band squeeze (boolean)', type: 'boolean', example: 'BBSqueeze',               supportsInterval: true },
  { name: 'HV20',         desc: 'Historical volatility 20d',        type: 'number',  example: 'HV20 < 30',              supportsInterval: true },
  { name: 'HV60',         desc: 'Historical volatility 60d',        type: 'number',  example: 'HV60 < 25',              supportsInterval: true },
  { name: 'Sharpe60',     desc: 'Sharpe ratio 60d',                 type: 'number',  example: 'Sharpe60 > 1',           supportsInterval: true },
  { name: 'Sharpe126',    desc: 'Sharpe ratio 126d',                type: 'number',  example: 'Sharpe126 > 0.8',        supportsInterval: true },
  // Price / return fields (no interval)
  { name: 'Change',       desc: 'Today\'s % change',               type: 'number',  example: 'Change > 2' },
  { name: 'Volume',       desc: 'Volume ratio (today / avg 20d)',   type: 'number',  example: 'Volume > 2' },
  { name: 'Close',        desc: 'Last traded price',                type: 'number',  example: 'Close > 500' },
  { name: 'Return1w',     desc: '1-week return %',                  type: 'number',  example: 'Return1w > 5' },
  { name: 'Return1m',     desc: '1-month return %',                 type: 'number',  example: 'Return1m > 10' },
  { name: 'Return3m',     desc: '3-month return %',                 type: 'number',  example: 'Return3m > 15' },
  { name: 'Return6m',     desc: '6-month return %',                 type: 'number',  example: 'Return6m > 20' },
  { name: 'Return1y',     desc: '1-year return %',                  type: 'number',  example: 'Return1y > 30' },
  { name: 'From52wHigh',  desc: '% below 52-week high (negative)',  type: 'number',  example: 'From52wHigh > -5' },
  { name: 'From52wLow',   desc: '% above 52-week low',             type: 'number',  example: 'From52wLow > 20' },
  { name: 'PE',           desc: 'Price / earnings ratio',           type: 'number',  example: 'PE < 30' },
  { name: 'MomentumScore',desc: 'Composite momentum score',         type: 'number',  example: 'MomentumScore > 70' },
  { name: 'Sector',       desc: 'Sector name',                      type: 'string',  example: 'Sector = "Banks"' },
  { name: 'Industry',     desc: 'Industry (partial match)',          type: 'string',  example: 'Industry = "Private"' },
  { name: 'Symbol',       desc: 'Ticker symbol',                    type: 'string',  example: 'Symbol = "RELIANCE"' },
  { name: 'DataPoints',   desc: 'Number of available data points',  type: 'number',  example: 'DataPoints > 200' },
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

const STRING_VALUE_FIELDS = new Set(['sector', 'industry', 'symbol']);

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

      if (STRING_VALUE_FIELDS.has(fieldLower) && fieldLower === 'sector') {
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

      if (fieldLower === 'symbol') {
        // no suggestions for symbol — user types it
        return [];
      }

      // boolean field values
      const fieldDef = TQL_FIELDS.find((f) => f.name.toLowerCase() === fieldLower);
      if (fieldDef?.type === 'boolean') {
        return [
          { label: 'true',  insert: 'true ',  kind: 'value' },
          { label: 'false', insert: 'false ', kind: 'value' },
        ];
      }

      // numeric — no value suggestions (free text)
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
