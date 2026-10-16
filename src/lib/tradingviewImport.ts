/**
 * TradingView Watchlist Parser, Normalizer, and Import Preview Resolver
 *
 * Supports:
 * - Comma, newline, CRLF, tab, and semicolon separated symbols
 * - UTF-8 BOM stripping
 * - Official TradingView export format (NSE:XYZ, BSE:XYZ, NASDAQ:XYZ)
 * - Bare symbols (defaulting to NSE)
 * - Yahoo-style .NS (NSE) and .BO (BSE) suffixes
 * - Stripping -EQ series suffix (e.g. RELIANCE-EQ -> RELIANCE)
 * - Preserving hyphenated symbols (e.g. BAJAJ-AUTO, NAM-INDIA)
 * - Section headers prefixed with #, ##, or ### (e.g. ### BANKING)
 * - Flagging unsupported exchanges (V1 supports NSE only)
 * - Section-scoped duplicate detection in parser
 * - Pure import preview resolver with destination-aware deduplication,
 *   target watchlist duplicate checking for append, per-destination 1,000 symbol limits,
 *   and real valid-sections counting.
 */

export interface ParsedImportItem {
  id: string;
  symbol: string;
  raw: string;
  exchange: string;
  section: string;
  isValidNse: boolean;
  isDuplicate: boolean;
  status: 'valid' | 'duplicate' | 'unsupported';
  reason?: string;
  selected: boolean;
}

export interface ParsedImportSection {
  name: string;
  items: ParsedImportItem[];
}

export interface TradingViewParseResult {
  sections: ParsedImportSection[];
  items: ParsedImportItem[];
  summary: {
    totalParsed: number;
    validNse: number;
    duplicates: number;
    unsupported: number;
    sectionsCount: number;
  };
}

export interface ResolvedPreviewItem {
  id: string;
  symbol: string;
  raw: string;
  exchange: string;
  section: string;
  isValidNse: boolean;
  status: 'valid' | 'duplicate' | 'unsupported' | 'already_present' | 'capacity_exceeded';
  reason?: string;
  selected: boolean;
  isPlannedForImport: boolean;
}

export interface ResolvedSectionPreview {
  name: string;
  items: ResolvedPreviewItem[];
  validCount: number;
  duplicateCount: number;
  unsupportedCount: number;
  exceedsCapacity: boolean;
}

export interface ImportPreviewResolution {
  sections: ResolvedSectionPreview[];
  items: ResolvedPreviewItem[];
  summary: {
    totalParsed: number;
    readyToImport: number;
    duplicates: number;
    unsupported: number;
    alreadyInTarget: number;
    capacityExceeded: number;
    validSectionsCount: number;
  };
  canSubmit: boolean;
  submitDisabledReason?: string;
}

export interface ResolveImportOptions {
  mode: 'create' | 'append' | 'replace';
  splitSections: boolean;
  targetWatchlistExistingSymbols?: string[];
  targetWatchlistCurrentCount?: number;
  userExcludedIds?: Set<string>;
}

export interface WatchlistImportApiItem {
  symbol: string;
  exchange: string;
}

export interface WatchlistImportApiSection {
  name: string;
  items: WatchlistImportApiItem[];
}

export interface WatchlistImportPayload {
  base_name: string;
  mode: 'create' | 'append' | 'replace';
  split_sections: boolean;
  target_watchlist_id?: number | null;
  sections: WatchlistImportApiSection[];
}

// NSE symbols contain uppercase letters, numbers, and hyphens (e.g. BAJAJ-AUTO)
const NSE_SYMBOL_REGEX = /^[A-Z0-9]+(?:-[A-Z0-9]+)*$/;

/**
 * Normalizes an individual symbol token.
 * Extracts exchange, strips suffixes (.NS, .BO, -EQ), and validates format.
 */
