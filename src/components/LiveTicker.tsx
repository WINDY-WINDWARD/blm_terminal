'use client';

import React from 'react';

export function LiveTicker() {
    // Temporary mock data. Will integrate with OpenAlgo WebSocket later.
    const tickerItems = [
        { symbol: 'NSE:RELIANCE-EQ', price: '2,950.45', change: '+1.2%' },
        { symbol: 'NSE:HDFCBANK-EQ', price: '1,420.10', change: '-0.5%' },
        { symbol: 'NSE:INFY-EQ', price: '1,680.00', change: '+0.8%' },
        { symbol: 'NSE:TCS-EQ', price: '4,100.25', change: '+2.1%' },
        { symbol: 'NSE:ITC-EQ', price: '420.50', change: '-0.1%' },
        { symbol: 'NSE:SBIN-EQ', price: '750.30', change: '+1.5%' },
    ];

    return (
        <div className="h-6 bg-terminal-gray border-t border-terminal-gray flex items-center overflow-hidden whitespace-nowrap text-xs font-mono shrink-0">
            <div className="animate-ticker inline-block px-10">
                {tickerItems.map((item, i) => {
                    const isUp = item.change.startsWith('+');
                    return (
                        <span key={i} className="mx-6">
                            <span className="text-terminal-amber">{item.symbol}</span>
                            <span className={`ml-2 ${isUp ? 'text-terminal-green' : 'text-terminal-red'}`}>
                                {item.price} ({item.change})
                            </span>
                        </span>
                    );
                })}
                {/* Duplicate for seamless scrolling */}
                {tickerItems.map((item, i) => {
                    const isUp = item.change.startsWith('+');
                    return (
                        <span key={`dup-${i}`} className="mx-6">
                            <span className="text-terminal-amber">{item.symbol}</span>
                            <span className={`ml-2 ${isUp ? 'text-terminal-green' : 'text-terminal-red'}`}>
                                {item.price} ({item.change})
                            </span>
                        </span>
                    );
                })}
            </div>
        </div>
    );
}
