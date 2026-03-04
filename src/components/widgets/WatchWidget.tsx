'use client';

import React from 'react';

export function WatchWidget() {
    const data = [
        { symbol: 'RELIANCE', ltp: '2950.45', change: '+2.4%' },
        { symbol: 'TCS', ltp: '4100.25', change: '+1.8%' },
        { symbol: 'INFY', ltp: '1680.00', change: '+1.2%' },
        { symbol: 'HDFCBANK', ltp: '1420.10', change: '-1.5%' },
        { symbol: 'ITC', ltp: '420.50', change: '-0.8%' },
        { symbol: 'SBIN', ltp: '750.30', change: '+1.5%' },
    ];

    return (
        <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
            <table className="w-full text-left border-collapse">
                <thead className="bg-blue-900 text-white sticky top-0">
                    <tr>
                        <th className="p-1 border border-terminal-gray">SYMBOL</th>
                        <th className="p-1 border border-terminal-gray text-right">LTP</th>
                        <th className="p-1 border border-terminal-gray text-right">CHG%</th>
                    </tr>
                </thead>
                <tbody>
                    {data.map((row, i) => {
                        const isUp = row.change.startsWith('+');
                        const colorClass = isUp ? 'text-terminal-green' : 'text-terminal-red';
                        return (
                            <tr key={i} className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer">
                                <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">{row.symbol}</td>
                                <td className="p-1 text-right border-r border-terminal-gray">{row.ltp}</td>
                                <td className={`p-1 text-right border-r border-terminal-gray ${colorClass}`}>{row.change}</td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
