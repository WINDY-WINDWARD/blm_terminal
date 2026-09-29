'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
} from 'lightweight-charts';
import type { IChartApi, IPaneApi, IPriceLine, ISeriesApi, Time } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import {
  activeSymbolAtom,
  activeExchangeAtom,
  chartSymbolOverridesAtom,
  focusedPanelAtom,
  tickDataAtom,
  chartIndicatorsAtom,
  scriptChartHandoffAtom,
  scriptLastErrorAtom,
} from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';
import { ChartIndicatorMenu } from './ChartIndicatorMenu';
import { ChartScriptsMenu } from './ChartScriptsMenu';
import { useScriptSlots, useScriptedOverlays } from './ScriptedOverlays';
import type { ScriptBar } from '@/lib/scripts/types';
import { setChartSlot } from '@/lib/scripts/api';
import { useScriptFundamentals } from '@/lib/scripts/fundamentalsCtx';
import {
  brewDaily,
  brewIntraday,
  LIVE_STALE_MS,
  type BrewInput,
} from '@/lib/scripts/liveBar';
import {
  EMPTY_STOP_STREAK,
  HISTORY_MAX_AGE_S,
  backfillCacheAction,
  dailyBackfillRange,
  historyCache,
  historyCacheKey,
  intradayBackfillRange,
  mapDailyCandles,
  mapIntradayCandles,
  mergeHistoryBars,
  shouldBackfill,
} from '@/lib/chartHistory';
import type { ActiveIndicator, IndicatorCandle } from '@/lib/indicators/types';
import { clampIndicators } from '@/lib/indicators/presets';
import {
  atr,
  bollinger,
  ema,
  macd,
  obv,
  rsi,
  sessionVWAP,
  sma,
  stochastic,
} from '@/lib/indicators/calculations';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Interval = '1m' | '5m' | '15m' | '30m' | '1h' | 'D' | 'W' | 'M';

const ALL_INTERVALS: Interval[] = ['1m', '5m', '15m', '30m', '1h', 'D', 'W', 'M'];

