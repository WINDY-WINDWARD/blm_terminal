'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { symbolPerPanelAtom, exchangePerPanelAtom, focusedPanelAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import { wsService } from '@/lib/socket';
import type { TickData } from '@/lib/socket';

type Interval = '1m' | '5m' | '15m' | '1h' | 'D';

interface ChartWidgetProps {
  panelId: string;
}

function formatDate(date: Date): string {
  return date.toISOString().split('T')[0];
}

function getDateRange(interval: Interval): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (interval) {
    case '1m':  start.setDate(end.getDate() - 5);           break;
    case '5m':  start.setDate(end.getDate() - 14);          break;
    case '15m': start.setDate(end.getDate() - 30);          break;
    case '1h':  start.setDate(end.getDate() - 90);          break;
    case 'D':   start.setFullYear(end.getFullYear() - 1);   break;
  }
  return { start: formatDate(start), end: formatDate(end) };
}

/**
 * Get the candle period in seconds for a given interval.
 * This determines how ticks are grouped into candles.
 */
function getCandlePeriodSeconds(interval: Interval): number {
  switch (interval) {
    case '1m':  return 60;
    case '5m':  return 300;
    case '15m': return 900;
    case '1h':  return 3600;
    case 'D':   return 86400; // 24 hours
  }
}

/**
 * Calculate the candle timestamp for a given Unix timestamp and interval.
 * This aligns ticks to the correct candle period (e.g., 15:05:00 for a 5m candle).
 */
function alignToCandle(timestampSeconds: number, periodSeconds: number): number {
  return Math.floor(timestampSeconds / periodSeconds) * periodSeconds;
}

