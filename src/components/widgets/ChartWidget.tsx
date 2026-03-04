'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom, useSetAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, focusedPanelAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import { wsService } from '@/lib/socket';
import type { TickData } from '@/lib/socket';

type Interval = '1m' | '5m' | '15m' | '1h' | 'D';

interface ChartWidgetProps {
  panelId: string;
}

function formatDate(date: Date): string {
  // Format date as YYYY-MM-DD in IST (Asia/Kolkata, UTC+5:30)
  return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
}

function getDateRange(interval: Interval): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (interval) {
    case '1m': start.setDate(end.getDate() - 5); break;
    case '5m': start.setDate(end.getDate() - 14); break;
    case '15m': start.setDate(end.getDate() - 30); break;
    case '1h': start.setDate(end.getDate() - 90); break;
    case 'D': start.setFullYear(end.getFullYear() - 1); break;
  }
  return { start: formatDate(start), end: formatDate(end) };
}

/**
 * Get the candle period in seconds for a given interval.
 */
function getCandlePeriodSeconds(interval: Interval): number {
  switch (interval) {
    case '1m': return 60;
    case '5m': return 300;
    case '15m': return 900;
    case '1h': return 3600;
    case 'D': return 86400;
  }
}

/**
 * Calculate the candle timestamp for a given Unix timestamp and interval.
 */
function alignToCandle(timestampSeconds: number, periodSeconds: number): number {
  return Math.floor(timestampSeconds / periodSeconds) * periodSeconds;
}

export function ChartWidget({ panelId }: ChartWidgetProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null);

  // Global active symbol — single source of truth across all widgets
  const [symbol, setSymbol] = useAtom(activeSymbolAtom);
  const [exchange, setExchange] = useAtom(activeExchangeAtom);
  const [focusedPanel] = useAtom(focusedPanelAtom);

  const [inputSymbol, setInputSymbol] = useState(symbol);
  const [inputExchange, setInputExchange] = useState(exchange);
  const [interval, setInterval] = useState<Interval>('D');
  const [pendingInterval, setPendingInterval] = useState<Interval | null>(null);

  // Candle state for aggregating ticks based on selected timeframe
  interface PartialCandle {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }
  const partialCandleRef = useRef<PartialCandle | null>(null);
  const lastCumulativeVolumeRef = useRef<number | null>(null);
  const lastHistBarTimeRef = useRef<number | null>(null);

  // Sync input fields when global symbol changes (e.g. WatchWidget / TopWidget click)
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
    // Tag result with symbol+exchange so the object reference always changes
    // when the query key changes, even when data is served from cache.
    select: (data) => ({ ...data, _symbol: symbol, _exchange: exchange }),
  });

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['history', symbol, exchange, interval] });
  };

  // When data loads successfully, confirm the pending interval change
  useEffect(() => {
    if (!isLoading && !isError && pendingInterval !== null) {
      setPendingInterval(null);
    }
  }, [isLoading, isError, pendingInterval]);

  // If there's an error, revert the pending interval
  useEffect(() => {
    if (isError && pendingInterval !== null) {
      setPendingInterval(null);
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
      localization: {
        locale: 'en-IN', timeFormatter: (t: number) =>
          new Date(t * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })
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
  }, []); // intentionally empty — chart created once

  // Clear chart and reset refs immediately when symbol or exchange changes
  useEffect(() => {
    if (seriesRef.current) {
      seriesRef.current.setData([]);
    }
    partialCandleRef.current = null;
    lastCumulativeVolumeRef.current = null;
    lastHistBarTimeRef.current = null;
  }, [symbol, exchange]);

  // Populate chart with historical data
  // Depends on histData AND symbol/exchange — the select() tag ensures histData
  // is always a new object reference when the symbol changes, so this effect
  // reliably fires even when new data is served from React Query cache.
  useEffect(() => {
    if (!seriesRef.current) return;

    if (!histData?.data?.length) {
      seriesRef.current.setData([]);
      return;
    }

    // Guard: skip if the tagged symbol/exchange don't match current values
    // (protects against a stale cached result arriving after a rapid switch)
    if (histData._symbol !== symbol || histData._exchange !== exchange) return;

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

    lastHistBarTimeRef.current = bars[bars.length - 1].time as number;
    partialCandleRef.current = null;
    lastCumulativeVolumeRef.current = null;
  }, [histData, symbol, exchange]);

  // Reset candle refs when interval changes (histData may come from cache unchanged)
  useEffect(() => {
    partialCandleRef.current = null;
    lastCumulativeVolumeRef.current = null;
    lastHistBarTimeRef.current = null;
  }, [interval]);

  // WebSocket: subscribe to live ticks for last-candle update (mode 2)
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
      const tickSeconds = data.timestamp
        ? Math.floor(new Date(data.timestamp).getTime() / 1000)
        : Math.floor(Date.now() / 1000);
      const candleTime = alignToCandle(tickSeconds, periodSeconds);

      if (interval === 'D') {
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
        const cumVol = data.volume ?? 0;
        const prevCumVol = lastCumulativeVolumeRef.current ?? cumVol;
        const volDelta = Math.max(0, cumVol - prevCumVol);
        lastCumulativeVolumeRef.current = cumVol;

        if (!partialCandleRef.current || partialCandleRef.current.time !== candleTime) {
          if (partialCandleRef.current) {
            seriesRef.current.update({
              time: partialCandleRef.current.time as Time,
              open: partialCandleRef.current.open,
              high: partialCandleRef.current.high,
              low: partialCandleRef.current.low,
              close: partialCandleRef.current.close,
            });
          }
          partialCandleRef.current = {
            time: candleTime,
            open: data.ltp,
            high: data.ltp,
            low: data.ltp,
            close: data.ltp,
            volume: volDelta,
          };
        } else {
          partialCandleRef.current.high = Math.max(partialCandleRef.current.high, data.ltp);
          partialCandleRef.current.low = Math.min(partialCandleRef.current.low, data.ltp);
          partialCandleRef.current.close = data.ltp;
          partialCandleRef.current.volume += volDelta;
        }

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
    setSymbol(s);
    setExchange(ex);
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
              className={`px-1.5 py-0.5 text-[10px] border ${interval === iv
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
          onClick={() => {
            if (chartRef.current && seriesRef.current) {
              chartRef.current.timeScale().fitContent();
              seriesRef.current.priceScale().applyOptions({ autoScale: true });
            }
          }}
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
