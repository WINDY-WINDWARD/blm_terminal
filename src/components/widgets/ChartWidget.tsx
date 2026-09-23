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
import type { IChartApi, IPriceLine, ISeriesApi, Time } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import {
  activeSymbolAtom,
  activeExchangeAtom,
  chartSymbolOverridesAtom,
  focusedPanelAtom,
  tickDataAtom,
  chartIndicatorsAtom,
} from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';
import { ChartIndicatorMenu } from './ChartIndicatorMenu';
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
): Promise<IntradayOHLCVResponse> {
  const res = await fetch(
    `/api/py/ticker/intraday/${encodeURIComponent(symbol)}?interval=${interval}`,
  );
  if (!res.ok) throw new Error(`Backend error ${res.status}`);
  return res.json() as Promise<IntradayOHLCVResponse>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChartWidget({ panelId }: ChartWidgetProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null);
  const indicatorSeriesRef = useRef<ISeriesApi<'Line' | 'Histogram', Time>[]>([]);
  const liveLineRef = useRef<IPriceLine | null>(null);
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

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Clear chart when symbol, exchange, or interval changes
  useEffect(() => {
    if (seriesRef.current) {
      seriesRef.current.setData([]);
    }
  }, [symbol, exchange, interval]);

  // ---------- Render daily bars ----------
  useEffect(() => {
    if (!seriesRef.current) return;
    if (!isDaily) return;
    if (!histData?.candles?.length) {
      seriesRef.current.setData([]);
      return;
    }
    if (histData._symbol !== symbol) return;

    const bars = histData.candles
      .map((candle) => ({
        time: (new Date(candle.Date + 'T00:00:00Z').getTime() / 1000) as Time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));

    seriesRef.current.setData(bars);
    chartRef.current?.timeScale().fitContent();
  }, [histData, symbol, isDaily]);

  // ---------- Render intraday / W / M bars ----------
    useEffect(() => {
      if (!seriesRef.current) return;
      if (!isIntraday) return;
      if (!intradayData?.candles?.length) {
        seriesRef.current.setData([]);
        return;
      }
      if (intradayData._symbol !== symbol) return;
  
      const bars = intradayData.candles
        .map((candle) => ({
          // NSE charting timestamps are Unix ms – divide by 1000 for lightweight-charts
          time: Math.floor(candle.timestamp / 1000) as Time,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));
  
      seriesRef.current.setData(bars);
      chartRef.current?.timeScale().fitContent();
    }, [intradayData, symbol, isIntraday]);

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
  const isStale = isDaily ? histData?.is_stale === true : false;
  const liveVsEodPct =
    tickFresh && tick && eodInfo && eodInfo.close !== 0
      ? ((tick.ltp - eodInfo.close) / eodInfo.close) * 100
      : null;
  const inrFmt = useMemo(
    () => new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    [],
  );

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
    while (chart.panes().length > 1) {
      chart.removePane(chart.panes().length - 1);
    }

    // Rebuild bars with the same mapping as the render effects above.
    let bars: IndicatorCandle[] = [];
    if (isDaily) {
      if (!histData?.candles?.length || histData._symbol !== symbol) return;
      bars = histData.candles
        .map((c) => ({
          time: new Date(c.Date + 'T00:00:00Z').getTime() / 1000,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume,
        }))
        .sort((a, b) => a.time - b.time);
    } else {
      if (!intradayData?.candles?.length || intradayData._symbol !== symbol) return;
      bars = intradayData.candles
        .map((c) => ({
          time: Math.floor(c.timestamp / 1000),
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume,
        }))
        .sort((a, b) => a.time - b.time);
    }
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
  }, [histData, intradayData, symbol, interval, indicators, tick?.ltp, tick?.updatedAt]);

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
