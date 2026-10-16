import { describe, it, expect } from 'vitest';
import {
  parseTradingViewList,
  normalizeSymbolToken,
  resolveImportPreview,
  buildImportPayload,
} from '../../lib/tradingviewImport';

describe('TradingView Watchlist Import Parser and Normalizer', () => {
  it('parses the canonical live TradingView fixture (8 NSE symbols)', () => {
    const input = 'NSE:IDBI,NSE:TMPV,NSE:IDFCFIRSTB,NSE:RELIANCE,NSE:HDFCBANK,NSE:ICICIBANK,NSE:WAAREEENER,NSE:ADANIENT';
    const result = parseTradingViewList(input);

    expect(result.summary.totalParsed).toBe(8);
    expect(result.summary.validNse).toBe(8);
    expect(result.summary.duplicates).toBe(0);
    expect(result.summary.unsupported).toBe(0);
    expect(result.summary.sectionsCount).toBe(1);

    const symbols = result.items.map((i) => i.symbol);
    expect(symbols).toEqual([
      'IDBI',
      'TMPV',
      'IDFCFIRSTB',
      'RELIANCE',
      'HDFCBANK',
      'ICICIBANK',
      'WAAREEENER',
      'ADANIENT',
    ]);

    expect(result.items.every((i) => i.isValidNse && i.selected && i.exchange === 'NSE')).toBe(true);
  });

  it('handles UTF-8 BOM, CRLF, and mixed delimiters (newlines, commas, tabs, semicolons)', () => {
    const input = '\uFEFFNSE:IDBI\r\nNSE:TMPV; NSE:IDFCFIRSTB\tNSE:RELIANCE\nNSE:HDFCBANK';
    const result = parseTradingViewList(input);

    expect(result.summary.totalParsed).toBe(5);
    expect(result.summary.validNse).toBe(5);
    expect(result.items.map((i) => i.symbol)).toEqual([
      'IDBI',
      'TMPV',
      'IDFCFIRSTB',
      'RELIANCE',
      'HDFCBANK',
    ]);
  });

  it('normalizes bare symbols and Yahoo-style .NS suffixes to NSE', () => {
    const input = 'RELIANCE\nTCS.NS\ninfy\nBAJAJ-AUTO.ns';
    const result = parseTradingViewList(input);

    expect(result.summary.validNse).toBe(4);
    expect(result.items[0]).toMatchObject({ symbol: 'RELIANCE', exchange: 'NSE', isValidNse: true });
    expect(result.items[1]).toMatchObject({ symbol: 'TCS', exchange: 'NSE', isValidNse: true });
    expect(result.items[2]).toMatchObject({ symbol: 'INFY', exchange: 'NSE', isValidNse: true });
    expect(result.items[3]).toMatchObject({ symbol: 'BAJAJ-AUTO', exchange: 'NSE', isValidNse: true });
  });

  it('strips -EQ series suffix while preserving hyphens in symbol names', () => {
    const input = 'NSE:RELIANCE-EQ, BAJAJ-AUTO-EQ, NAM-INDIA';
    const result = parseTradingViewList(input);

    expect(result.items.map((i) => i.symbol)).toEqual(['RELIANCE', 'BAJAJ-AUTO', 'NAM-INDIA']);
    expect(result.items.every((i) => i.isValidNse)).toBe(true);
  });

  it('flags unsupported exchanges such as BSE, NASDAQ, and crypto', () => {
    const input = 'NSE:RELIANCE, BSE:500325, TCS.BO, NASDAQ:AAPL, BINANCE:BTCUSDT';
    const result = parseTradingViewList(input);

    expect(result.summary.totalParsed).toBe(5);
    expect(result.summary.validNse).toBe(1);
    expect(result.summary.unsupported).toBe(4);

    const reliance = result.items.find((i) => i.symbol === 'RELIANCE');
    expect(reliance?.isValidNse).toBe(true);
    expect(reliance?.selected).toBe(true);

    const bse = result.items.find((i) => i.symbol === '500325');
    expect(bse?.isValidNse).toBe(false);
    expect(bse?.exchange).toBe('BSE');
    expect(bse?.selected).toBe(false);

    const tcsBo = result.items.find((i) => i.symbol === 'TCS' && i.exchange === 'BSE');
    expect(tcsBo?.isValidNse).toBe(false);

    const nasdaq = result.items.find((i) => i.symbol === 'AAPL');
    expect(nasdaq?.isValidNse).toBe(false);
    expect(nasdaq?.exchange).toBe('NASDAQ');
  });

  it('scopes duplicate detection within each section in parser', () => {
    const input = `
### NIFTY50
NSE:RELIANCE
NSE:RELIANCE
### LARGE CAP
NSE:RELIANCE
NSE:TCS
`;
    const result = parseTradingViewList(input);

    expect(result.sections.length).toBe(2);
    // In section 1, second RELIANCE is a duplicate
    expect(result.sections[0].items[0].isDuplicate).toBe(false);
    expect(result.sections[0].items[1].isDuplicate).toBe(true);

    // In section 2, RELIANCE is NOT a duplicate within section 2
    expect(result.sections[1].items[0].isDuplicate).toBe(false);
    expect(result.sections[1].items[1].isDuplicate).toBe(false);

    expect(result.summary.duplicates).toBe(1);
    expect(result.summary.validNse).toBe(3);
  });
});

