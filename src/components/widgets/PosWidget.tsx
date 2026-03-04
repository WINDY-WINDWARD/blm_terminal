'use client';

import React from 'react';

export function PosWidget() {
    const data = [
        { symbol: 'RELIANCE', qty: 100, avg: 2900.00, ltp: 2950.45, pnl: 5045.00 },
        { symbol: 'TCS', qty: -50, avg: 4150.00, ltp: 4100.25, pnl: 2487.50 },
        { symbol: 'HDFCBANK', qty: 200, avg: 1450.00, ltp: 1420.10, pnl: -5980.00 },
    ];

    const totalPnl = data.reduce((acc, curr) => acc + curr.pnl, 0);

    return (
        <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
            <div className="flex justify-between p-2 bg-terminal-gray font-bold">
                <span>TOTAL P&L:</span>
                <span className={totalPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red'}>
                    {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}
                </span>
            </div>
            <table className="w-full text-left border-collapse mt-1">
                <thead className="bg-blue-900 text-white sticky top-0">
                    <tr>
                        <th className="p-1 border border-terminal-gray">SYMBOL</th>
                        <th className="p-1 border border-terminal-gray text-right">QTY</th>
                        <th className="p-1 border border-terminal-gray text-right">AVG</th>
                        <th className="p-1 border border-terminal-gray text-right">LTP</th>
                        <th className="p-1 border border-terminal-gray text-right">P&L</th>
                    </tr>
                </thead>
                <tbody>
                    {data.map((row, i) => {
                        const isPos = row.pnl >= 0;
                        const colorClass = isPos ? 'text-terminal-green' : 'text-terminal-red';
                        return (
                            <tr key={i} className="border-b border-terminal-gray hover:bg-zinc-900">
                                <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">{row.symbol}</td>
                                <td className="p-1 text-right border-r border-terminal-gray">{row.qty}</td>
                                <td className="p-1 text-right border-r border-terminal-gray">{row.avg.toFixed(2)}</td>
                                <td className="p-1 text-right border-r border-terminal-gray text-terminal-amber">{row.ltp.toFixed(2)}</td>
                                <td className={`p-1 text-right font-bold ${colorClass}`}>
                                    {isPos ? '+' : ''}{row.pnl.toFixed(2)}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