export function ChartWidget({ panelId }: ChartWidgetProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null);

  const [symbolPerPanel, setSymbolPerPanel] = useAtom(symbolPerPanelAtom);
  const [exchangePerPanel, setExchangePerPanel] = useAtom(exchangePerPanelAtom);
  const [focusedPanel] = useAtom(focusedPanelAtom);

  const symbol = symbolPerPanel[panelId] ?? 'RELIANCE';
  const exchange = exchangePerPanel[panelId] ?? 'NSE';

  const [inputSymbol, setInputSymbol] = useState(symbol);
  const [inputExchange, setInputExchange] = useState(exchange);
  const [interval, setInterval] = useState<Interval>('D');
  const [pendingInterval, setPendingInterval] = useState<Interval | null>(null);

  // Candle state for aggregating ticks based on selected timeframe
  interface PartialCandle {
    time: number; // aligned candle timestamp (seconds)
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }
  const partialCandleRef = useRef<PartialCandle | null>(null);
  // Tracks the last seen cumulative day volume for computing per-candle volume delta
  const lastCumulativeVolumeRef = useRef<number | null>(null);
  // Timestamp (epoch seconds) of the last bar in the historical dataset.
  // Used for the daily interval so the live candle time matches exactly what
  // lightweight-charts already has, avoiding timezone-alignment mismatches.
  const lastHistBarTimeRef = useRef<number | null>(null);

  // Sync input when atom changes externally (e.g. WatchWidget row click)
  useEffect(() => {
    setInputSymbol(symbol);
    setInputExchange(exchange);
  }, [symbol, exchange]);

  const { start, end } = getDateRange(interval);

  const queryClient = useQueryClient();

  const { data: histData, isLoading, isError } = useQuery({
    queryKey: ['history', symbol, exchange, interval],
    queryFn: () => OpenAlgoClient.getHistory(symbol, exchange, interval, start, end),
    staleTime: 60_000,
    retry: 1,
  });

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['history', symbol, exchange, interval] });
  };

  // When data loads successfully, confirm the pending interval change
  useEffect(() => {
    if (!isLoading && !isError && pendingInterval !== null) {
      setPendingInterval(null); // Clear pending state
    }
  }, [isLoading, isError, pendingInterval]);

  // If there's an error, revert the pending interval
  useEffect(() => {
    if (isError && pendingInterval !== null) {
      setPendingInterval(null); // User will see old interval highlighted
    }
  }, [isError, pendingInterval]);

  // Build chart (once on mount)
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#000000' },
        textColor: '#FFB900',
      },
      grid: {
        vertLines: { color: '#222' },
        horzLines: { color: '#222' },
      },
      crosshair: { mode: 1 },
      timeScale: { timeVisible: true, secondsVisible: false },
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
  }, []); // intentionally empty — chart created once

  // Populate chart with historical data
  useEffect(() => {
    if (!seriesRef.current || !histData?.data?.length) return;
    const bars = histData.data
      .map((bar) => ({
        time: bar.timestamp as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));

    seriesRef.current.setData(bars);
    chartRef.current?.timeScale().fitContent();

    // Record the last bar's timestamp so the daily live candle can reuse it
    lastHistBarTimeRef.current = bars[bars.length - 1].time as number;

    // Reset partial candle and cumulative volume tracking when historical data changes
    partialCandleRef.current = null;
    lastCumulativeVolumeRef.current = null;
    // Note: lastHistBarTimeRef is intentionally NOT reset here — it was just set above
  }, [histData]);

  // Also reset when interval changes (histData may be served from cache and not change)
  useEffect(() => {
    partialCandleRef.current = null;
    lastCumulativeVolumeRef.current = null;
    lastHistBarTimeRef.current = null;
  }, [interval]);

  // WebSocket: subscribe to live ticks for last-candle update (mode 2)
  // Aggregates ticks into candles based on the selected interval.
  //
  // OpenAlgo Mode-2 tick fields:
  //   data.ltp    = last traded price (the actual current price)
  //   data.open   = day open (9:15 AM) — correct only for daily candles
  //   data.high   = day running high   — correct only for daily candles
  //   data.low    = day running low    — correct only for daily candles
  //   data.close  = previous day's close (NOT the current price — never use this)
  //   data.volume = cumulative day volume (must compute delta for intraday candles)
  const handleTick = useCallback(
    (data: TickData) => {
      if (data.symbol !== symbol || data.exchange !== exchange) return;
      if (!seriesRef.current) return;

      const periodSeconds = getCandlePeriodSeconds(interval);
      // Use the server-side tick timestamp when available so candle boundaries
      // are computed from market time, not browser wall-clock (avoids period
      // mismatches caused by network latency or minor clock drift).
      const tickSeconds = data.timestamp
        ? Math.floor(new Date(data.timestamp).getTime() / 1000)
        : Math.floor(Date.now() / 1000);
      const candleTime = alignToCandle(tickSeconds, periodSeconds);

      if (interval === 'D') {
        // ── Daily candle ────────────────────────────────────────────────────
        // data.open/high/low are day-level values — correct to use directly.
        // data.volume is the cumulative day volume — correct for a daily bar.
        //
        // IMPORTANT: do NOT use candleTime (computed from tick timestamp) for
        // the daily bar. The historical bars use whatever epoch the OpenAlgo
        // server produces (often IST midnight = UTC 18:30 previous day), which
        // will never equal a UTC-midnight-aligned candleTime. Reuse the last
        // historical bar's timestamp so the update() call hits the correct bar.
        const dailyCandleTime = lastHistBarTimeRef.current ?? candleTime;
        const dailyBar = {
          time: dailyCandleTime,
          open: data.open ?? data.ltp,
          high: data.high ?? data.ltp,
          low: data.low ?? data.ltp,
          close: data.ltp,
          volume: data.volume ?? 0,
        };
        partialCandleRef.current = dailyBar;
        seriesRef.current.update({
          time: dailyBar.time as Time,
          open: dailyBar.open,
          high: dailyBar.high,
          low: dailyBar.low,
          close: dailyBar.close,
        });
      } else {
        // ── Intraday candles (1m, 5m, 15m, 1h) ─────────────────────────────
        // data.open/high/low are day-level values — DO NOT use them here.
        // We build O/H/L exclusively from data.ltp.
        // data.volume is cumulative day volume — compute delta to get per-candle volume.
        const cumVol = data.volume ?? 0;
        const prevCumVol = lastCumulativeVolumeRef.current ?? cumVol;
        const volDelta = Math.max(0, cumVol - prevCumVol);
        lastCumulativeVolumeRef.current = cumVol;

        if (!partialCandleRef.current || partialCandleRef.current.time !== candleTime) {
          // Candle period has rolled over — finalise previous candle, start new one
          if (partialCandleRef.current) {
            seriesRef.current.update({
              time: partialCandleRef.current.time as Time,
              open: partialCandleRef.current.open,
              high: partialCandleRef.current.high,
              low: partialCandleRef.current.low,
              close: partialCandleRef.current.close,
            });
          }
          // New candle: open = first ltp seen in this period
          partialCandleRef.current = {
            time: candleTime,
            open: data.ltp,
            high: data.ltp,
            low: data.ltp,
            close: data.ltp,
            volume: volDelta,
          };
        } else {
          // Same candle period — update H/L/C and accumulate volume delta
          partialCandleRef.current.high = Math.max(partialCandleRef.current.high, data.ltp);
          partialCandleRef.current.low = Math.min(partialCandleRef.current.low, data.ltp);
          partialCandleRef.current.close = data.ltp;
          partialCandleRef.current.volume += volDelta;
        }

        // Push the live candle update to the chart
        seriesRef.current.update({
          time: partialCandleRef.current.time as Time,
          open: partialCandleRef.current.open,
          high: partialCandleRef.current.high,
          low: partialCandleRef.current.low,
          close: partialCandleRef.current.close,
        });
      }
    },
    [symbol, exchange, interval]
  );

  useEffect(() => {
    wsService.subscribe(symbol, exchange, 2);
    const unsub = wsService.onTick(handleTick);
    return () => {
      unsub();
      wsService.unsubscribe(symbol, exchange, 2);
    };
  }, [symbol, exchange, handleTick]);

  const handleSymbolSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const s = inputSymbol.trim().toUpperCase();
    const ex = inputExchange.trim().toUpperCase();
    if (!s || !ex) return;
    setSymbolPerPanel((prev) => ({ ...prev, [panelId]: s }));
    setExchangePerPanel((prev) => ({ ...prev, [panelId]: ex }));
  };

  const handleIntervalChange = (newInterval: Interval) => {
    setInterval(newInterval);
    setPendingInterval(newInterval);
  };

  const INTERVALS: Interval[] = ['1m', '5m', '15m', '1h', 'D'];
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
        <span className="text-terminal-gray">:</span>
        <input
          type="text"
          value={inputSymbol}
          onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
          placeholder="RELIANCE"
          className="flex-1 bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase"
        />
        <button
          type="submit"
          className="px-2 py-0.5 bg-blue-800 hover:bg-blue-700 text-white border border-blue-500 text-xs"
        >
          GO
        </button>

        <div className="flex gap-0.5 ml-1">
          {INTERVALS.map((iv) => (
            <button
              key={iv}
              type="button"
              onClick={() => handleIntervalChange(iv)}
              className={`px-1.5 py-0.5 text-[10px] border ${
                interval === iv
                  ? 'bg-terminal-amber text-black border-terminal-amber font-bold'
                  : 'bg-black text-terminal-gray border-terminal-gray hover:text-terminal-amber'
              }`}
            >
              {iv}
            </button>
          ))}
        </div>

        {isLoading && <span className="text-terminal-gray text-[10px] ml-1">LOADING…</span>}
        {isError && <span className="text-terminal-red text-[10px] ml-1">API ERR</span>}

        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className="px-1.5 py-0.5 text-[10px] border border-terminal-gray text-terminal-gray hover:text-terminal-amber hover:border-terminal-amber bg-black disabled:opacity-40 ml-1"
          title="Refresh chart data"
        >
          ↺
        </button>

        <button
          type="button"
          onClick={() => chartRef.current?.timeScale().fitContent()}
          className="px-1.5 py-0.5 text-[10px] border border-terminal-gray text-terminal-gray hover:text-terminal-amber hover:border-terminal-amber bg-black ml-0.5"
          title="Recenter chart"
        >
          ⊡
        </button>

        {!isFocused && (
          <span className="text-terminal-gray text-[10px] ml-auto">{symbol}</span>
        )}
      </form>

      {/* Chart canvas fills remaining height */}
      <div ref={chartContainerRef} className="flex-1 w-full min-h-0" />
    </div>
  );
}