describe('TradingView Import Preview Resolver', () => {
  it('deduplicates across sections in flat/merge mode', () => {
    const input = `
### SECTION 1
NSE:RELIANCE
NSE:TCS
### SECTION 2
NSE:RELIANCE
NSE:INFY
`;
    const parsed = parseTradingViewList(input);
    const resolved = resolveImportPreview(parsed, {
      mode: 'create',
      splitSections: false,
    });

    expect(resolved.summary.readyToImport).toBe(3); // RELIANCE, TCS, INFY
    expect(resolved.summary.duplicates).toBe(1); // Second RELIANCE in flat mode
    expect(resolved.canSubmit).toBe(true);

    const relianceItems = resolved.items.filter((i) => i.symbol === 'RELIANCE');
    expect(relianceItems[0].status).toBe('valid');
    expect(relianceItems[0].isPlannedForImport).toBe(true);
    expect(relianceItems[1].status).toBe('duplicate');
    expect(relianceItems[1].isPlannedForImport).toBe(false);
  });

  it('preserves section symbols independently in split mode and counts valid non-empty sections', () => {
    const input = `
### BANKING
NSE:HDFCBANK
NSE:ICICIBANK
### IT
NSE:TCS
NSE:INFY
### EMPTY SECTION
BSE:500325
`;
    const parsed = parseTradingViewList(input);
    const resolved = resolveImportPreview(parsed, {
      mode: 'create',
      splitSections: true,
    });

    expect(resolved.summary.readyToImport).toBe(4);
    // BANKING and IT have valid symbols; EMPTY SECTION only has BSE so 0 valid symbols
    expect(resolved.summary.validSectionsCount).toBe(2);
    expect(resolved.sections[0].validCount).toBe(2);
    expect(resolved.sections[1].validCount).toBe(2);
    expect(resolved.sections[2].validCount).toBe(0);
    expect(resolved.canSubmit).toBe(true);
  });

  it('checks target watchlist existing symbols in append mode', () => {
    const input = 'NSE:RELIANCE, NSE:TCS, NSE:INFY';
    const parsed = parseTradingViewList(input);

    const resolved = resolveImportPreview(parsed, {
      mode: 'append',
      splitSections: false,
      targetWatchlistExistingSymbols: ['RELIANCE'],
      targetWatchlistCurrentCount: 10,
    });

    expect(resolved.summary.readyToImport).toBe(2); // TCS, INFY
    expect(resolved.summary.alreadyInTarget).toBe(1); // RELIANCE
    expect(resolved.canSubmit).toBe(true);

    const reliance = resolved.items.find((i) => i.symbol === 'RELIANCE');
    expect(reliance?.status).toBe('already_present');
    expect(reliance?.isPlannedForImport).toBe(false);
  });

  it('enforces target watchlist remaining capacity in append mode', () => {
    const input = 'NSE:AAA, NSE:BBB, NSE:CCC, NSE:DDD';
    const parsed = parseTradingViewList(input);

    // Target watchlist has 998 items -> only 2 spaces remaining
    const resolved = resolveImportPreview(parsed, {
      mode: 'append',
      splitSections: false,
      targetWatchlistExistingSymbols: [],
      targetWatchlistCurrentCount: 998,
    });

    expect(resolved.summary.readyToImport).toBe(2); // AAA, BBB
    expect(resolved.summary.capacityExceeded).toBe(2); // CCC, DDD
    expect(resolved.canSubmit).toBe(true);

    const ccc = resolved.items.find((i) => i.symbol === 'CCC');
    expect(ccc?.status).toBe('capacity_exceeded');
    expect(ccc?.isPlannedForImport).toBe(false);
  });

  it('disables submit when target watchlist is completely full (1,000 items)', () => {
    const input = 'NSE:RELIANCE';
    const parsed = parseTradingViewList(input);

    const resolved = resolveImportPreview(parsed, {
      mode: 'append',
      splitSections: false,
      targetWatchlistCurrentCount: 1000,
    });

    expect(resolved.canSubmit).toBe(false);
    expect(resolved.submitDisabledReason).toBe('Target watchlist is full (1,000 symbols)');
  });

  it('disables submit when zero valid symbols exist', () => {
    const input = 'BSE:500325, NASDAQ:AAPL';
    const parsed = parseTradingViewList(input);

    const resolved = resolveImportPreview(parsed, {
      mode: 'create',
      splitSections: false,
    });

    expect(resolved.summary.readyToImport).toBe(0);
    expect(resolved.canSubmit).toBe(false);
    expect(resolved.submitDisabledReason).toBe('No valid symbols selected for import');
  });

  it('handles user exclusions when toggling symbols in preview', () => {
    const input = 'NSE:RELIANCE, NSE:TCS';
    const parsed = parseTradingViewList(input);
    const relianceId = parsed.items[0].id;

    const resolved = resolveImportPreview(parsed, {
      mode: 'create',
      splitSections: false,
      userExcludedIds: new Set([relianceId]),
    });

    expect(resolved.summary.readyToImport).toBe(1); // Only TCS
    const reliance = resolved.items.find((i) => i.id === relianceId);
    expect(reliance?.selected).toBe(false);
    expect(reliance?.isPlannedForImport).toBe(false);
  });

  it('buildImportPayload constructs correct payloads for single and split modes', () => {
    const input = `
### NIFTY
NSE:RELIANCE
### BANK
NSE:HDFCBANK
`;
    const parsed = parseTradingViewList(input);
    const resolvedSplit = resolveImportPreview(parsed, {
      mode: 'create',
      splitSections: true,
    });

    const payload = buildImportPayload(resolvedSplit, {
      baseName: 'My Portfolio',
      mode: 'create',
      splitSections: true,
    });

    expect(payload.base_name).toBe('My Portfolio');
    expect(payload.mode).toBe('create');
    expect(payload.split_sections).toBe(true);
    expect(payload.sections.length).toBe(2);
    expect(payload.sections[0].items).toEqual([{ symbol: 'RELIANCE', exchange: 'NSE' }]);
    expect(payload.sections[1].items).toEqual([{ symbol: 'HDFCBANK', exchange: 'NSE' }]);
  });
});
