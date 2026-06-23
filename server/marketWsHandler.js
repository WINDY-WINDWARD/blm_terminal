/**
 * In-process WebSocket handler for /ws/market. Used by server.js
 * (dev) and any production server that wants to host the market
 * WS endpoint in the same Node process as the Next.js front-end.
 *
 * Protocol: see src/lib/marketWsRoute.ts (the TypeScript
 * implementation, which is what the test suite exercises). This
 * file is a 1:1 CommonJS translation of that module so server.js
 * can require() it without a TypeScript runtime.
 *
 * The test suite in src/__tests__/api/ws/market/route.test.ts
 * pins down the protocol behavior; this implementation is kept
 * in sync with the TypeScript version manually.
 */

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';
const NSE_BASE_URL = 'https://www.nseindia.com';
const NSE_HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  Accept: 'application/json, text/html, */*',
  'Accept-Language': 'en-US,en;q=0.9',
  Referer: 'https://www.nseindia.com/',
  Origin: 'https://www.nseindia.com',
};
const NSE_FIELD_MAP_CHANGE_RANGES = {
  oneDayPercent: '',
  oneWeekPercent: 'one_week_chng_per',
  oneMonthPercent: 'one_month_chng_per',
  threeMonthPercent: 'three_month_chng_per',
  sixMonthPercent: 'six_month_chng_per',
  oneYearPercent: 'one_year_chng_per',
  twoYearPercent: 'two_year_chng_per',
  threeYearPercent: 'three_year_chng_per',
  fiveYearPercent: 'five_year_chng_per',
};
const SYMBOL_DATA_TTL_SECONDS = 60;
const CHANGE_RANGES_TTL_SECONDS = 300;
const NSE_MAX_SYMBOLS_PER_REQUEST = 50;
const NSE_MAX_ATTEMPTS = 3;
const NSE_CONCURRENCY = 2;
const NSE_COURTESY_DELAY = 1.5;

const symbolDataCache = new Map();
const changeRangesCache = new Map();
let nseActiveCount = 0;
const nseWaiters = [];
const lastRequestAt = new Map();

function acquireNse() {
  if (nseActiveCount < NSE_CONCURRENCY) {
    nseActiveCount += 1;
    return Promise.resolve();
  }
  return new Promise((resolve) => nseWaiters.push(resolve));
}
function releaseNse() {
  const next = nseWaiters.shift();
  if (next) next();
  else nseActiveCount = Math.max(0, nseActiveCount - 1);
}

async function throttledNseCall(endpointName, fn) {
  await acquireNse();
  try {
    const last = lastRequestAt.get(endpointName) || 0;
    const elapsed = (Date.now() - last) / 1000;
    const wait = NSE_COURTESY_DELAY - elapsed;
    if (wait > 0) await new Promise((r) => setTimeout(r, wait * 1000));
    let lastExc;
    for (let attempt = 0; attempt < NSE_MAX_ATTEMPTS; attempt++) {
      try {
        const result = await fn();
        lastRequestAt.set(endpointName, Date.now());
        return result;
      } catch (exc) {
        lastExc = exc;
        if (
          attempt < NSE_MAX_ATTEMPTS - 1 &&
          (exc instanceof TypeError || /5\d\d/.test(String(exc && exc.message)))
        ) {
          await new Promise((r) => setTimeout(r, 250 * Math.pow(2, attempt)));
          continue;
        }
        break;
      }
    }
    throw lastExc;
  } finally {
    releaseNse();
  }
}

function isSymbolDataCacheable(v) {
  return v != null && typeof v.ltp === 'number' && v.ltp > 0;
}
function isChangeRangesCacheable(v) {
  return v != null && Object.values(v).some((x) => x != null);
}

function buildSymbolDataUrl(symbol) {
  const params = new URLSearchParams({
    functionName: 'getSymbolData',
    marketType: 'N',
    series: 'EQ',
    symbol,
  });
  return `${NSE_BASE_URL}/api/NextApi/apiClient/GetQuoteApi?${params.toString()}`;
}
function buildChangeRangesUrl(symbol) {
  const params = new URLSearchParams({
    functionName: 'getYearwiseData',
    symbol: `${symbol}EQN`,
  });
  return `${NSE_BASE_URL}/api/NextApi/apiClient/GetQuoteApi?${params.toString()}`;
}