// Backend daily OHLCV candle
interface BackendCandle {
  Date: string; // "YYYY-MM-DD"
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface BackendOHLCVResponse {
  symbol: string;
  candles: BackendCandle[];
  count: number;
  /** Stale-while-revalidate flag from the backend ticker pipeline. */
  is_stale?: boolean;
}

// Intraday / weekly / monthly candle from new endpoint
interface IntradayCandle {
  timestamp: number; // Unix milliseconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface IntradayOHLCVResponse {
  symbol: string;
  interval: string;
  candles: IntradayCandle[];
  count: number;
}

interface SymbolSearchResult {
  symbol: string;
  companyName: string;
}

interface ChartWidgetProps {
  panelId: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format date as DD-MM-YYYY for the backend ticker API. */
function toBackendDate(date: Date): string {
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  return `${day}-${month}-${year}`;
}

function getDailyDateRange(): { fromDate: string; toDate: string } {
  const end = new Date();
  const start = new Date();
  start.setFullYear(end.getFullYear() - 1);
  return { fromDate: toBackendDate(start), toDate: toBackendDate(end) };
}

/** Returns true if current time is within NSE trading hours (09:15–15:30 IST Mon–Fri). */
function isMarketHours(): boolean {
  const nowUtc = Date.now();
  // IST = UTC + 5:30 = UTC + 330 min
  const nowIst = new Date(nowUtc + 5.5 * 60 * 60 * 1000);
  const day = nowIst.getUTCDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;
  const hhmm = nowIst.getUTCHours() * 100 + nowIst.getUTCMinutes();
  return hhmm >= 915 && hhmm <= 1530;
}

async function fetchBackendOHLCV(
  symbol: string,
  fromDate: string,
  toDate: string,
): Promise<BackendOHLCVResponse> {
  const params = new URLSearchParams({ from_date: fromDate, to_date: toDate });
  const res = await fetch(`/api/py/ticker/ohlcv/${symbol}?${params.toString()}`);
  if (!res.ok) throw new Error(`Backend error ${res.status}`);
  return res.json() as Promise<BackendOHLCVResponse>;
}

async function fetchIntradayOHLCV(
  symbol: string,
  interval: Interval,
  fromTsMs?: number,
  toTsMs?: number,
): Promise<IntradayOHLCVResponse> {
  const params = new URLSearchParams({ interval });
  if (fromTsMs !== undefined) params.set('from_ts', String(Math.floor(fromTsMs)));
  if (toTsMs !== undefined) params.set('to_ts', String(Math.floor(toTsMs)));
  const res = await fetch(
    `/api/py/ticker/intraday/${encodeURIComponent(symbol)}?${params.toString()}`,
  );
  if (!res.ok) throw new Error(`Backend error ${res.status}`);
  return res.json() as Promise<IntradayOHLCVResponse>;
}

/** Candlestick-series shape for a brew-friendly server bar row. */
function toChartBars(
  bars: BrewInput[],
): { time: Time; open: number; high: number; low: number; close: number }[] {
  return bars.map((b) => ({
    time: b.time as Time,
    open: b.o,
    high: b.h,
    low: b.l,
    close: b.c,
  }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChartWidget({ panelId }: ChartWidgetProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null);
  const indicatorSeriesRef = useRef<ISeriesApi<'Line' | 'Histogram', Time>[]>([]);
  // Panes created by the indicator rebuild, tracked by object identity so
  // teardown removes ONLY these — script-owned panes (Script Lab) must
  // survive indicator rebuilds on every tick.
  const indicatorPanesRef = useRef<IPaneApi<Time>[]>([]);
  const liveLineRef = useRef<IPriceLine | null>(null);
  // L3: fitContent only when the symbol/interval key changes, never on polls.
  const fitKeyRef = useRef('');
  // Tracks whether a brewing bar is currently painted (for stale-drop).
  const brewActiveRef = useRef(false);
  // --- Scroll-back history (memory-only, never persisted) ---
  // Extra older bars merged under the query windows below. Cleared on
  // symbol/interval switch; the shared historyCache adds a 2h TTL.
  const extraBarsRef = useRef<BrewInput[]>([]);
  const [extraVer, setExtraVer] = useState(0);
  const bfStateRef = useRef({ epoch: 0, inFlight: false, emptyStreak: 0, exhausted: false, suppress: false });
  // Fresh-per-render feed for the stable range-change handler.
  const feedRef = useRef<{ symbol: string; interval: Interval; isDaily: boolean; oldestSec: number }>({
    symbol: '',
    interval: 'D',
    isDaily: true,
    oldestSec: 0,
  });
  const lastRangeRef = useRef(0);

  const resetBackfill = () => {
    bfStateRef.current.epoch += 1;
    bfStateRef.current.inFlight = false;
    bfStateRef.current.emptyStreak = 0;
    bfStateRef.current.exhausted = false;
    extraBarsRef.current = [];
  };
  const [globalSymbol] = useAtom(activeSymbolAtom);
  const [globalExchange] = useAtom(activeExchangeAtom);
  const [overrides, setOverrides] = useAtom(chartSymbolOverridesAtom);
  // Per-panel independence: an override entry detaches this chart from the
  // global symbol; absent entry = linked, follows global.
  const override = overrides[panelId];
  // `||` (not `??`): a persisted empty-string exchange must also fall back,
  // otherwise the tick key `SYM.` never matches the market feed.
  const symbol = override?.symbol || globalSymbol;
  const exchange = override?.exchange || globalExchange;
  const [focusedPanel] = useAtom(focusedPanelAtom);
  const [tickMap, setTickData] = useAtom(tickDataAtom);
  const [savedIndicators, setSavedIndicators] = useAtom(chartIndicatorsAtom);

  // Clamp persisted state (forward-compatible with future indicator versions).
  const indicators: ActiveIndicator[] = useMemo(
    () => clampIndicators(savedIndicators?.items),
    [savedIndicators],
  );

  // Persist the clamped form once so corrupt/legacy entries self-heal.
  useEffect(() => {
    if (savedIndicators && savedIndicators.items !== undefined) {
      const clamped = clampIndicators(savedIndicators.items);
      if (clamped.length !== savedIndicators.items.length) {
        setSavedIndicators({ v: 1, items: clamped });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [inputSymbol, setInputSymbol] = useState(symbol);
  const [inputExchange, setInputExchange] = useState(exchange);
  const [interval, setInterval] = useState<Interval>('D');

  // Autocomplete state
  const [autocompleteResults, setAutocompleteResults] = useState<SymbolSearchResult[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const searchContainerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  const isIntraday = interval !== 'D';
    const isDaily = interval === 'D';

  // Sync input fields when the effective symbol changes — but never clobber
  // text the user is actively typing in this chart's search box.
  useEffect(() => {
    const active = document.activeElement;
    if (searchContainerRef.current?.contains(active)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setInputSymbol(symbol);
    setInputExchange(exchange);
  }, [symbol, exchange]);

  // Handle outside clicks to close autocomplete dropdown
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        searchContainerRef.current &&
        !searchContainerRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const { fromDate, toDate } = getDailyDateRange();
  const queryClient = useQueryClient();

  // ---------- Daily OHLCV (existing pipeline) ----------
  const {
    data: histData,
    isLoading: dailyLoading,
    isError: dailyError,
  } = useQuery({
    queryKey: ['backend-ohlcv', symbol, fromDate, toDate],
    queryFn: () => fetchBackendOHLCV(symbol, fromDate, toDate),
    enabled: isDaily,
    staleTime: 5 * 60_000,
    refetchInterval: isDaily && isMarketHours() ? 60_000 : false,
    retry: 1,
    select: (data) => ({ ...data, _symbol: symbol }),
  });

  // ---------- Intraday / Weekly / Monthly (new endpoint) ----------
  const {
    data: intradayData,
    isLoading: intradayLoading,
    isError: intradayError,
    } = useQuery({
      queryKey: ['intraday-ohlcv', symbol, interval],
      queryFn: () => fetchIntradayOHLCV(symbol, interval),
      enabled: isIntraday,
      staleTime: 30_000,
      refetchInterval: isIntraday
        ? (interval === '1h' || interval === '1m' || interval === '5m' || interval === '15m' || interval === '30m') && isMarketHours()
          ? 60_000
          : 5 * 60_000
        : false,
      retry: 1,
      select: (data) => ({ ...data, _symbol: symbol }),
    });
  
    const isLoading = (isDaily && dailyLoading) || (isIntraday && intradayLoading);
    const isError = (isDaily && dailyError) || (isIntraday && intradayError);

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['backend-ohlcv', symbol] });
    void queryClient.invalidateQueries({ queryKey: ['intraday-ohlcv', symbol] });
    // Refresh restarts history from the head window (backfill re-fetches on scroll).
    resetBackfill();
    historyCache.clearPrefix(`${symbol}|${interval}|`);
    setExtraVer((v) => v + 1);
  };

  // ---------- Build chart (once on mount) ----------
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#000000' },
        textColor: '#FFB900',
        fontFamily: 'JetBrains Mono, monospace',
      },
      grid: {
        vertLines: { color: '#222' },
        horzLines: { color: '#222' },
      },
      crosshair: { mode: 1 },
      timeScale: { timeVisible: true, secondsVisible: false },
      localization: {
        locale: 'en-IN',
        timeFormatter: (t: number) =>
          new Date(t * 1000).toLocaleTimeString('en-IN', {
            timeZone: 'Asia/Kolkata',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          }),
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
    });

    chartRef.current = chart;

    seriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: '#00ff00',
      downColor: '#ff0000',
      borderVisible: false,
      wickUpColor: '#00ff00',
      wickDownColor: '#ff0000',
    });

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    // Scroll-back history: fetch older windows as the user pans left.
    // Memory-only (historyCache 2h TTL + per-chart ref) — never persisted.
    // The suppress flag breaks the re-entrancy loop: our own
    // setVisibleLogicalRange restore would otherwise re-trigger a fetch.
    // One timeScale handle: the mock (and v5 impl) may hand out a fresh
    // wrapper per call, so subscribe + restore must share this instance.
    const timeScale = chart.timeScale();
    const doBackfill = async (savedFrom: number, savedTo: number) => {
      const st = bfStateRef.current;
      if (st.inFlight || st.exhausted) return;
      const feed = feedRef.current;
      const epoch = st.epoch;
      if (!feed.oldestSec) return;
      if (feed.oldestSec < Date.now() / 1000 - HISTORY_MAX_AGE_S) {
        st.exhausted = true;
        return;
      }
      st.inFlight = true;
      try {
        let fetched: BrewInput[] | null = null;
        let key = '';
        let fromCache = false;
        if (feed.isDaily) {
          const { fromDate, toDate } = dailyBackfillRange(feed.oldestSec);
          key = historyCacheKey(feed.symbol, feed.interval, fromDate);
          fetched = historyCache.get(key);
          fromCache = fetched !== null;
          if (!fromCache) {
            const res = await fetchBackendOHLCV(feed.symbol, fromDate, toDate);
            fetched = mapDailyCandles(res.candles ?? []);
          }
        } else {
          const win = intradayBackfillRange(feed.oldestSec, feed.interval);
          if (!win) {
            // M loads full history up front — nothing to backfill.
            st.exhausted = true;
            return;
          }
          key = historyCacheKey(feed.symbol, feed.interval, String(win.fromTsMs));
          fetched = historyCache.get(key);
          fromCache = fetched !== null;
          if (!fromCache) {
            const res = await fetchIntradayOHLCV(feed.symbol, feed.interval, win.fromTsMs, win.toTsMs);
            fetched = mapIntradayCandles(res.candles ?? []);
          }
        }
        if (st.epoch !== epoch) return;
        if (fetched === null) fetched = [];
        const action = backfillCacheAction({ fromCache, count: fetched.length });
        if (action === 'store') historyCache.set(key, fetched);
        console.debug(
          `[backfill] ${feed.symbol}/${feed.interval} key=${key} fetched=${fetched.length} cached=${fromCache} action=${action}`,
        );
        if (fetched.length === 0) {
          // Only genuine network empties count: an empty cache hit (window
          // still in flight elsewhere) or a skipped store must not exhaust.
          if (action === 'count-empty') {
            st.emptyStreak += 1;
            if (st.emptyStreak >= EMPTY_STOP_STREAK) st.exhausted = true;
          }
          return;
        }
        st.emptyStreak = 0;
        const prevLen = extraBarsRef.current.length;
        extraBarsRef.current = mergeHistoryBars(extraBarsRef.current, fetched);
        const added = extraBarsRef.current.length - prevLen;
        setExtraVer((v) => v + 1);
        if (added > 0) {
          // Prepending shifts logical indices right: restore the viewport.
          st.suppress = true;
          try {
            timeScale.setVisibleLogicalRange({ from: savedFrom + added, to: savedTo + added });
          } finally {
            st.suppress = false;
          }
        }
      } catch {
        // Silent: a failed window retries on the next scroll nudge.
      } finally {
        st.inFlight = false;
      }
    };

    const onVisibleRange = (lr: { from: number; to: number } | null) => {
      const st = bfStateRef.current;
      if (st.suppress) return;
      const now = Date.now();
      if (now - lastRangeRef.current < 300) return;
      lastRangeRef.current = now;
      const range = lr ?? timeScale.getVisibleLogicalRange();
      const from = range?.from;
      if (!shouldBackfill(typeof from === 'number' ? from : null)) return;
      const to = range?.to ?? (typeof from === 'number' ? from + 100 : 0);
      void doBackfill(typeof from === 'number' ? from : 0, to);
    };
    timeScale.subscribeVisibleLogicalRangeChange(onVisibleRange);

    return () => {
      window.removeEventListener('resize', handleResize);
      timeScale.unsubscribeVisibleLogicalRangeChange(onVisibleRange);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Clear chart when symbol, exchange, or interval changes. Backfill
  // state resets too: extra bars, guards, and this pair's cache entries.
  // (Other pairs' entries linger until the 2h TTL sweeps them.)
  useEffect(() => {
    if (seriesRef.current) {
      seriesRef.current.setData([]);
    }
    resetBackfill();
    historyCache.clearPrefix(`${symbol}|${interval}|`);
    setExtraVer((v) => v + 1);
  }, [symbol, exchange, interval]);

  // ---------- Server bars in brew-friendly shape ----------
  // Single source for the candle render, the brewing bar, and (via the
  // ScriptBar memo below) the script runner. Null = no paintable data.
  // Scroll-back bars (memory-only, never persisted) merge UNDER the query
  // window so polls, brew, indicators, and scripts all share one array.
  const dailyServerBars: BrewInput[] | null = useMemo(() => {
    if (!isDaily || !histData?.candles?.length || histData._symbol !== symbol) return null;
    const base = mapDailyCandles(histData.candles);
    return mergeHistoryBars(base, extraBarsRef.current);
    // extraVer is a version tick for extraBarsRef mutations (refs are invisible to deps).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDaily, histData, symbol, extraVer]);

  const intradayServerBars: BrewInput[] | null = useMemo(() => {
    if (!isIntraday || !intradayData?.candles?.length || intradayData._symbol !== symbol)
      return null;
    const base = mapIntradayCandles(intradayData.candles);
    return mergeHistoryBars(base, extraBarsRef.current);
    // extraVer is a version tick for extraBarsRef mutations (refs are invisible to deps).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isIntraday, intradayData, symbol, extraVer]);

  // Fresh-per-render feed (oldest loaded bar) for the stable scroll-back handler.
  useEffect(() => {
    const server = isDaily ? dailyServerBars : intradayServerBars;
    feedRef.current = {
      symbol,
      interval,
      isDaily,
      oldestSec: server?.length ? server[0].time : 0,
    };
  });

  // ---------- Render daily bars ----------
  useEffect(() => {
    if (!seriesRef.current) return;
    if (!isDaily) return;
    if (!dailyServerBars?.length) {
      seriesRef.current.setData([]);
      return;
    }

    seriesRef.current.setData(toChartBars(dailyServerBars));
    // L3: repaint on every poll, but re-fit the viewport only when the
    // symbol or interval changes — fitContent on every 60s poll yanks the
    // user's scroll/zoom back to the full range.
    const key = `${symbol}|${interval}`;
    if (fitKeyRef.current !== key) {
      fitKeyRef.current = key;
      chartRef.current?.timeScale().fitContent();
    }
  }, [dailyServerBars, symbol, interval, isDaily]);

  // ---------- Render intraday / W / M bars ----------
    useEffect(() => {
      if (!seriesRef.current) return;
      if (!isIntraday) return;
      if (!intradayServerBars?.length) {
        seriesRef.current.setData([]);
        return;
      }

      seriesRef.current.setData(toChartBars(intradayServerBars));
      // L3: same no-yank rule as daily.
      const key = `${symbol}|${interval}`;
      if (fitKeyRef.current !== key) {
        fitKeyRef.current = key;
        chartRef.current?.timeScale().fitContent();
      }
    }, [intradayServerBars, symbol, interval, isIntraday]);

  // ---------- Live tick: self-sufficient subscription (shared atom writer) ----------
  const tick = tickMap[`${symbol}.${exchange}`];
  useEffect(() => {
    const unsub = marketDataService.onSymbolData((s, data) => {
      if (s !== symbol || !data) return;
      setTickData((prev) => ({
        ...prev,
        [`${s}.${exchange}`]: {
          symbol: s,
          exchange,
          ltp: data.ltp,
          pChange: data.pChange,
          yearHigh: data.yearHigh,
          yearLow: data.yearLow,
          updatedAt: Date.now(),
        },
      }));
    });
    marketDataService.requestSymbolData([symbol]);
    return unsub;
  }, [symbol, exchange, setTickData]);

  // ---------- EOD reference (last history bar) for the LIVE/EOD badge ----------
  const eodInfo = useMemo(() => {
    if (isDaily) {
      if (!histData?.candles?.length || histData._symbol !== symbol) return null;
      const last = histData.candles[histData.candles.length - 1];
      const [, m, d] = last.Date.split('-');
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return { close: last.close, label: `${d}-${months[Number(m) - 1] ?? m}` };
    }
    if (!intradayData?.candles?.length || intradayData._symbol !== symbol) return null;
    const last = intradayData.candles[intradayData.candles.length - 1];
    const label = new Date(last.timestamp).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
    return { close: last.close, label };
  }, [histData, intradayData, symbol, isDaily]);

  const tickAgeMs = tick?.updatedAt ? Date.now() - tick.updatedAt : Number.POSITIVE_INFINITY;
  const tickFresh = tick != null && tickAgeMs < 5 * 60_000 && isMarketHours();
  // Brewing-grade freshness (L4): ticks older than 2 minutes never paint —
  // the chart falls back to pure server data instead of a frozen live bar.
  const tickLive = tick != null && tickAgeMs <= LIVE_STALE_MS && isMarketHours();
  const isStale = isDaily ? histData?.is_stale === true : false;
  const liveVsEodPct =
    tickFresh && tick && eodInfo && eodInfo.close !== 0
      ? ((tick.ltp - eodInfo.close) / eodInfo.close) * 100
      : null;
  const inrFmt = useMemo(
    () => new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    [],
  );

  // ---------- Live brewing bar (Addendum L) ----------
  // Merges the latest WS tick into the candle series in memory via
  // series.update (no viewport yank). Server data always wins (L2): every
  // 60s poll repaints via setData in the render effects above, then this
  // effect — declared after them — re-applies the brewing bar, or drops it
  // once the tick goes stale so no frozen live bar lingers.
  useEffect(() => {
    const main = seriesRef.current;
    if (!main) return;
    const server = isDaily ? dailyServerBars : intradayServerBars;
    if (!server?.length) {
      brewActiveRef.current = false;
      return;
    }
    const t = tick;
    if (!tickLive || t == null || !Number.isFinite(t.ltp) || t.ltp <= 0) {
      if (brewActiveRef.current) {
        main.setData(toChartBars(server));
        brewActiveRef.current = false;
      }
      return;
    }
    const now = Date.now();
    const brewed = isDaily
      ? brewDaily(server, t.ltp, now)
      : brewIntraday(server, t.ltp, now, interval);
    const last = brewed[brewed.length - 1];
    if (!last) return;
    main.update({
      time: last.time as Time,
      open: last.o,
      high: last.h,
      low: last.l,
      close: last.c,
    });
    brewActiveRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    tick?.ltp,
    tick?.updatedAt,
    tickLive,
    dailyServerBars,
    intradayServerBars,
    symbol,
    interval,
    isDaily,
  ]);

  // ---------- Indicators + LIVE price line (one combined overlay effect) ----------
  useEffect(() => {
    const chart = chartRef.current;
    const main = seriesRef.current;
    if (!chart || !main) return;

    // Teardown previous overlays: LIVE line, indicator series, extra panes.
    if (liveLineRef.current) {
      try {
        main.removePriceLine(liveLineRef.current);
      } catch {
        /* already removed with a prior teardown */
      }
      liveLineRef.current = null;
    }
    for (const s of indicatorSeriesRef.current) {
      try {
        chart.removeSeries(s);
      } catch {
        /* already removed */
      }
    }
    indicatorSeriesRef.current = [];
    // Remove only indicator-owned panes (by identity) — the script pane and
    // any other foreign pane survive.
    for (const p of indicatorPanesRef.current) {
      const idx = chart.panes().indexOf(p);
      if (idx > 0) {
        try {
          chart.removePane(idx);
        } catch {
          /* already removed */
        }
      }
    }
    indicatorPanesRef.current = [];

    // Rebuild bars from the merged server memos (scroll-back included).
    let bars: IndicatorCandle[] = [];
    const server = isDaily ? dailyServerBars : intradayServerBars;
    if (!server?.length) return;
    bars = server.map((b) => ({
      time: b.time,
      open: b.o,
      high: b.h,
      low: b.l,
      close: b.c,
      volume: b.v,
    }));
    if (bars.length === 0) return;

    // LIVE line on all intervals — dashed amber, history untouched.
    if (tickFresh && tick && Number.isFinite(tick.ltp)) {
      liveLineRef.current = main.createPriceLine({
        price: tick.ltp,
        color: '#FFB900',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'LIVE',
      });
    }

    const times = bars.map((b) => b.time);
    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    const vols = bars.map((b) => b.volume);

    const toLineData = (vals: (number | null)[]) =>
      times.flatMap((t, i) =>
        vals[i] == null ? [] : [{ time: t as Time, value: vals[i] as number }],
      );

    const addOverlayLine = (vals: (number | null)[], color: string, dashed = false) => {
      const s = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData(toLineData(vals));
      indicatorSeriesRef.current.push(s);
      return s;
    };

    const addOscillatorPane = () => {
      // A new pane is created implicitly by adding a series at the next index.
      return chart.panes().length;
    };

    /** Record a pane created by addSeries-at-end so teardown owns it. */
    const trackOscPane = () => {
      const panes = chart.panes();
      const created = panes[panes.length - 1];
      if (created && !indicatorPanesRef.current.includes(created)) {
        indicatorPanesRef.current.push(created);
      }
    };

    const addOscLine = (
      vals: (number | null)[],
      color: string,
      paneIndex: number,
      bands?: number[],
    ) => {
      const s = chart.addSeries(
        LineSeries,
        {
          color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
        },
        paneIndex,
      );
      s.setData(toLineData(vals));
      chart.panes()[paneIndex]?.setStretchFactor(0.35);
      trackOscPane();
      if (bands) {
        for (const level of bands) {
          s.createPriceLine({
            price: level,
            color: '#787B86',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: '',
          });
        }
      }
      indicatorSeriesRef.current.push(s);
      return s;
    };

    for (const ind of indicators) {
      if (!ind.visible) continue;
      const p = ind.params;
      switch (ind.type) {
        case 'SMA':
          addOverlayLine(sma(closes, p.period ?? 20), ind.color);
          break;
        case 'EMA':
          addOverlayLine(ema(closes, p.period ?? 20), ind.color);
          break;
        case 'BB': {
          const bb = bollinger(closes, p.period ?? 20, p.mult ?? 2);
          addOverlayLine(bb.basis, ind.color);
          addOverlayLine(bb.upper, ind.color, true);
          addOverlayLine(bb.lower, ind.color, true);
          break;
        }
        case 'VWAP':
          // Persisted VWAP on D/W/M is skipped (menu disables adding it there).
          if (interval === 'D' || interval === 'W' || interval === 'M') break;
          addOverlayLine(sessionVWAP(bars), ind.color);
          break;
        case 'VOLUME': {
          const up = '#26a69a';
          const dn = '#ef5350';
          const s = chart.addSeries(HistogramSeries, {
            priceScaleId: 'vol',
            priceFormat: { type: 'volume' },
          });
          s.setData(
            bars.map((b) => ({
              time: b.time as Time,
              value: b.volume,
              color: b.close >= b.open ? up : dn,
            })),
          );
          chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
          indicatorSeriesRef.current.push(s);
          break;
        }
        case 'RSI':
          addOscLine(rsi(closes, p.period ?? 14), ind.color, addOscillatorPane(), [70, 50, 30]);
          break;
        case 'MACD': {
          const m = macd(closes, p.fast ?? 12, p.slow ?? 26, p.signal ?? 9);
          const paneIndex = addOscillatorPane();
          const histS = chart.addSeries(
            HistogramSeries,
            { priceScaleId: '', priceFormat: { type: 'price', precision: 4, minMove: 0.0001 } },
            paneIndex,
          );
          histS.setData(
            times.flatMap((t, i) =>
              m.hist[i] == null
                ? []
                : [{
                    time: t as Time,
                    value: m.hist[i] as number,
                    color: (m.hist[i] as number) >= 0 ? '#26a69a' : '#ef5350',
                  }],
            ),
          );
          chart.panes()[paneIndex]?.setStretchFactor(0.35);
          trackOscPane();
          indicatorSeriesRef.current.push(histS);
          addOscLine(m.macdLine, ind.color, paneIndex);
          addOscLine(m.signalLine, '#FF6D00', paneIndex);
          break;
        }
        case 'STOCH': {
          const st = stochastic(highs, lows, closes, p.k ?? 14, p.slowing ?? 3, p.d ?? 3);
          const paneIndex = addOscillatorPane();
          addOscLine(st.k, ind.color, paneIndex, [80, 20]);
          addOscLine(st.d, '#FF6D00', paneIndex);
          break;
        }
        case 'ATR':
          addOscLine(atr(highs, lows, closes, p.period ?? 14), ind.color, addOscillatorPane());
          break;
        case 'OBV':
          addOscLine(obv(closes, vols), ind.color, addOscillatorPane());
          break;
        default:
          break;
      }
    }

    return () => {
      // Cleanup runs at the top of the next invocation; this guards unmount.
      if (liveLineRef.current && seriesRef.current) {
        try {
          seriesRef.current.removePriceLine(liveLineRef.current);
        } catch {
          /* already removed */
        }
        liveLineRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dailyServerBars, intradayServerBars, symbol, interval, indicators, tick?.ltp, tick?.updatedAt]);

  // ---------- Script Lab v1 ----------
  // Declared AFTER the main overlay effect: same-component hook order
  // guarantees script painting runs after indicator teardown/rebuild, and
  // all script artifacts live in the hook's own refs.
  const { slots: scriptSlots, details: scriptDetails, refetchSlots } =
    useScriptSlots(panelId);
  const [scriptHandoff, setScriptHandoff] = useAtom(scriptChartHandoffAtom);
  const [scriptLastError, setScriptLastError] = useAtom(scriptLastErrorAtom);

  // Bars in ScriptBar shape — the merged server memos above, so scripts
  // see scroll-back history too (full loaded history, Part C).
  const scriptBars: ScriptBar[] = useMemo(() => {
    const server = isDaily ? dailyServerBars : intradayServerBars;
    if (!server?.length) return [];
    return server.map((b) => ({ time: b.time, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v }));
  }, [isDaily, dailyServerBars, intradayServerBars]);

  // Scripts see the same brewing bar as the candles, flagged live:true
  // (L5) — so script outputs track the forming bar instead of stopping at
  // the last settled server bar. Falls back to pure server bars when stale.
  const liveScriptBars: ScriptBar[] = useMemo(() => {
    const t = tick;
    if (!tickLive || t == null || !Number.isFinite(t.ltp) || t.ltp <= 0) return scriptBars;
    const now = Date.now();
    const brewed = isDaily
      ? brewDaily(scriptBars, t.ltp, now)
      : brewIntraday(scriptBars, t.ltp, now, interval);
    // v is always present: server volume survives in-place updates and
    // fresh forming bars are stamped v: 0 — never undefined (NaN guard).
    return brewed as ScriptBar[];
  }, [scriptBars, tick?.ltp, tick?.updatedAt, tickLive, isDaily, interval]);

  const needsFundamentals = useMemo(
    () =>
      scriptSlots.some(
        (s) =>
          s.enabled &&
          scriptDetails.get(s.script_id)?.head?.manifest?.needs_fundamentals === true,
      ),
    [scriptSlots, scriptDetails],
  );
  const fundState = useScriptFundamentals({ symbol, needed: needsFundamentals });

  // 3-strike auto-disable persists enabled:false so the slot stays off.
  const handleScriptStrikeOut = (slot: { script_id: number; param_values: Record<string, number | boolean | string> }, message: string) => {
    setScriptLastError({ panelId, scriptId: slot.script_id, message, ts: Date.now() });
    setChartSlot(panelId, {
      script_id: slot.script_id,
      enabled: false,
      param_values: slot.param_values,
    })
      .then(() => refetchSlots())
      .catch(() => {
        /* slots refetch on next poll; error atom already shows the cause */
      });
  };

  useScriptedOverlays({
    panelId,
    symbol,
    exchange,
    interval,
    bars: liveScriptBars,
    slots: scriptSlots,
    details: scriptDetails,
    fundamentals: fundState.state === 'ready' ? fundState.data : undefined,
    chartRef,
    mainRef: seriesRef,
    onStrikeOut: handleScriptStrikeOut,
  });

  // AI → chart handoff: enabling the accepted script on this panel.
  // param_values omitted → backend keeps tuned params; the detail query is
  // invalidated so the NEW head rev paints instead of the 60s-stale one.
  // Stale handoffs (>60s, e.g. accepted with no chart open) are dropped so a
  // later mount with the same panel id never auto-enables a stale script.
  useEffect(() => {
    if (!scriptHandoff || scriptHandoff.panelId !== panelId) return;
    if (Date.now() - scriptHandoff.ts > 60000) {
      // Card already reads "accepted", so a silent drop leaves the user
      // guessing — flag it through the same surface as other script errors.
      setScriptLastError({
        panelId,
        scriptId: scriptHandoff.scriptId,
        message: 'Script handoff expired (>60s) — accept the card again or enable it from the script menu.',
        ts: Date.now(),
      });
      setScriptHandoff(null);
      return;
    }
    setChartSlot(panelId, {
      script_id: scriptHandoff.scriptId,
      enabled: true,
    })
      .then(() => {
        void queryClient.invalidateQueries({ queryKey: ['script-detail', scriptHandoff.scriptId] });
        void queryClient.invalidateQueries({ queryKey: ['scripts-catalog'] });
        void refetchSlots();
      })
      .catch(() => {
        /* menu surfaces retry; handoff still consumed below */
      });
    setScriptHandoff(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptHandoff, panelId]);

  // ---------- Toolbar / form handlers ----------
  const handleSymbolChange = (value: string) => {
    setInputSymbol(value);
    setActiveIndex(-1);

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    const query = value.trim().toUpperCase();
    if (!query) {
      setAutocompleteResults([]);
      setShowDropdown(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/py/stockuniverse/search/${encodeURIComponent(query)}`);
        if (!res.ok) {
          setAutocompleteResults([]);
          setShowDropdown(false);
          return;
        }
        const results = (await res.json()) as SymbolSearchResult[];
        setAutocompleteResults(results);
        setShowDropdown(results.length > 0);
      } catch {
        setAutocompleteResults([]);
        setShowDropdown(false);
      }
    }, 300);
  };

  const handleSelectResult = (result: SymbolSearchResult) => {
    setInputSymbol(result.symbol);
    setShowDropdown(false);
    setAutocompleteResults([]);
    // Suggestions come from the NSE stock-universe search, so the result is
    // NSE even if the exchange box holds something else (e.g. BSE) — pin it
    // instead of pairing an NSE symbol with the wrong exchange (dead ticks).
    const ex = 'NSE';
    setInputExchange(ex);
    // Loading from inside this chart detaches it from the global symbol.
    setOverrides((prev) => ({ ...prev, [panelId]: { symbol: result.symbol, exchange: ex } }));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDropdown || autocompleteResults.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => Math.min(prev + 1, autocompleteResults.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => Math.max(prev - 1, -1));
    } else if (e.key === 'Enter') {
      if (activeIndex >= 0 && autocompleteResults[activeIndex]) {
        e.preventDefault();
        handleSelectResult(autocompleteResults[activeIndex]);
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  };

  const handleSymbolSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setShowDropdown(false);
    const s = inputSymbol.trim().toUpperCase();
    const ex = inputExchange.trim().toUpperCase();
    if (!s || !ex) return;
    setOverrides((prev) => ({ ...prev, [panelId]: { symbol: s, exchange: ex } }));
  };

  const handleIntervalChange = (newInterval: Interval) => {
    setInterval(newInterval);
  };

  const isFocused = focusedPanel === panelId;

  return (
    <div className="h-full w-full flex flex-col bg-terminal-bg">
      {/* Symbol / Exchange / Interval toolbar */}
      <form
        onSubmit={handleSymbolSubmit}
        className="flex items-center gap-1 px-2 py-1 border-b border-terminal-gray text-xs font-mono flex-shrink-0"
      >
        <input
          type="text"
          value={inputExchange}
          onChange={(e) => setInputExchange(e.target.value.toUpperCase())}
          placeholder="NSE"
          className="w-14 bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase text-center"
        />
        <span className="text-white/60">:</span>
        <div ref={searchContainerRef} className="flex-1 relative">
          <input
            type="text"
            value={inputSymbol}
            onChange={(e) => handleSymbolChange(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              if (autocompleteResults.length > 0) setShowDropdown(true);
            }}
            placeholder="RELIANCE"
            className="w-full bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase"
          />
          {showDropdown && autocompleteResults.length > 0 && (
            <div className="absolute z-50 left-0 right-0 top-full mt-0.5 bg-black border border-terminal-gray max-h-48 overflow-y-auto shadow-lg">
              {autocompleteResults.slice(0, 10).map((result, index) => (
                <div
                  key={result.symbol}
                  onClick={() => handleSelectResult(result)}
                  className={`px-1.5 py-1 cursor-pointer flex items-center justify-between text-xs hover:bg-zinc-800 ${
                    index === activeIndex ? 'bg-zinc-800 text-terminal-amber' : 'text-white/70'
                  }`}
                >
                  <span className="text-terminal-amber font-bold font-mono">{result.symbol}</span>
                  <span className="ml-2 truncate text-white/70 text-[11px] font-sans text-right">{result.companyName}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <button
          type="submit"
          className="px-2 py-0.5 bg-blue-800 hover:bg-blue-700 text-white border border-blue-500 text-xs"
        >
          GO
        </button>

            <div className="flex gap-0.5 ml-1">
              {ALL_INTERVALS.map((iv) => {
                const isActive = interval === iv;
                return (
                  <button
                    key={iv}
                    type="button"
                    onClick={() => handleIntervalChange(iv)}
                    className={`px-1.5 py-0.5 text-[10px] font-mono border transition-colors ${
                      isActive
                        ? 'bg-terminal-green text-black border-terminal-green font-bold shadow-[0_0_6px_rgba(0,255,0,0.4)]'
                        : 'border-terminal-gray/80 text-white/50 hover:border-white/40 hover:text-white bg-black/40'
                    }`}
                  >
                    {iv}
                  </button>
                );
              })}
            </div>

            <div className="ml-1">
              <ChartIndicatorMenu
                interval={interval}
                active={indicators}
                onChange={(next) => setSavedIndicators({ v: 1, items: next })}
              />
            </div>

            <div className="ml-1">
              <ChartScriptsMenu
                panelId={panelId}
                slots={scriptSlots}
                details={scriptDetails}
                refetchSlots={refetchSlots}
                lastError={
                  scriptLastError && scriptLastError.panelId === panelId
                    ? scriptLastError.message
                    : null
                }
              />
            </div>

        {isLoading && <span className="text-white/70 text-[10px] ml-1">LOADING…</span>}
        {isError && <span className="text-terminal-red text-[10px] ml-1">FETCH ERR</span>}

        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className="px-1.5 py-0.5 text-[10px] border border-terminal-gray text-white/70 hover:text-terminal-amber hover:border-terminal-amber bg-black disabled:opacity-40 ml-1"
          title="Refresh chart data"
        >
          ↺
        </button>

        <button
          type="button"
          onClick={() => {
            if (chartRef.current && seriesRef.current) {
              chartRef.current.timeScale().fitContent();
              seriesRef.current.priceScale().applyOptions({ autoScale: true });
            }
          }}
          className="px-1.5 py-0.5 text-[10px] border border-terminal-gray text-white/70 hover:text-terminal-amber hover:border-terminal-amber bg-black ml-0.5"
          title="Recenter chart"
        >
          ⊡
        </button>

        {/* LIVE vs EOD badge — explains LTP/close gaps (e.g. corporate actions) */}
        {eodInfo && (
          <span className="text-[10px] font-mono ml-1 whitespace-nowrap">
            {tickFresh && tick ? (
              <>
                <span className="text-terminal-amber font-bold">
                  LIVE {inrFmt.format(tick.ltp)}
                </span>
                <span className="text-white/50">
                  {' '}· EOD {inrFmt.format(eodInfo.close)} (
                  {liveVsEodPct != null
                    ? `${liveVsEodPct >= 0 ? '+' : ''}${liveVsEodPct.toFixed(2)}%`
                    : '—'}
                  ) · EOD as of {eodInfo.label}
                </span>
              </>
            ) : (
              <span className="text-white/50">
                EOD {inrFmt.format(eodInfo.close)} · EOD as of {eodInfo.label}
              </span>
            )}
            {isStale && (
              <span className="ml-1 px-1 border border-terminal-red text-terminal-red">
                STALE
              </span>
            )}
          </span>
        )}

        {!isFocused && (
          <span className="text-white/60 text-[10px] ml-auto">{symbol}</span>
        )}
      </form>

        {/* Chart canvas */}
        <div ref={chartContainerRef} className="flex-1 w-full min-h-0 relative">
        </div>
      </div>
    );
  }