export function normalizeSymbolToken(rawToken: string): {
  symbol: string;
  exchange: string;
  isValidNse: boolean;
  reason?: string;
} {
  const clean = rawToken.trim().replace(/^["']|["']$/g, '');
  if (!clean) {
    return { symbol: '', exchange: 'NSE', isValidNse: false, reason: 'Empty token' };
  }

  let exchange = 'NSE';
  let symbol = clean;

  if (clean.includes(':')) {
    const colonIdx = clean.indexOf(':');
    exchange = clean.slice(0, colonIdx).trim().toUpperCase();
    symbol = clean.slice(colonIdx + 1).trim();
  } else if (clean.toUpperCase().endsWith('.NS')) {
    exchange = 'NSE';
    symbol = clean.slice(0, -3).trim();
  } else if (clean.toUpperCase().endsWith('.BO')) {
    exchange = 'BSE';
    symbol = clean.slice(0, -3).trim();
  }

  symbol = symbol.toUpperCase();

  // Strip -EQ series if present (e.g. RELIANCE-EQ -> RELIANCE)
  if (symbol.endsWith('-EQ')) {
    symbol = symbol.slice(0, -3);
  }

  // V1 supports NSE only
  if (exchange !== 'NSE') {
    return {
      symbol,
      exchange,
      isValidNse: false,
      reason: `Unsupported exchange '${exchange}'. V1 only supports NSE equities.`,
    };
  }

  if (!NSE_SYMBOL_REGEX.test(symbol)) {
    return {
      symbol,
      exchange,
      isValidNse: false,
      reason: `Invalid symbol format '${symbol}' for NSE.`,
    };
  }

  return {
    symbol,
    exchange: 'NSE',
    isValidNse: true,
  };
}

/**
 * Parses raw text or file content from TradingView into structured sections and items.
 * Duplicates are scoped per section so split mode sections retain independent symbols.
 */
export function parseTradingViewList(rawInput: string): TradingViewParseResult {
  if (!rawInput || typeof rawInput !== 'string') {
    return {
      sections: [],
      items: [],
      summary: { totalParsed: 0, validNse: 0, duplicates: 0, unsupported: 0, sectionsCount: 0 },
    };
  }

  // Strip BOM if present and normalize line endings
  let text = rawInput;
  if (text.charCodeAt(0) === 0xfeff) {
    text = text.slice(1);
  }
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  const lines = text.split('\n');
  const sectionsMap = new Map<string, ParsedImportItem[]>();
  const sectionSeenMap = new Map<string, Set<string>>();

  let currentSection = 'DEFAULT';
  sectionsMap.set(currentSection, []);
  sectionSeenMap.set(currentSection, new Set<string>());

  const allItems: ParsedImportItem[] = [];
  let itemCounter = 0;

  for (const rawLine of lines) {
    const trimmedLine = rawLine.trim();
    if (!trimmedLine) continue;

    // Check for section header: line starts with '#'
    if (trimmedLine.startsWith('#')) {
      const headerTitle = trimmedLine.replace(/^#+/, '').trim();
      currentSection = headerTitle || 'DEFAULT';
      if (!sectionsMap.has(currentSection)) {
        sectionsMap.set(currentSection, []);
        sectionSeenMap.set(currentSection, new Set<string>());
      }
      continue;
    }

    // Split line by comma, semicolon, or tab
    const tokens = trimmedLine.split(/[,;\t]+/);

    for (const token of tokens) {
      const cleaned = token.trim();
      if (!cleaned) continue;

      itemCounter += 1;
      const normalized = normalizeSymbolToken(cleaned);

      let isDuplicate = false;
      let status: 'valid' | 'duplicate' | 'unsupported' = 'valid';
      let reason = normalized.reason;
      let selected = false;

      const seenInSection = sectionSeenMap.get(currentSection)!;

      if (!normalized.isValidNse) {
        status = 'unsupported';
        selected = false;
      } else {
        if (seenInSection.has(normalized.symbol)) {
          isDuplicate = true;
          status = 'duplicate';
          reason = `Duplicate symbol in section (${normalized.symbol})`;
          selected = false;
        } else {
          seenInSection.add(normalized.symbol);
          status = 'valid';
          selected = true;
        }
      }

      const item: ParsedImportItem = {
        id: `item-${itemCounter}-${normalized.symbol || 'sym'}`,
        symbol: normalized.symbol,
        raw: cleaned,
        exchange: normalized.exchange,
        section: currentSection,
        isValidNse: normalized.isValidNse,
        isDuplicate,
        status,
        reason,
        selected,
      };

      allItems.push(item);
      sectionsMap.get(currentSection)!.push(item);
    }
  }

  // Build clean sections array, omitting empty ones if multiple sections exist
  const sections: ParsedImportSection[] = [];
  for (const [name, items] of sectionsMap.entries()) {
    if (items.length > 0) {
      sections.push({ name, items });
    }
  }

  const validNse = allItems.filter((i) => i.isValidNse && !i.isDuplicate).length;
  const duplicates = allItems.filter((i) => i.isDuplicate).length;
  const unsupported = allItems.filter((i) => !i.isValidNse).length;

  return {
    sections,
    items: allItems,
    summary: {
      totalParsed: allItems.length,
      validNse,
      duplicates,
      unsupported,
      sectionsCount: sections.length,
    },
  };
}

/**
 * Pure resolver that derives the effective import preview for merge versus split mode.
 * Enforces per-destination deduplication, append target duplicate checking, and 1,000 symbol limits.
 */
export function resolveImportPreview(
  parseResult: TradingViewParseResult,
  options: ResolveImportOptions
): ImportPreviewResolution {
  const isSplitMode = options.mode === 'create' && options.splitSections;
  const userExcluded = options.userExcludedIds || new Set<string>();

  const targetExisting = new Set(
    (options.targetWatchlistExistingSymbols || []).map((s) => s.toUpperCase())
  );
  const targetCurrentCount = options.targetWatchlistCurrentCount ?? targetExisting.size;
  const spaceLeftInTarget = options.mode === 'append' ? Math.max(0, 1000 - targetCurrentCount) : 1000;

  const resolvedSections: ResolvedSectionPreview[] = [];
  const allResolvedItems: ResolvedPreviewItem[] = [];

  const seenAcrossAll = new Set<string>();
  let flatPlannedCount = 0;

  let totalReadyToImport = 0;
  let totalDuplicates = 0;
  let totalUnsupported = 0;
  let totalAlreadyInTarget = 0;
  let totalCapacityExceeded = 0;
  let validSectionsCount = 0;
  let hasAnySectionExceedingCap = false;

  for (const sec of parseResult.sections) {
    const secItems: ResolvedPreviewItem[] = [];
    const secSeen = new Set<string>();
    let secPlannedCount = 0;
    let secExceedsCapacity = false;

    let secValidCount = 0;
    let secDuplicateCount = 0;
    let secUnsupportedCount = 0;

    for (const item of sec.items) {
      const isExcludedByUser = userExcluded.has(item.id);

      if (!item.isValidNse) {
        secUnsupportedCount += 1;
        totalUnsupported += 1;
        const resItem: ResolvedPreviewItem = {
          ...item,
          status: 'unsupported',
          selected: false,
          isPlannedForImport: false,
          reason: item.reason || 'Unsupported exchange or format',
        };
        secItems.push(resItem);
        allResolvedItems.push(resItem);
        continue;
      }

      if (isExcludedByUser) {
        const resItem: ResolvedPreviewItem = {
          ...item,
          selected: false,
          isPlannedForImport: false,
          reason: 'Deselected by user',
        };
        secItems.push(resItem);
        allResolvedItems.push(resItem);
        continue;
      }

      if (isSplitMode) {
        // Split mode: deduplicate per section, enforce 1000 per section
        if (secSeen.has(item.symbol)) {
          secDuplicateCount += 1;
          totalDuplicates += 1;
          const resItem: ResolvedPreviewItem = {
            ...item,
            status: 'duplicate',
            reason: `Duplicate symbol in section (${item.symbol})`,
            selected: false,
            isPlannedForImport: false,
          };
          secItems.push(resItem);
          allResolvedItems.push(resItem);
        } else {
          secPlannedCount += 1;
          if (secPlannedCount > 1000) {
            secExceedsCapacity = true;
            hasAnySectionExceedingCap = true;
            totalCapacityExceeded += 1;
            const resItem: ResolvedPreviewItem = {
              ...item,
              status: 'capacity_exceeded',
              reason: 'Exceeds 1,000 symbol section capacity',
              selected: false,
              isPlannedForImport: false,
            };
            secItems.push(resItem);
            allResolvedItems.push(resItem);
          } else {
            secSeen.add(item.symbol);
            secValidCount += 1;
            totalReadyToImport += 1;
            const resItem: ResolvedPreviewItem = {
              ...item,
              status: 'valid',
              selected: true,
              isPlannedForImport: true,
              reason: undefined,
            };
            secItems.push(resItem);
            allResolvedItems.push(resItem);
          }
        }
      } else {
        // Flat destination (create merge, replace, or append)
        if (options.mode === 'append' && targetExisting.has(item.symbol)) {
          totalAlreadyInTarget += 1;
          const resItem: ResolvedPreviewItem = {
            ...item,
            status: 'already_present',
            reason: `Already in target watchlist (${item.symbol})`,
            selected: false,
            isPlannedForImport: false,
          };
          secItems.push(resItem);
          allResolvedItems.push(resItem);
        } else if (seenAcrossAll.has(item.symbol)) {
          secDuplicateCount += 1;
          totalDuplicates += 1;
          const resItem: ResolvedPreviewItem = {
            ...item,
            status: 'duplicate',
            reason: `Duplicate symbol in destination (${item.symbol})`,
            selected: false,
            isPlannedForImport: false,
          };
          secItems.push(resItem);
          allResolvedItems.push(resItem);
        } else {
          flatPlannedCount += 1;
          if (flatPlannedCount > spaceLeftInTarget) {
            totalCapacityExceeded += 1;
            const resItem: ResolvedPreviewItem = {
              ...item,
              status: 'capacity_exceeded',
              reason:
                options.mode === 'append'
                  ? `Watchlist capacity reached (1,000 max, ${spaceLeftInTarget} space remaining)`
                  : 'Destination capacity reached (1,000 max)',
              selected: false,
              isPlannedForImport: false,
            };
            secItems.push(resItem);
            allResolvedItems.push(resItem);
          } else {
            seenAcrossAll.add(item.symbol);
            secValidCount += 1;
            totalReadyToImport += 1;
            const resItem: ResolvedPreviewItem = {
              ...item,
              status: 'valid',
              selected: true,
              isPlannedForImport: true,
              reason: undefined,
            };
            secItems.push(resItem);
            allResolvedItems.push(resItem);
          }
        }
      }
    }

    if (secPlannedCount > 0 && secValidCount > 0) {
      validSectionsCount += 1;
    }

    resolvedSections.push({
      name: sec.name,
      items: secItems,
      validCount: secValidCount,
      duplicateCount: secDuplicateCount,
      unsupportedCount: secUnsupportedCount,
      exceedsCapacity: secExceedsCapacity,
    });
  }

  let canSubmit = true;
  let submitDisabledReason: string | undefined = undefined;

  if (options.mode === 'append' && spaceLeftInTarget <= 0) {
    canSubmit = false;
    submitDisabledReason = 'Target watchlist is full (1,000 symbols)';
  } else if (isSplitMode && hasAnySectionExceedingCap) {
    canSubmit = false;
    submitDisabledReason = 'One or more sections exceed the 1,000 symbol limit';
  } else if (totalReadyToImport === 0) {
    canSubmit = false;
    submitDisabledReason = 'No valid symbols selected for import';
  }

  return {
    sections: resolvedSections,
    items: allResolvedItems,
    summary: {
      totalParsed: allResolvedItems.length,
      readyToImport: totalReadyToImport,
      duplicates: totalDuplicates,
      unsupported: totalUnsupported,
      alreadyInTarget: totalAlreadyInTarget,
      capacityExceeded: totalCapacityExceeded,
      validSectionsCount: isSplitMode ? validSectionsCount : totalReadyToImport > 0 ? 1 : 0,
    },
    canSubmit,
    submitDisabledReason,
  };
}

/**
 * Converts a preview resolution into the backend import request payload.
 */
export function buildImportPayload(
  source: ImportPreviewResolution | TradingViewParseResult,
  options: {
    baseName: string;
    mode: 'create' | 'append' | 'replace';
    splitSections: boolean;
    targetWatchlistId?: number | null;
  }
): WatchlistImportPayload {
  const sectionsPayload: WatchlistImportApiSection[] = [];

  for (const sec of source.sections) {
    const plannedItems = sec.items
      .filter((i) => ('isPlannedForImport' in i ? i.isPlannedForImport : i.selected && i.isValidNse))
      .map((i) => ({ symbol: i.symbol, exchange: 'NSE' }));

    if (plannedItems.length > 0) {
      sectionsPayload.push({
        name: sec.name,
        items: plannedItems,
      });
    }
  }

  return {
    base_name: options.baseName.trim() || 'Imported Watchlist',
    mode: options.mode,
    split_sections: options.mode === 'create' ? options.splitSections : false,
    target_watchlist_id: options.targetWatchlistId ?? null,
    sections: sectionsPayload,
  };
}