function extractSymbolData(raw) {
  if (!raw) return null;
  const equity = raw.equityResponse && raw.equityResponse[0];
  if (!equity) return null;
  const ltp = (equity.orderBook && equity.orderBook.lastPrice) || (equity.tradeInfo && equity.tradeInfo.lastPrice) || 0;
  if (!ltp) return null;
  return {
    ltp,
    pChange: (equity.metaData && equity.metaData.pChange) || 0,
    yearHigh: equity.priceInfo && equity.priceInfo.yearHigh,
    yearLow: equity.priceInfo && equity.priceInfo.yearLow,
  };
}
function parseChangeRangesRow(row) {
  const out = {
    oneDayPercent: null, oneWeekPercent: null, oneMonthPercent: null,
    threeMonthPercent: null, sixMonthPercent: null, oneYearPercent: null,
    twoYearPercent: null, threeYearPercent: null, fiveYearPercent: null,
  };
  if (!row) return out;
  for (const outKey of Object.keys(NSE_FIELD_MAP_CHANGE_RANGES)) {
    const nseKey = NSE_FIELD_MAP_CHANGE_RANGES[outKey];
    if (!nseKey) continue;
    const raw = row[nseKey];
    if (raw == null) out[outKey] = null;
    else {
      const num = Number(raw);
      out[outKey] = Number.isFinite(num) ? num : null;
    }
  }
  return out;
}

