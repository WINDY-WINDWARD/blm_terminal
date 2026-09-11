'use client';

import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, focusedPanelAtom } from '@/store/terminalStore';

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

  const [symbol, setSymbol] = useAtom(activeSymbolAtom);
  const [exchange, setExchange] = useAtom(activeExchangeAtom);
  const [focusedPanel] = useAtom(focusedPanelAtom);

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

  // Sync input fields when global symbol changes
  useEffect(() => {
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
    const ex = inputExchange.trim().toUpperCase() || 'NSE';
    setSymbol(result.symbol);
    setExchange(ex);
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
    setSymbol(s);
    setExchange(ex);
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
                    className={`px-1.5 py-0.5 text-[10px] font-mono border transition-all ${
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
