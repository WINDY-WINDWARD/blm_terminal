'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom, useAtomValue } from 'jotai';
import {
  activeSymbolAtom,
  activeExchangeAtom,
  tickDataAtom,
  openAlgoAvailableAtom,
  fundsAtom,
  focusedPanelAtom,
} from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import type { PlaceOrderParams, OrderData, FundsData } from '@/lib/openalgo';

type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
type Product = 'MIS' | 'CNC' | 'NRML';
type Exchange = 'NSE' | 'BSE' | 'NFO' | 'MCX' | 'BFO' | 'CDS';

interface OrderWidgetProps {
  panelId: string;
}

const QUICK_INSTRUMENTS = [
  { symbol: 'RELIANCE' },
  { symbol: 'HDFCBANK' },
  { symbol: 'TCS' },
  { symbol: 'INFY' },
] as const;

export function OrderWidget({ panelId }: OrderWidgetProps) {
  const focusedPanel = useAtomValue(focusedPanelAtom);
  const qc = useQueryClient();
  const [globalSymbol, setGlobalSymbol] = useAtom(activeSymbolAtom);
  const [globalExchange, setGlobalExchange] = useAtom(activeExchangeAtom);
  const tickData = useAtomValue(tickDataAtom);
  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);
  const [globalFunds, setGlobalFunds] = useAtom(fundsAtom);

  const [symbol, setSymbol] = useState(globalSymbol || 'RELIANCE');
  const [exchange, setExchange] = useState<Exchange>((globalExchange as Exchange) || 'NSE');
  const [qty, setQty] = useState('1');
  const [orderType, setOrderType] = useState<OrderType>('MARKET');
  const [product, setProduct] = useState<Product>('MIS');
  const [price, setPrice] = useState('');
  const [triggerPrice, setTriggerPrice] = useState('');
  const [status, setStatus] = useState<{ type: 'success' | 'error' | 'pending'; msg: string } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [orderFilter, setOrderFilter] = useState<'ALL' | 'COMPLETE' | 'PENDING' | 'REJECTED'>('ALL');

  // Sync symbol & exchange from focused panel atom changes
  useEffect(() => {
    if (globalSymbol) setSymbol(globalSymbol);
    if (globalExchange) setExchange(globalExchange as Exchange);
  }, [globalSymbol, globalExchange]);

  // Current instrument live LTP lookup
  const tickKey = `${symbol}.${exchange}`;
  const liveLtp = tickData[tickKey]?.ltp ?? tickData[`${symbol}.NSE`]?.ltp ?? 0;

  // When symbol or exchange changes, clear price so ticket reflects current instrument
  useEffect(() => {
    setPrice('');
    setTriggerPrice('');
  }, [symbol, exchange]);

  // When liveLtp arrives and price is empty or 0, update price field
  useEffect(() => {
    if (liveLtp > 0 && (price === '0' || !price)) {
      setPrice(liveLtp.toFixed(2));
    }
  }, [liveLtp, price]);

  // Query: Funds & Account Margins
  const {
    data: fundsResponse,
    refetch: refetchFunds,
    isFetching: isFundsFetching,
  } = useQuery({
    queryKey: ['funds'],
    queryFn: async () => {
      const res = await OpenAlgoClient.getFunds();
      if (res?.data) {
        setGlobalFunds(res.data);
      }
      return res;
    },
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
    enabled: openAlgoAvailable,
  });

  const fundsData: FundsData | null = fundsResponse?.data ?? globalFunds;

  const parseFund = (val: string | number | undefined | null): number => {
    if (val === undefined || val === null) return 0;
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? 0 : num;
  };

  const availableCash = fundsData ? parseFund(fundsData.availablecash) : 0;
  const collateral = fundsData ? parseFund(fundsData.collateral) : 0;
  const realizedM2M = fundsData ? parseFund(fundsData.m2mrealized) : 0;
  const unrealizedM2M = fundsData ? parseFund(fundsData.m2munrealized) : 0;
  const utilisedMargin = fundsData ? parseFund(fundsData.utiliseddebits) : 0;
  const totalMargin = availableCash + utilisedMargin;
  const marginPct = totalMargin > 0 ? (utilisedMargin / totalMargin) * 100 : 0;
  const availableBuffer = Math.max(0, availableCash - utilisedMargin);

  // Query: Recent Orders
  const {
    data: orderBookData,
    refetch: refetchOrders,
    isFetching: isOrdersFetching,
  } = useQuery({
    queryKey: ['orderbook'],
    queryFn: () => OpenAlgoClient.getOrderBook(),
    refetchInterval: 10_000,
    staleTime: 8_000,
    retry: 1,
  });

  const allOrders: OrderData[] = useMemo(() => orderBookData?.data?.orders ?? [], [orderBookData]);

  const completeOrders = useMemo(
    () => allOrders.filter((o) => o.order_status?.toLowerCase() === 'complete'),
    [allOrders]
  );
  const pendingOrders = useMemo(
    () =>
      allOrders.filter((o) => {
        const s = o.order_status?.toLowerCase();
        return s === 'open' || s === 'pending' || s === 'trigger pending';
      }),
    [allOrders]
  );
  const rejectedOrders = useMemo(
    () =>
      allOrders.filter((o) => {
        const s = o.order_status?.toLowerCase();
        return s === 'rejected' || s === 'cancelled';
      }),
    [allOrders]
  );

  const displayedOrders = useMemo(() => {
    switch (orderFilter) {
      case 'COMPLETE':
        return completeOrders;
      case 'PENDING':
        return pendingOrders;
      case 'REJECTED':
        return rejectedOrders;
      case 'ALL':
      default:
        return allOrders;
    }
  }, [orderFilter, allOrders, completeOrders, pendingOrders, rejectedOrders]);

  // Margin estimation & lot sizing
  const leverage = useMemo(() => {
    switch (product) {
      case 'MIS':
        return 5;
      case 'NRML':
        return 2.5;
      case 'CNC':
      default:
        return 1;
    }
  }, [product]);

  const unitPrice = useMemo(() => {
    const parsedPrice = parseFloat(price);
    if (orderType === 'MARKET') {
      return liveLtp > 0 ? liveLtp : !isNaN(parsedPrice) && parsedPrice > 0 ? parsedPrice : 0;
    }
    return !isNaN(parsedPrice) && parsedPrice > 0 ? parsedPrice : liveLtp > 0 ? liveLtp : 0;
  }, [orderType, price, liveLtp]);

  const qtyNum = Math.max(1, parseInt(qty, 10) || 1);
  const estMargin = unitPrice > 0 ? (qtyNum * unitPrice) / leverage : 0;

  const maxQty = useMemo(() => {
    if (availableCash > 0 && unitPrice > 0) {
      return Math.max(0, Math.floor((availableCash * leverage) / unitPrice));
    }
    return 0;
  }, [availableCash, leverage, unitPrice]);

  const handleSelectSymbol = (sym: string) => {
    const upper = sym.toUpperCase();
    setSymbol(upper);
    setGlobalSymbol(upper);
  };

  const handleSelectExchange = (ex: Exchange) => {
    setExchange(ex);
    setGlobalExchange(ex);
  };

  const addQtyDelta = (delta: number) => {
    const current = parseInt(qty, 10) || 0;
    const nextVal = Math.max(1, current + delta);
    setQty(String(nextVal));
  };

  // Order submission
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
          ...(orderType === 'SL' || orderType === 'SL-M' ? { trigger_price: triggerPrice } : {}),
        };
        const result = await OpenAlgoClient.placeOrder(params);
        setStatus({
          type: 'success',
          msg: `Order ${result.orderid ?? 'PLACED'}: ${result.message || 'Execution routed'}`,
        });
        // Invalidate order book, funds and positions
        void qc.invalidateQueries({ queryKey: ['orderbook'] });
        void qc.invalidateQueries({ queryKey: ['funds'] });
        void qc.invalidateQueries({ queryKey: ['positionbook'] });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setStatus({ type: 'error', msg });
      } finally {
        setIsSubmitting(false);
      }
    },
    [symbol, exchange, qty, price, triggerPrice, orderType, product, qc]
  );

  // Keyboard shortcuts: F1 = BUY, F2 = SELL
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'F1') {
        e.preventDefault();
        void handleOrder('BUY');
      }
      if (e.key === 'F2') {
        e.preventDefault();
        void handleOrder('SELL');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleOrder]);

  const needsPrice = orderType === 'LIMIT' || orderType === 'SL';
  const needsTrigger = orderType === 'SL' || orderType === 'SL-M';

  const bidDisp = liveLtp > 0 ? (liveLtp - 0.3).toFixed(2) : unitPrice > 0 ? (unitPrice - 0.3).toFixed(2) : '—';
  const askDisp = liveLtp > 0 ? liveLtp.toFixed(2) : unitPrice > 0 ? unitPrice.toFixed(2) : '—';

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-[#09090b] text-white overflow-hidden select-none">
      {/* Top Deck Banner */}
      <div className="bg-[#0c0c0f] border-b border-[#27272a] px-3 py-2 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-2">
          <span className="text-terminal-amber font-mono font-bold text-xs tracking-wider">◈ BLM TERMINAL</span>
          <span className="text-zinc-600 font-mono text-xs">|</span>
          <span className="text-white font-mono font-bold text-xs tracking-wide">ORDER & EXECUTION DECK</span>
          <span className="hidden @md:inline-block text-[10px] uppercase font-mono tracking-wider font-bold text-zinc-300 bg-[#121216] border border-[#27272a] px-2 py-0.5 rounded">
            BENTO MATRIX
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-[10px] font-mono font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            {openAlgoAvailable ? 'OPENALGO LIVE' : 'GATEWAY STANDBY'}
          </span>
          <span className="hidden @3xl:inline-block text-[10px] text-zinc-400 font-mono">
            [F1] BUY • [F2] SELL
          </span>
        </div>
      </div>

      {/* Main Bento Matrix Body */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid grid-cols-1 @md:grid-cols-2 @4xl:grid-cols-4 gap-3">

          {/* 1. HERO ORDER TICKET CARD (Col 1-2) */}
          <div className="col-span-1 @md:col-span-1 @4xl:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 flex flex-col justify-between shadow-md">
            <div>
              {/* Bento Card Header */}
              <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-[#27272a]">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                    EXECUTION // ORDER TICKET
                  </span>
                  <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                    {exchange} EQ & DERIVATIVES
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                  <span className="text-[10px] text-emerald-400 font-mono font-bold">LIVE GATEWAY</span>
                </div>
              </div>

              {/* Symbol Picker Pills */}
              <div className="mb-3" data-widget-tour="order-instrument-setup">
                <div className="text-[10px] uppercase font-mono tracking-wider text-zinc-400 font-bold mb-1.5 flex items-center justify-between">
                  <span>SELECT INSTRUMENT</span>
                  <span className="text-[10px] text-zinc-400 font-mono">BROKER: OPENALGO ACTIVE</span>
                </div>
                <div className="grid grid-cols-2 @md:grid-cols-4 gap-1.5">
                  {QUICK_INSTRUMENTS.map((inst) => {
                    const isSelected = symbol === inst.symbol;
                    const instTick = tickData[`${inst.symbol}.${exchange}`] ?? tickData[`${inst.symbol}.NSE`];
                    const instLtp = instTick?.ltp;
                    const instChg = instTick?.pChange;
                    const hasChg = instChg != null;
                    const isUp = hasChg ? instChg >= 0 : true;
                    return (
                      <button
                        key={inst.symbol}
                        type="button"
                        onClick={() => handleSelectSymbol(inst.symbol)}
                        className={`p-2 rounded text-left transition-all border ${
                          isSelected
                            ? 'border-terminal-amber bg-terminal-amber/10 shadow-sm'
                            : 'border-[#27272a] bg-[#121216] hover:border-zinc-500'
                        }`}
                      >
                        <div className="text-xs font-bold font-mono flex items-center justify-between text-white">
                          <span className={isSelected ? 'text-terminal-amber font-black' : 'text-zinc-200'}>
                            {inst.symbol}
                          </span>
                          {hasChg && (
                            <span className={`text-[10px] ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                              {isUp ? '▲' : '▼'}
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-white font-mono font-bold tabular-nums">
                          {instLtp != null
                            ? `₹${instLtp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                            : '—'}
                        </div>
                        <div className={`text-[10px] font-mono tabular-nums ${hasChg ? (isUp ? 'text-emerald-400' : 'text-rose-400') : 'text-zinc-500'}`}>
                          {hasChg ? `${isUp ? '+' : ''}${instChg.toFixed(2)}%` : '—'}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Custom Symbol Input & Exchange Selector */}
              <div className="grid grid-cols-1 @md:grid-cols-3 gap-2 mb-2.5">
                <div className="@md:col-span-2 bg-[#121216] border border-[#27272a] rounded p-1.5">
                  <span className="text-[10px] font-mono text-zinc-300 uppercase tracking-wider block mb-1 font-bold">
                    ACTIVE SYMBOL
                  </span>
                  <input
                    type="text"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                    onBlur={() => {
                      const trimmed = symbol.trim();
                      if (trimmed && trimmed !== globalSymbol) {
                        setGlobalSymbol(trimmed);
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const trimmed = symbol.trim();
                        if (trimmed && trimmed !== globalSymbol) {
                          setGlobalSymbol(trimmed);
                        }
                      }
                    }}
                    placeholder="E.g. RELIANCE, NIFTY..."
                    className="w-full bg-[#09090b] border border-[#27272a] text-white font-mono font-bold text-xs py-1 px-2 rounded uppercase outline-none focus:border-terminal-amber"
                  />
                </div>
                <div className="bg-[#121216] border border-[#27272a] rounded p-1.5">
                  <span className="text-[10px] font-mono text-zinc-300 uppercase tracking-wider block mb-1 font-bold">
                    EXCHANGE
                  </span>
                  <select
                    value={exchange}
                    onChange={(e) => handleSelectExchange(e.target.value as Exchange)}
                    className="w-full bg-[#09090b] border border-[#27272a] text-white font-mono font-bold text-xs py-1 px-1.5 rounded outline-none focus:border-terminal-amber"
                  >
                    {(['NSE', 'BSE', 'NFO', 'MCX', 'BFO', 'CDS'] as Exchange[]).map((ex) => (
                      <option key={ex} value={ex} className="bg-[#0c0c0f] text-white">
                        {ex}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Parameters Grid (Order Type & Product Pills) */}
              <div className="grid grid-cols-1 @md:grid-cols-2 gap-2 mb-2.5" data-widget-tour="order-type-lot-selector">
                {/* Order Type Pills (MKT, LMT, SL, SL-M) */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-1.5">
                  <span className="text-[10px] font-mono text-zinc-300 uppercase tracking-wider block mb-1 font-bold">
                    ORDER TYPE
                  </span>
                  <div className="grid grid-cols-4 gap-1">
                    {(
                      [
                        { key: 'MARKET', label: 'MKT' },
                        { key: 'LIMIT', label: 'LMT' },
                        { key: 'SL', label: 'SL' },
                        { key: 'SL-M', label: 'SL-M' },
                      ] as const
                    ).map((t) => {
                      const isActive = orderType === t.key;
                      return (
                        <button
                          key={t.key}
                          type="button"
                          onClick={() => setOrderType(t.key)}
                          className={`py-1 text-[10px] font-mono font-bold rounded transition-all text-center border ${
                            isActive
                              ? 'bg-terminal-amber text-black border-terminal-amber shadow-sm'
                              : 'bg-[#18181f] text-zinc-300 border-[#27272a] hover:border-zinc-500'
                          }`}
                        >
                          {t.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Product Pills (MIS, CNC, NRML) */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-1.5">
                  <span className="text-[10px] font-mono text-zinc-300 uppercase tracking-wider block mb-1 font-bold">
                    PRODUCT
                  </span>
                  <div className="grid grid-cols-3 gap-1">
                    {(
                      [
                        { key: 'MIS', label: 'MIS', desc: 'Intraday Margin (5x)' },
                        { key: 'CNC', label: 'CNC', desc: 'Cash & Carry (Delivery 1x)' },
                        { key: 'NRML', label: 'NRML', desc: 'Normal F&O Margin (2.5x)' },
                      ] as const
                    ).map((p) => {
                      const isActive = product === p.key;
                      return (
                        <button
                          key={p.key}
                          type="button"
                          title={p.desc}
                          onClick={() => setProduct(p.key)}
                          className={`py-1 text-[10px] font-mono font-bold rounded transition-all text-center border ${
                            isActive
                              ? 'bg-terminal-amber text-black border-terminal-amber shadow-sm'
                              : 'bg-[#18181f] text-zinc-300 border-[#27272a] hover:border-zinc-500'
                          }`}
                        >
                          {p.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Quick Lot Size Pills */}
              <div className="mb-2.5">
                <div className="flex items-center justify-between text-[10px] font-mono text-zinc-300 mb-1">
                  <span className="uppercase tracking-wider font-bold">QUICK LOT SIZE PILLS</span>
                  <span className="text-zinc-400">LOT STEP: 1 SHARE</span>
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  <button
                    type="button"
                    onClick={() => addQtyDelta(1)}
                    className="px-2.5 py-1 text-xs font-mono font-bold rounded bg-[#121216] border border-[#27272a] text-zinc-200 hover:border-terminal-amber hover:text-terminal-amber transition-all"
                  >
                    +1
                  </button>
                  <button
                    type="button"
                    onClick={() => addQtyDelta(5)}
                    className="px-2.5 py-1 text-xs font-mono font-bold rounded bg-[#121216] border border-[#27272a] text-zinc-200 hover:border-terminal-amber hover:text-terminal-amber transition-all"
                  >
                    +5
                  </button>
                  <button
                    type="button"
                    onClick={() => addQtyDelta(10)}
                    className="px-2.5 py-1 text-xs font-mono font-bold rounded bg-[#121216] border border-[#27272a] text-zinc-200 hover:border-terminal-amber hover:text-terminal-amber transition-all"
                  >
                    +10
                  </button>
                  <button
                    type="button"
                    onClick={() => addQtyDelta(50)}
                    className="px-2.5 py-1 text-xs font-mono font-bold rounded bg-[#121216] border border-[#27272a] text-zinc-200 hover:border-terminal-amber hover:text-terminal-amber transition-all"
                  >
                    +50
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (maxQty > 0) setQty(String(maxQty));
                    }}
                    disabled={maxQty <= 0}
                    className="px-2.5 py-1 text-xs font-mono font-bold rounded bg-terminal-amber/15 border border-terminal-amber/40 text-terminal-amber hover:bg-terminal-amber hover:text-black disabled:opacity-40 disabled:pointer-events-none transition-all"
                  >
                    MAX ({maxQty})
                  </button>
                </div>
              </div>

              {/* Input Fields: Qty, Limit Price, Trigger Price */}
              <div className="grid grid-cols-1 @md:grid-cols-3 gap-2 mb-2.5">
                {/* Quantity Input */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2">
                  <label className="text-[10px] font-mono text-zinc-300 uppercase tracking-wider block mb-1 font-bold">
                    QUANTITY
                  </label>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => addQtyDelta(-1)}
                      className="w-7 h-7 flex items-center justify-center bg-[#1a1a24] text-white border border-[#27272a] rounded hover:border-zinc-500 font-bold"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      value={qty}
                      min="1"
                      onChange={(e) => setQty(e.target.value)}
                      className="w-full bg-[#09090b] border border-[#27272a] text-white text-center font-mono font-bold text-sm py-1 rounded outline-none focus:border-terminal-amber tabular-nums"
                    />
                    <button
                      type="button"
                      onClick={() => addQtyDelta(1)}
                      className="w-7 h-7 flex items-center justify-center bg-[#1a1a24] text-white border border-[#27272a] rounded hover:border-zinc-500 font-bold"
                    >
                      +
                    </button>
                  </div>
                </div>

                {/* Limit Price Input */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2">
                  <div className="flex items-center justify-between text-[10px] font-mono text-zinc-300 mb-1">
                    <span className="uppercase tracking-wider font-bold">LIMIT PRICE (₹)</span>
                    <span className="text-zinc-400 text-[9px] font-bold">
                      {orderType === 'MARKET' ? 'MARKET' : 'LMT'}
                    </span>
                  </div>
                  <input
                    type="number"
                    value={price}
                    step="0.05"
                    onChange={(e) => setPrice(e.target.value)}
                    disabled={!needsPrice}
                    className={`w-full bg-[#09090b] border border-[#27272a] text-right font-mono font-bold text-sm py-1 px-2 rounded outline-none focus:border-terminal-amber tabular-nums ${
                      !needsPrice ? 'text-zinc-500 cursor-not-allowed' : 'text-white'
                    }`}
                  />
                </div>

                {/* Trigger Price Input */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2">
                  <div className="flex items-center justify-between text-[10px] font-mono text-zinc-300 mb-1">
                    <span className="uppercase tracking-wider font-bold">TRIGGER PRICE (₹)</span>
                    <span className="text-zinc-400 text-[9px] font-bold">
                      {needsTrigger ? 'ARMED' : 'OPTIONAL'}
                    </span>
                  </div>
                  <input
                    type="number"
                    value={triggerPrice}
                    step="0.05"
                    onChange={(e) => setTriggerPrice(e.target.value)}
                    disabled={!needsTrigger}
                    className={`w-full bg-[#09090b] border border-[#27272a] text-right font-mono font-bold text-sm py-1 px-2 rounded outline-none focus:border-terminal-amber tabular-nums ${
                      !needsTrigger ? 'text-zinc-500 cursor-not-allowed' : 'text-white'
                    }`}
                  />
                </div>
              </div>

              {/* Best Bid / Ask Depth Preview & Margin Estimate */}
              <div className="bg-[#121216] border border-[#27272a] rounded p-2 mb-3 flex flex-col @md:flex-row items-center justify-between text-[11px] font-mono gap-2">
                <div className="flex items-center gap-3">
                  <span className="text-zinc-300 font-bold">SPREAD:</span>
                  <span className="text-emerald-400 font-bold">BID ₹{bidDisp}</span>
                  <span className="text-zinc-600">|</span>
                  <span className="text-rose-400 font-bold">ASK ₹{askDisp}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-zinc-300 font-bold">EST. MARGIN:</span>
                  <span className="text-terminal-amber font-bold tabular-nums">
                    ₹{estMargin.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                  <span className="text-zinc-400 text-[10px]">({leverage}x {product})</span>
                </div>
              </div>
            </div>

            {/* Prominent F1 BUY and F2 SELL Buttons */}
            <div data-widget-tour="order-execution-buttons">
              <div className="grid grid-cols-2 gap-2.5 pt-1">
                <button
                  type="button"
                  onClick={() => void handleOrder('BUY')}
                  disabled={isSubmitting}
                  className="bg-emerald-600/20 hover:bg-emerald-600/30 active:scale-[0.99] text-emerald-400 border border-emerald-500/40 font-mono font-bold py-2.5 px-3 rounded text-sm tracking-wider flex items-center justify-center gap-2 shadow-lg shadow-emerald-950/40 transition-all disabled:opacity-50"
                >
                  <span className="bg-emerald-500/30 text-emerald-300 text-[10px] px-1.5 py-0.5 rounded font-black tracking-normal border border-emerald-500/40">
                    [F1]
                  </span>
                  <span>BUY {symbol}</span>
                </button>

                <button
                  type="button"
                  onClick={() => void handleOrder('SELL')}
                  disabled={isSubmitting}
                  className="bg-rose-600/20 hover:bg-rose-600/30 active:scale-[0.99] text-rose-400 border border-rose-500/40 font-mono font-bold py-2.5 px-3 rounded text-sm tracking-wider flex items-center justify-center gap-2 shadow-lg shadow-rose-950/40 transition-all disabled:opacity-50"
                >
                  <span className="bg-rose-500/30 text-rose-300 text-[10px] px-1.5 py-0.5 rounded font-black tracking-normal border border-rose-500/40">
                    [F2]
                  </span>
                  <span>SELL {symbol}</span>
                </button>
              </div>

              {/* Status Banner */}
              {status && (
                <div
                  className={`mt-2 px-2.5 py-1.5 rounded text-xs font-mono font-bold border flex items-center gap-2 ${
                    status.type === 'success'
                      ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400'
                      : status.type === 'error'
                      ? 'bg-rose-500/10 border-rose-500/40 text-rose-400'
                      : 'bg-terminal-amber/10 border-terminal-amber/40 text-terminal-amber'
                  }`}
                >
                  <span>{status.type === 'success' ? '✓' : status.type === 'error' ? '⚠' : '⚡'}</span>
                  <span>{status.msg}</span>
                </div>
              )}
            </div>
          </div>

          {/* 2. ACCOUNT MARGINS & FUNDS KPI CARD (Col 3-4) */}
          <div className="col-span-1 @md:col-span-1 @4xl:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 flex flex-col justify-between shadow-md" data-widget-tour="order-risk-kpi-deck">
            <div>
              {/* Bento Card Header */}
              <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-[#27272a]">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                    RISK // ACCOUNT MARGINS & FUNDS
                  </span>
                  <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                    {openAlgoAvailable ? 'OPENALGO LIVE' : 'OFFLINE'}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span
                    className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${
                      openAlgoAvailable && fundsData
                        ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
                        : 'text-zinc-400 bg-zinc-800 border-zinc-700'
                    }`}
                  >
                    {openAlgoAvailable && fundsData ? 'COLLATERAL SYNCED' : 'NO BROKER DATA'}
                  </span>
                </div>
              </div>

              {/* 4 Micro KPI Cards (2x2 Grid) */}
              <div className="grid grid-cols-2 gap-2 mb-3">
                {/* Available Cash */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2.5 hover:border-zinc-500 transition-colors">
                  <div className="text-[10px] uppercase font-mono tracking-wider text-zinc-300 font-bold mb-1 flex items-center justify-between">
                    <span>AVAILABLE CASH</span>
                    <span className="text-emerald-400 text-xs">●</span>
                  </div>
                  <div className="text-base @md:text-lg font-mono font-bold text-white tabular-nums">
                    ₹{availableCash.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
                    Liquid Cleared Funds
                  </div>
                </div>

                {/* Collateral Margin */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2.5 hover:border-zinc-500 transition-colors">
                  <div className="text-[10px] uppercase font-mono tracking-wider text-zinc-300 font-bold mb-1 flex items-center justify-between">
                    <span>COLLATERAL MARGIN</span>
                    <span className="text-blue-400 text-xs">●</span>
                  </div>
                  <div className="text-base @md:text-lg font-mono font-bold text-zinc-100 tabular-nums">
                    ₹{collateral.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
                    Pledged Securities Margin
                  </div>
                </div>

                {/* Realized M2M */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2.5 hover:border-zinc-500 transition-colors">
                  <div className="text-[10px] uppercase font-mono tracking-wider text-zinc-300 font-bold mb-1 flex items-center justify-between">
                    <span>REALIZED M2M</span>
                    <span className={`text-xs ${realizedM2M >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {realizedM2M >= 0 ? '▲' : '▼'}
                    </span>
                  </div>
                  <div className={`text-base @md:text-lg font-mono font-bold tabular-nums ${
                    realizedM2M >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {realizedM2M >= 0 ? '+' : ''}₹{realizedM2M.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
                    Settled Day Profit / Loss
                  </div>
                </div>

                {/* Unrealized M2M */}
                <div className="bg-[#121216] border border-[#27272a] rounded p-2.5 hover:border-zinc-500 transition-colors">
                  <div className="text-[10px] uppercase font-mono tracking-wider text-zinc-300 font-bold mb-1 flex items-center justify-between">
                    <span>UNREALIZED M2M</span>
                    <span className="text-terminal-amber text-xs">⚡</span>
                  </div>
                  <div className={`text-base @md:text-lg font-mono font-bold tabular-nums ${
                    unrealizedM2M >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {unrealizedM2M >= 0 ? '+' : ''}₹{unrealizedM2M.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
                    Floating Live Across Open Legs
                  </div>
                </div>
              </div>

              {/* Utilised Margin Progress Bar & Cushion Indicator */}
              <div className="bg-[#121216] border border-[#27272a] rounded p-2.5 mb-2.5">
                <div className="flex items-center justify-between text-xs font-mono font-bold mb-1.5">
                  <span className="text-zinc-200">UTILISED MARGIN</span>
                  <span className="text-terminal-amber tabular-nums">
                    {marginPct.toFixed(1)}% USED{' '}
                    <span className="text-zinc-400 font-normal">
                      (₹{utilisedMargin.toLocaleString('en-IN')} / ₹{totalMargin.toLocaleString('en-IN')})
                    </span>
                  </span>
                </div>

                {/* Progress Bar */}
                <div className="w-full bg-[#09090b] h-3 rounded overflow-hidden border border-[#27272a] flex relative">
                  <div
                    style={{ width: `${Math.min(100, Math.max(0, marginPct))}%` }}
                    className="h-full bg-gradient-to-r from-emerald-500 via-terminal-amber to-rose-500 rounded-sm transition-all duration-500"
                  />
                  <div className="absolute inset-0 flex justify-between px-1 pointer-events-none text-[8px] font-mono text-zinc-400 items-center">
                    <span>0%</span>
                    <span className="text-zinc-300 font-bold">50% THRESHOLD</span>
                    <span className="text-rose-400 font-bold">85% MARGIN CALL</span>
                  </div>
                </div>

                {/* Secondary Risk Buffers */}
                <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-[#27272a]/60 text-[10px] font-mono">
                  <div>
                    <span className="text-zinc-400 block font-bold">AVAILABLE BUFFER</span>
                    <span className="text-white font-bold tabular-nums">
                      ₹{availableBuffer.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-400 block font-bold">PEAK VA-R EXPOSURE</span>
                    <span className="text-white font-bold tabular-nums">
                      ₹{utilisedMargin.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-400 block font-bold">MAX LEVERAGE CAP</span>
                    <span className="text-terminal-amber font-bold">5.0x PERMITTED</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Quick Capital Actions */}
            <div className="flex items-center justify-between pt-1 text-[11px] font-mono">
              <span className="text-zinc-400">
                Broker Gateway: {openAlgoAvailable ? 'OpenAlgo Active Engine' : 'Offline Engine'}
              </span>
              <button
                type="button"
                onClick={() => void refetchFunds()}
                disabled={isFundsFetching}
                className="px-2.5 py-1 rounded bg-[#18181f] border border-[#27272a] text-zinc-200 hover:border-terminal-amber hover:text-terminal-amber transition-all font-bold disabled:opacity-50"
              >
                {isFundsFetching ? '⚡ AUDITING...' : '⚡ RE-AUDIT MARGINS'}
              </button>
            </div>
          </div>

          {/* 3. RECENT EXECUTIONS & ORDER BOOK (Col 1-4) */}
          <div className="col-span-1 @md:col-span-2 @4xl:col-span-4 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 shadow-md" data-widget-tour="order-book-table">
            {/* Card Header & Filter Chips */}
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-[#27272a]">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                  AUDIT // RECENT EXECUTIONS & ORDER BOOK
                </span>
                <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                  SYNCHRONIZED WITH EXCHANGE ENGINE
                </span>
              </div>

              {/* Filter Chips & Refresh */}
              <div className="flex items-center gap-1.5 text-[11px] font-mono">
                <button
                  type="button"
                  onClick={() => setOrderFilter('ALL')}
                  className={`px-2 py-0.5 rounded font-bold border transition-all ${
                    orderFilter === 'ALL'
                      ? 'bg-terminal-amber text-black border-terminal-amber'
                      : 'bg-[#121216] text-zinc-300 border-[#27272a] hover:border-zinc-500'
                  }`}
                >
                  ALL ({allOrders.length})
                </button>
                <button
                  type="button"
                  onClick={() => setOrderFilter('COMPLETE')}
                  className={`px-2 py-0.5 rounded font-bold border transition-all ${
                    orderFilter === 'COMPLETE'
                      ? 'bg-terminal-amber text-black border-terminal-amber'
                      : 'bg-[#121216] text-zinc-300 border-[#27272a] hover:border-zinc-500'
                  }`}
                >
                  COMPLETE ({completeOrders.length})
                </button>
                <button
                  type="button"
                  onClick={() => setOrderFilter('PENDING')}
                  className={`px-2 py-0.5 rounded font-bold border transition-all ${
                    orderFilter === 'PENDING'
                      ? 'bg-terminal-amber text-black border-terminal-amber'
                      : 'bg-[#121216] text-zinc-300 border-[#27272a] hover:border-zinc-500'
                  }`}
                >
                  PENDING ({pendingOrders.length})
                </button>
                <button
                  type="button"
                  onClick={() => setOrderFilter('REJECTED')}
                  className={`px-2 py-0.5 rounded font-bold border transition-all ${
                    orderFilter === 'REJECTED'
                      ? 'bg-terminal-amber text-black border-terminal-amber'
                      : 'bg-[#121216] text-zinc-300 border-[#27272a] hover:border-zinc-500'
                  }`}
                >
                  REJECTED ({rejectedOrders.length})
                </button>
                <button
                  type="button"
                  onClick={() => void refetchOrders()}
                  disabled={isOrdersFetching}
                  className="px-2 py-0.5 rounded bg-[#18181f] text-zinc-300 border border-[#27272a] hover:border-zinc-500 text-[10px] ml-1"
                  title="Refresh Order Book"
                >
                  {isOrdersFetching ? '↻ ...' : '↻'}
                </button>
              </div>
            </div>

            {/* Order Book Table */}
            <div className="overflow-x-auto max-h-64 custom-scroll">
              <table className="w-full text-left font-mono text-xs border-collapse">
                <thead>
                  <tr className="text-[10px] uppercase text-zinc-300 border-b border-[#27272a] bg-[#121216] sticky top-0 z-10">
                    <th className="py-2 px-2.5 font-bold">TIMESTAMP</th>
                    <th className="py-2 px-2 font-bold">ORDER ID</th>
                    <th className="py-2 px-2 font-bold">SYMBOL</th>
                    <th className="py-2 px-2 text-center font-bold">SIDE</th>
                    <th className="py-2 px-2 font-bold">TYPE</th>
                    <th className="py-2 px-2 font-bold">PROD</th>
                    <th className="py-2 px-2 text-right font-bold">QTY</th>
                    <th className="py-2 px-2 text-right font-bold">PRICE (₹)</th>
                    <th className="py-2 px-2.5 text-center font-bold">STATUS</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#27272a]/60">
                  {displayedOrders.map((o) => {
                    const statusStr = (o.order_status || 'UNKNOWN').toLowerCase();
                    const isComplete = statusStr === 'complete';
                    const isPending = statusStr === 'open' || statusStr === 'pending' || statusStr === 'trigger pending';
                    const isRejected = statusStr === 'rejected' || statusStr === 'cancelled';
                    const isBuy = (o.action || 'BUY').toUpperCase() === 'BUY';

                    return (
                      <tr key={o.orderid} className="hover:bg-zinc-900/50 transition-colors">
                        <td className="py-2 px-2.5 text-zinc-300 tabular-nums text-[11px]">
                          {o.timestamp || '—'}
                        </td>
                        <td className="py-2 px-2 text-zinc-200 font-bold text-[11px]">
                          #{o.orderid}
                        </td>
                        <td
                          onClick={() => handleSelectSymbol(o.symbol)}
                          className="py-2 px-2 text-white font-bold cursor-pointer hover:text-terminal-amber transition-colors"
                          title="Click to load symbol into ticket"
                        >
                          {o.symbol}
                        </td>
                        <td className="py-2 px-2 text-center">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                              isBuy
                                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                                : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                            }`}
                          >
                            {o.action}
                          </span>
                        </td>
                        <td className="py-2 px-2 text-zinc-300 text-[11px]">
                          {o.pricetype || 'MKT'}
                        </td>
                        <td className="py-2 px-2 text-zinc-300 text-[11px]">
                          {o.product || 'MIS'}
                        </td>
                        <td className="py-2 px-2 text-right text-white font-bold tabular-nums">
                          {o.quantity}
                        </td>
                        <td className="py-2 px-2 text-right text-white font-bold tabular-nums">
                          ₹{(o.price ?? 0).toFixed(2)}
                        </td>
                        <td className="py-2 px-2.5 text-center">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                              isComplete
                                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                                : isPending
                                ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                                : isRejected
                                ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                                : 'bg-zinc-800 text-zinc-300 border-zinc-700'
                            }`}
                          >
                            {(o.order_status || 'UNKNOWN').toUpperCase()}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                  {displayedOrders.length === 0 && (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-zinc-400 font-mono text-xs">
                        No {orderFilter === 'ALL' ? '' : orderFilter.toLowerCase()} orders found in order book
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