async function fetchSymbolDataFromNse(symbol) {
  const res = await fetch(buildSymbolDataUrl(symbol), {
    headers: NSE_HEADERS,
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok) throw new Error(`NSE returned ${res.status}`);
  const payload = await res.json();
  if (!payload || typeof payload !== 'object') {
    throw new Error('Unexpected getSymbolData response shape');
  }
  return extractSymbolData(payload);
}
async function fetchChangeRangesFromNse(symbol) {
  const res = await fetch(buildChangeRangesUrl(symbol), {
    headers: NSE_HEADERS,
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok) throw new Error(`NSE returned ${res.status}`);
  const payload = await res.json();
  let row;
  if (Array.isArray(payload)) row = payload[0];
  else if (payload && typeof payload === 'object' && Array.isArray(payload.data)) row = payload.data[0];
  if (!row) return null;
  return parseChangeRangesRow(row);
}
async function fetchSymbolDataFromPython(symbol) {
  const url = `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error(`Python backend returned ${res.status}`);
  const body = await res.json();
  return extractSymbolData(body.data && body.data[symbol]);
}
async function fetchChangeRangesFromPython(symbol) {
  const url = `${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error(`Python backend returned ${res.status}`);
  const body = await res.json();
  return (body.data && body.data[symbol]) || null;
}

async function fetchSymbolDataWithFallback(symbol) {
  const sym = symbol.toUpperCase();
  const cacheKey = `symbol-data:${sym}`;
  const cached = symbolDataCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  let nseFailed = false;
  try {
    const value = await throttledNseCall('symbol-data', () => fetchSymbolDataFromNse(sym));
    if (isSymbolDataCacheable(value)) {
      symbolDataCache.set(cacheKey, { value, expiresAt: Date.now() + SYMBOL_DATA_TTL_SECONDS * 1000 });
      return value;
    }
    nseFailed = true;
  } catch (err) {
    nseFailed = true;
    console.warn(`[marketWsJs] symbol-data NSE failed for ${sym}: ${err && err.message}`);
  }
  void nseFailed;
  try {
    const value = await fetchSymbolDataFromPython(sym);
    if (isSymbolDataCacheable(value)) {
      symbolDataCache.set(cacheKey, { value, expiresAt: Date.now() + SYMBOL_DATA_TTL_SECONDS * 1000 });
    }
    return value;
  } catch (err) {
    console.error(`[marketWsJs] symbol-data Python failed for ${sym}: ${err && err.message}`);
    return null;
  }
}

async function fetchChangeRangesWithFallback(symbol) {
  const sym = symbol.toUpperCase();
  const cacheKey = `change-ranges:${sym}`;
  const cached = changeRangesCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  let nseFailed = false;
  try {
    const value = await throttledNseCall('change-ranges', () => fetchChangeRangesFromNse(sym));
    if (isChangeRangesCacheable(value)) {
      changeRangesCache.set(cacheKey, { value, expiresAt: Date.now() + CHANGE_RANGES_TTL_SECONDS * 1000 });
      return value;
    }
    nseFailed = true;
  } catch (err) {
    nseFailed = true;
    console.warn(`[marketWsJs] change-ranges NSE failed for ${sym}: ${err && err.message}`);
  }
  void nseFailed;
  try {
    const value = await fetchChangeRangesFromPython(sym);
    if (isChangeRangesCacheable(value)) {
      changeRangesCache.set(cacheKey, { value, expiresAt: Date.now() + CHANGE_RANGES_TTL_SECONDS * 1000 });
    }
    return value;
  } catch (err) {
    console.error(`[marketWsJs] change-ranges Python failed for ${sym}: ${err && err.message}`);
    return null;
  }
}

function sendJson(ws, msg) {
  try { ws.send(JSON.stringify(msg)); }
  catch (err) { console.warn('[marketWsJs] send failed:', err && err.message); }
}

async function streamBatch(ws, requestId, symbols, startedType, partialType, completeType, fetcher) {
  if (!symbols || !Array.isArray(symbols) || symbols.length === 0) {
    sendJson(ws, { type: 'error', request_id: requestId, message: 'symbols must be a non-empty list' });
    return;
  }
  const capped = symbols.slice(0, NSE_MAX_SYMBOLS_PER_REQUEST);
  sendJson(ws, { type: startedType, request_id: requestId, symbols: capped });

  const tasks = capped.map((sym) => {
    const promise = fetcher(sym)
      .then((value) => ({ sym, value }))
      .catch((err) => {
        console.warn(`[marketWsJs] unhandled error for ${sym}: ${err && err.message}`);
        return { sym, value: null };
      });
    return { sym, promise };
  });

  while (tasks.length > 0) {
    const completed = await Promise.race(tasks.map((t) => t.promise));
    const idx = tasks.findIndex((t) => t.sym === completed.sym);
    if (idx >= 0) tasks.splice(idx, 1);
    const partial = { type: partialType, request_id: requestId, symbol: completed.sym };
    if (completed.value == null) partial.data = null;
    else partial.data = completed.value;
    sendJson(ws, partial);
  }

  sendJson(ws, { type: completeType, request_id: requestId });
}

async function handleMarketWsMessage(ws, raw) {
  let msg;
  try { msg = JSON.parse(raw); } catch { return; }
  const action = msg.action;
  const requestId = Number(msg.request_id || 0) | 0;
  const symbols = Array.isArray(msg.symbols) ? msg.symbols : [];
  if (action === 'get_change_ranges') {
    await streamBatch(ws, requestId, symbols, 'change_ranges_started', 'change_ranges_partial', 'change_ranges_complete', (s) => fetchChangeRangesWithFallback(s));
  } else if (action === 'get_symbol_data') {
    await streamBatch(ws, requestId, symbols, 'symbol_data_started', 'symbol_data_partial', 'symbol_data_complete', (s) => fetchSymbolDataWithFallback(s));
  } else if (action !== undefined) {
    sendJson(ws, { type: 'error', request_id: requestId, message: `Unknown action: ${action}` });
  }
}

/**
 * Handle a new WebSocket connection. The `ws` parameter is a
 * `ws` library WebSocket instance (already upgraded by the server).
 */
function handleMarketWsConnection(ws) {
  sendJson(ws, { type: 'connected' });
  ws.on('message', (data) => {
    handleMarketWsMessage(ws, data.toString());
  });
  ws.on('error', () => {});
  ws.on('close', () => {});
}

module.exports = { handleMarketWsConnection, handleMarketWsMessage };
