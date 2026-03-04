'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import type { PlaceOrderParams, OrderData } from '@/lib/openalgo';

type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
type Product = 'MIS' | 'CNC' | 'NRML';
type Exchange = 'NSE' | 'BSE' | 'NFO' | 'MCX' | 'BFO' | 'CDS';

interface OrderWidgetProps {
  panelId: string;
}

export function OrderWidget({ panelId: _panelId }: OrderWidgetProps) {
  const qc = useQueryClient();
  const activeSymbol = useAtomValue(activeSymbolAtom);
  const activeExchange = useAtomValue(activeExchangeAtom);

  const [symbol, setSymbol] = useState(activeSymbol);
  const [exchange, setExchange] = useState<Exchange>(activeExchange as Exchange);
  const [qty, setQty] = useState('1');
  const [orderType, setOrderType] = useState<OrderType>('MARKET');
  const [product, setProduct] = useState<Product>('MIS');
  const [price, setPrice] = useState('0');
  const [triggerPrice, setTriggerPrice] = useState('0');
  const [status, setStatus] = useState<{ type: 'success' | 'error' | 'pending'; msg: string } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Sync symbol from focused panel atom changes
  useEffect(() => {
    setSymbol(activeSymbol);
    setExchange(activeExchange as Exchange);
  }, [activeSymbol, activeExchange]);

  // Recent orders
  const { data: orderBookData } = useQuery({
    queryKey: ['orderbook'],
    queryFn: () => OpenAlgoClient.getOrderBook(),
    refetchInterval: 10_000,
    staleTime: 8_000,
    retry: 1,
  });
  const recentOrders: OrderData[] = (orderBookData?.data?.orders ?? []).slice(0, 8);

  const handleOrder = useCallback(
    async (side: 'BUY' | 'SELL') => {
      setIsSubmitting(true);
      setStatus({ type: 'pending', msg: `Submitting ${side} ${qty} ${symbol}...` });
      try {
        const params: PlaceOrderParams = {
          symbol,
          exchange,
          action: side,
          quantity: qty,
          price: orderType === 'MARKET' ? '0' : price,
          order_type: orderType,
          product,
          ...(orderType === 'SL' || orderType === 'SL-M'
            ? { trigger_price: triggerPrice }
            : {}),
        };
        const result = await OpenAlgoClient.placeOrder(params);
        setStatus({ type: 'success', msg: `Order ${result.orderid}: ${result.message}` });
        // Refresh order book
        void qc.invalidateQueries({ queryKey: ['orderbook'] });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setStatus({ type: 'error', msg });
      } finally {
        setIsSubmitting(false);
      }
    },
    [symbol, exchange, qty, price, triggerPrice, orderType, product, qc]
  );

  // Keyboard shortcuts F1=BUY F2=SELL
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'F1') { e.preventDefault(); void handleOrder('BUY'); }
      if (e.key === 'F2') { e.preventDefault(); void handleOrder('SELL'); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleOrder]);

  const needsPrice = orderType === 'LIMIT' || orderType === 'SL';
  const needsTrigger = orderType === 'SL' || orderType === 'SL-M';

  const inputClass = 'bg-black border border-terminal-gray text-white p-1 w-full text-right font-mono text-xs';
  const labelClass = 'text-terminal-amber text-xs min-w-[70px]';
  const selectClass = 'bg-black border border-terminal-gray text-white p-1 w-full font-mono text-xs outline-none';

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-zinc-950 overflow-hidden">
      <div className="font-bold text-sm text-blue-400 border-b border-terminal-gray px-2 py-1 flex-shrink-0">
        ORDER TICKET
      </div>

      <div className="flex-1 overflow-auto p-2">
        <div className="flex flex-col gap-1.5">
          {/* Symbol */}
          <div className="flex items-center gap-2">
            <label className={labelClass}>SYMBOL:</label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className={inputClass}
            />
          </div>

          {/* Exchange */}
          <div className="flex items-center gap-2">
            <label className={labelClass}>EXCHANGE:</label>
            <select
              value={exchange}
              onChange={(e) => setExchange(e.target.value as Exchange)}
              className={selectClass}
            >
              {(['NSE', 'BSE', 'NFO', 'MCX', 'BFO', 'CDS'] as Exchange[]).map((ex) => (
                <option key={ex} value={ex}>{ex}</option>
              ))}
            </select>
          </div>

          {/* Product */}
          <div className="flex items-center gap-2">
            <label className={labelClass}>PRODUCT:</label>
            <select
              value={product}
              onChange={(e) => setProduct(e.target.value as Product)}
              className={selectClass}
            >
              <option value="MIS">MIS (Intraday)</option>
              <option value="CNC">CNC (Delivery)</option>
              <option value="NRML">NRML (Futures/Options)</option>
            </select>
          </div>

          {/* Quantity */}
          <div className="flex items-center gap-2">
            <label className={labelClass}>QTY:</label>
            <input
              type="number"
              value={qty}
              min="1"
              onChange={(e) => setQty(e.target.value)}
              className={inputClass}
            />
          </div>

          {/* Order Type */}
          <div className="flex items-center gap-2">
            <label className={labelClass}>TYPE:</label>
            <select
              value={orderType}
              onChange={(e) => setOrderType(e.target.value as OrderType)}
              className={selectClass}
            >
              <option value="MARKET">MARKET</option>
              <option value="LIMIT">LIMIT</option>
              <option value="SL">SL</option>
              <option value="SL-M">SL-M</option>
            </select>
          </div>

          {/* Price (LIMIT / SL) */}
          {needsPrice && (
            <div className="flex items-center gap-2">
              <label className={labelClass}>PRICE:</label>
              <input
                type="number"
                value={price}
                step="0.05"
                onChange={(e) => setPrice(e.target.value)}
                className={inputClass}
              />
            </div>
          )}

          {/* Trigger Price (SL / SL-M) */}
          {needsTrigger && (
            <div className="flex items-center gap-2">
              <label className={labelClass}>TRIGGER:</label>
              <input
                type="number"
                value={triggerPrice}
                step="0.05"
                onChange={(e) => setTriggerPrice(e.target.value)}
                className={inputClass}
              />
            </div>
          )}
        </div>

        {/* BUY / SELL buttons */}
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => void handleOrder('BUY')}
            disabled={isSubmitting}
            className="flex-1 bg-blue-700 hover:bg-blue-600 text-white font-bold py-2 border border-blue-400 disabled:opacity-50"
          >
            BUY [F1]
          </button>
          <button
            onClick={() => void handleOrder('SELL')}
            disabled={isSubmitting}
            className="flex-1 bg-red-700 hover:bg-red-600 text-white font-bold py-2 border border-red-400 disabled:opacity-50"
          >
            SELL [F2]
          </button>
        </div>

        {/* Status line */}
        {status && (
          <div
            className={`mt-1.5 px-1 py-1 text-[10px] font-mono border-l-2 ${
              status.type === 'success'
                ? 'text-terminal-green border-terminal-green'
                : status.type === 'error'
                ? 'text-terminal-red border-terminal-red'
                : 'text-terminal-amber border-terminal-amber'
            }`}
          >
            &gt; {status.msg}
          </div>
        )}

        {/* Recent orders */}
        {recentOrders.length > 0 && (
          <div className="mt-3">
            <div className="text-terminal-gray text-[10px] mb-1 border-b border-terminal-gray pb-0.5">
              RECENT ORDERS
            </div>
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="text-terminal-gray text-[9px]">
                  <th className="p-0.5">SYMBOL</th>
                  <th className="p-0.5">ACT</th>
                  <th className="p-0.5 text-right">QTY</th>
                  <th className="p-0.5 text-right">STATUS</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((o) => (
                  <tr key={o.orderid} className="border-b border-terminal-gray hover:bg-zinc-900">
                    <td className="p-0.5 text-terminal-amber">{o.symbol}</td>
                    <td className={`p-0.5 font-bold ${o.action === 'BUY' ? 'text-blue-400' : 'text-terminal-red'}`}>
                      {o.action}
                    </td>
                    <td className="p-0.5 text-right">{o.quantity}</td>
                    <td className={`p-0.5 text-right text-[9px] ${
                      o.order_status === 'complete' ? 'text-terminal-green' : 
                      o.order_status === 'rejected' ? 'text-terminal-red' : 'text-terminal-amber'
                    }`}>
                      {o.order_status.toUpperCase()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
