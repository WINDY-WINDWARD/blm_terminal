'use client';

import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';

export function ChartWidget() {
    const chartContainerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#000000' },
                textColor: '#FFB900',
            },
            grid: {
                vertLines: { color: '#333' },
                horzLines: { color: '#333' },
            },
            width: chartContainerRef.current.clientWidth,
            height: chartContainerRef.current.clientHeight,
        });

        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#00ff00',
            downColor: '#ff0000',
            borderVisible: false,
            wickUpColor: '#00ff00',
            wickDownColor: '#ff0000',
        });

        // Mock realistic OHLC data
        const data = [];
        let time = Math.floor(Date.now() / 1000) - 86400 * 30; // 30 days ago
        let lastClose = 2900;

        for (let i = 0; i < 60; i++) {
            const volatility = lastClose * 0.02;
            const open = lastClose + (Math.random() - 0.5) * volatility;
            const high = open + Math.random() * volatility;
            const low = open - Math.random() * volatility;
            const close = Math.random() > 0.5 ? high - Math.random() * (high - open) : low + Math.random() * (open - low);

            data.push({
                time: (time + i * 86400) as any,
                open,
                high: Math.max(open, close, high),
                low: Math.min(open, close, low),
                close
            });
            lastClose = close;
        }

        candlestickSeries.setData(data);

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
        };
    }, []);

    return <div ref={chartContainerRef} className="h-full w-full relative" />;
}
