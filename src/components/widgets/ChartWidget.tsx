'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useQuery } from '@tanstack/react-query';
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

  // Sync input when atom changes externally (e.g. WatchWidget row click)
  useEffect(() => {
    setInputSymbol(symbol);
    setInputExchange(exchange);
  }, [symbol, exchange]);

  const { start, end } = getDateRange(interval);

  const { data: histData, isLoading, isError } = useQuery({
    queryKey: ['history', symbol, exchange, interval],
    queryFn: () => OpenAlgoClient.getHistory(symbol, exchange, interval, start, end),
    staleTime: 60_000,
    retry: 1,
  });

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
  }, [histData]);

  // WebSocket: subscribe to live ticks for last-candle update (mode 2)
  const handleTick = useCallback(
    (data: TickData) => {
      if (data.symbol !== symbol || data.exchange !== exchange) return;
      if (!seriesRef.current) return;
      const now = Math.floor(Date.now() / 1000) as Time;
      seriesRef.current.update({
        time: now,
        open: data.open ?? data.ltp,
        high: data.high ?? data.ltp,
        low: data.low ?? data.ltp,
        close: data.ltp,
      });
    },
    [symbol, exchange]
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
              onClick={() => setInterval(iv)}
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
        {!isFocused && (
          <span className="text-terminal-gray text-[10px] ml-auto">{symbol}</span>
        )}
      </form>

      {/* Chart canvas fills remaining height */}
      <div ref={chartContainerRef} className="flex-1 w-full min-h-0" />
    </div>
  );
}
