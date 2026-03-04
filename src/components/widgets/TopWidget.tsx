'use client';

import React from 'react';

export function TopWidget() {
    const data = [
        { symbol: 'RELIANCE', change: '+2.4%', ltp: '2950.45', volume: '1.2M' },
        { symbol: 'TCS', change: '+1.8%', ltp: '4100.25', volume: '800K' },
        { symbol: 'INFY', change: '+1.2%', ltp: '1680.00', volume: '2.1M' },
        { symbol: 'HDFCBANK', change: '-1.5%', ltp: '1420.10', volume: '3.4M' },
        { symbol: 'ITC', change: '-0.8%', ltp: '420.50', volume: '5.6M' },
    ];

    return (
        <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
            <table className="w-full text-left border-collapse">
                <thead className="bg-blue-900 text-white sticky top-0">
                    <tr>
                        <th className="p-1 border border-terminal-gray">SYMBOL</th>
                        <th className="p-1 border border-terminal-gray text-right">CHG%</th>
                        <th className="p-1 border border-terminal-gray text-right">LTP</th>
                        <th className="p-1 border border-terminal-gray text-right">VOL</th>
                    </tr>
                </thead>
                <tbody>
                    {data.map((row, i) => {
                        const isUp = row.change.startsWith('+');
                        const colorClass = isUp ? 'text-terminal-green' : 'text-terminal-red';
                        return (
                            <tr key={i} className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer">
                                <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">{row.symbol}</td>
                                <td className={`p-1 text-right border-r border-terminal-gray ${colorClass}`}>{row.change}</td>
                                <td className="p-1 text-right border-r border-terminal-gray">{row.ltp}</td>
                                <td className="p-1 text-right">{row.volume}</td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
