'use client';

import React, { useState } from 'react';
import { OpenAlgoClient } from '@/lib/openalgo';

export function OrderWidget() {
    const [symbol, setSymbol] = useState('RELIANCE');
    const [qty, setQty] = useState('1');
    const [price, setPrice] = useState('0');
    const [orderType, setOrderType] = useState<'MARKET' | 'LIMIT'>('MARKET');
    const [status, setStatus] = useState<string | null>(null);

    const handleOrder = async (side: 'BUY' | 'SELL') => {
        try {
            setStatus(`Submitting ${side}...`);
            // Note: OpenAlgo client might throw if connection fails. 
            // For standalone prototyping, we simply show the intended effect.
            // await OpenAlgoClient.placeOrder({ symbol, side, quantity: Number(qty), type: orderType, price: orderType === 'LIMIT' ? Number(price) : undefined });

            // MOCK
            setTimeout(() => setStatus(`SUCCESS: ${side} ${qty} ${symbol} @ ${orderType}`), 500);
        } catch (err: any) {
            setStatus(`ERROR: ${err.message}`);
        }
    };

    return (
        <div className="h-full w-full flex flex-col font-sans text-xs bg-zinc-950 p-2">
            <div className="font-bold text-sm text-blue-400 border-b border-terminal-gray pb-1 mb-2">ORDER TICKET</div>

            <div className="flex flex-col gap-2 flex-1">
                <div className="flex justify-between items-center">
                    <label className="text-terminal-amber">SYMBOL:</label>
                    <input
                        type="text"
                        value={symbol}
                        onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                        className="bg-black border border-terminal-gray text-white p-1 w-2/3 uppercase text-right"
                    />
                </div>

                <div className="flex justify-between items-center">
                    <label className="text-terminal-amber">QTY:</label>
                    <input
                        type="number"
                        value={qty}
                        onChange={(e) => setQty(e.target.value)}
                        className="bg-black border border-terminal-gray text-white p-1 w-2/3 text-right"
                    />
                </div>

                <div className="flex justify-between items-center">
                    <label className="text-terminal-amber">TYPE:</label>
                    <select
                        value={orderType}
                        onChange={(e) => setOrderType(e.target.value as any)}
                        className="bg-black border border-terminal-gray text-white p-1 w-2/3 outline-none"
                    >
                        <option value="MARKET">MARKET</option>
                        <option value="LIMIT">LIMIT</option>
                    </select>
                </div>

                {orderType === 'LIMIT' && (
                    <div className="flex justify-between items-center">
                        <label className="text-terminal-amber">PRICE:</label>
                        <input
                            type="number"
                            value={price}
                            onChange={(e) => setPrice(e.target.value)}
                            className="bg-black border border-terminal-gray text-white p-1 w-2/3 text-right"
                        />
                    </div>
                )}
            </div>

            <div className="mt-4 flex gap-2">
                <button
                    onClick={() => handleOrder('BUY')}
                    className="flex-1 bg-blue-700 hover:bg-blue-600 text-white font-bold py-2 rounded-sm border border-blue-400"
                >
                    BUY (F1)
                </button>
                <button
                    onClick={() => handleOrder('SELL')}
                    className="flex-1 bg-red-700 hover:bg-red-600 text-white font-bold py-2 rounded-sm border border-red-400"
                >
                    SELL (F2)
                </button>
            </div>

            {status && (
                <div className={`mt-2 p-1 text-[10px] font-mono ${status.includes('ERROR') ? 'text-terminal-red' : 'text-terminal-green'}`}>
                    &gt; {status}
                </div>
            )}
        </div>
    );
}
