'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAtom, useAtomValue } from 'jotai';
import {
  tickDataAtom,
  openAlgoAvailableAtom,
  activeSymbolAtom,
} from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import type { PositionData } from '@/lib/openalgo';
import {
  fetchPaperTrades,
  createPaperTrade,
  addPaperTradeLeg,
  updatePaperTradeLeg,
  deletePaperTradeLeg,
  deletePaperTrade,
  type PaperTrade,
  type PaperTradeLeg,
} from '@/lib/paperTrades';

export function PosWidget() {
  const [tickData] = useAtom(tickDataAtom);
  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);
  const globalSymbol = useAtomValue(activeSymbolAtom);
  const queryClient = useQueryClient();

  // Mode: 'live' or 'paper'. If OpenAlgo is unavailable, force 'paper'.
  const [viewMode, setViewMode] = useState<'live' | 'paper'>('paper');
  const effectiveMode = openAlgoAvailable ? viewMode : 'paper';

  // --- Modals State ---
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [symbolInput, setSymbolInput] = useState('');
  const [buyPriceInput, setBuyPriceInput] = useState('');
  const [buyQtyInput, setBuyQtyInput] = useState('');
  const [notesInput, setNotesInput] = useState('');
  const [symbolSuggestions, setSymbolSuggestions] = useState<Array<{ symbol: string; companyName: string }>>([]);
  const [isSearchingSymbol, setIsSearchingSymbol] = useState(false);

  // Manage / Update modal state
  const [managingTrade, setManagingTrade] = useState<PaperTrade | null>(null);
  const [activeManageTab, setActiveManageTab] = useState<'add' | 'sell' | 'history'>('add');

  // Add more leg input
  const [addLegQty, setAddLegQty] = useState('');
  const [addLegPrice, setAddLegPrice] = useState('');
  const [addLegNotes, setAddLegNotes] = useState('');

  // Sell leg input
  const [sellLegQty, setSellLegQty] = useState('');
  const [sellLegPrice, setSellLegPrice] = useState('');
  const [sellLegNotes, setSellLegNotes] = useState('');

  // Editing specific leg inline
  const [editingLegId, setEditingLegId] = useState<number | null>(null);
  const [editLegQty, setEditLegQty] = useState('');
  const [editLegPrice, setEditLegPrice] = useState('');
  const [editLegNotes, setEditLegNotes] = useState('');

  // ─── Live OpenAlgo Positions Query ─────────────────────────────────────────
  const {
    data: posData,
    isLoading: isLiveLoading,
    isError: isLiveError,
    error: liveError,
  } = useQuery({
    queryKey: ['positionbook'],
    queryFn: () => OpenAlgoClient.getPositionBook(),
    refetchInterval: 10_000,
    staleTime: 9_000,
    retry: 1,
    enabled: effectiveMode === 'live',
  });

  // ─── Paper Trades Query ────────────────────────────────────────────────────
  const {
    data: paperTrades = [],
    isLoading: isPaperLoading,
    isError: isPaperError,
    error: paperError,
  } = useQuery({
    queryKey: ['paper-trades'],
    queryFn: fetchPaperTrades,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  // ─── Paper Trade Mutations ────────────────────────────────────────────────
  const createTradeMutation = useMutation({
    mutationFn: createPaperTrade,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      setIsAddOpen(false);
      setSymbolInput('');
      setBuyPriceInput('');
      setBuyQtyInput('');
      setNotesInput('');
    },
  });

  const addLegMutation = useMutation({
    mutationFn: ({ tradeId, payload }: { tradeId: number; payload: { action: 'BUY' | 'SELL'; quantity: number; price: number; notes?: string } }) =>
      addPaperTradeLeg(tradeId, payload),
    onSuccess: (updatedTrade) => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      setManagingTrade(updatedTrade);
      setAddLegQty('');
      setAddLegPrice('');
      setAddLegNotes('');
      setSellLegQty('');
      setSellLegPrice('');
      setSellLegNotes('');
    },
  });

  const updateLegMutation = useMutation({
    mutationFn: ({ legId, payload }: { legId: number; payload: { quantity?: number; price?: number; notes?: string } }) =>
      updatePaperTradeLeg(legId, payload),
    onSuccess: (updatedTrade) => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      setManagingTrade(updatedTrade);
      setEditingLegId(null);
    },
  });

  const deleteLegMutation = useMutation({
    mutationFn: (legId: number) => deletePaperTradeLeg(legId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      // If position was deleted or updated, refresh managing trade
      setManagingTrade(null);
      setEditingLegId(null);
    },
  });

  const deleteTradeMutation = useMutation({
    mutationFn: (tradeId: number) => deletePaperTrade(tradeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      setManagingTrade(null);
    },
  });

  // ─── Autocomplete Search ──────────────────────────────────────────────────
  const handleSymbolSearch = async (val: string) => {
    setSymbolInput(val);
    const trimmed = val.trim();
    if (trimmed.length < 1) {
      setSymbolSuggestions([]);
      return;
    }
    setIsSearchingSymbol(true);
    try {
      const res = await fetch(`/api/py/stockuniverse/search/${encodeURIComponent(trimmed)}`);
      if (res.ok) {
        const data: unknown = await res.json();
        if (Array.isArray(data)) {
          const mapped = data
            .slice(0, 8)
            .map((item: Record<string, unknown>) => ({
              symbol: String(item.symbol ?? ''),
              companyName: String(item.companyName ?? ''),
            }));
          setSymbolSuggestions(mapped);
        }
      }
    } catch {
      setSymbolSuggestions([]);
    } finally {
      setIsSearchingSymbol(false);
    }
  };

  const openNewTradeModal = () => {
    setSymbolInput(globalSymbol || 'RELIANCE');
    setBuyPriceInput('');
    setBuyQtyInput('');
    setNotesInput('');
    setSymbolSuggestions([]);
    setIsAddOpen(true);
  };

  const openManageModal = (trade: PaperTrade, tab: 'add' | 'sell' | 'history' = 'add') => {
    setManagingTrade(trade);
    setActiveManageTab(tab);
    setAddLegQty('');
    setAddLegPrice(trade.last_close ? String(trade.last_close) : String(trade.average_buy_price));
    setAddLegNotes('');
    setSellLegQty(trade.remaining_quantity > 0 ? String(trade.remaining_quantity) : '');
    setSellLegPrice(trade.last_close ? String(trade.last_close) : String(trade.average_buy_price));
    setSellLegNotes('');
    setEditingLegId(null);
  };

  // ─── Calculations ──────────────────────────────────────────────────────────
  const positions: PositionData[] = posData?.data ?? [];
  const openLivePositions = positions.filter((p) => Number(p.quantity) !== 0);
  const liveTotalPnl = openLivePositions.reduce((acc, p) => acc + parseFloat(p.pnl ?? '0'), 0);

  // Paper trades total PnL
  const paperTotalUnrealized = useMemo(() => {
    return paperTrades.reduce((acc, t) => {
      if (t.remaining_quantity <= 0) return acc;
      const tick = tickData[`${t.symbol}.NSE`]?.ltp ?? t.last_close ?? t.average_buy_price;
      const pnl = (tick - t.average_buy_price) * t.remaining_quantity;
      return acc + pnl;
    }, 0);
  }, [paperTrades, tickData]);

  const paperTotalRealized = useMemo(() => {
    return paperTrades.reduce((acc, t) => acc + (t.realized_pnl ?? 0), 0);
  }, [paperTrades]);

  const renderBadge = (state: string) => {
    switch (state) {
      case 'VOLATILE':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-amber-500/20 text-amber-400 border border-amber-500/30">
            VOLATILE
          </span>
        );
      case 'BUY':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
            BUY TREND
          </span>
        );
      case 'SELL':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-rose-500/20 text-rose-400 border border-rose-500/30">
            SELL TREND
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-blue-500/20 text-blue-300 border border-blue-500/30">
            HOLD
          </span>
        );
    }
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-black select-none">
      {/* Header bar with optional Live/Paper toggle and action button */}
      <div className="flex items-center justify-between px-2 py-1.5 bg-[#0e1117] border-b border-[#222733] flex-shrink-0">
        <div className="flex items-center gap-2">
          {/* Conditional Toggle only if OpenAlgo is configured & available */}
          {openAlgoAvailable && (
            <div className="flex rounded bg-[#161b26] p-0.5 border border-[#2a3142]">
              <button
                type="button"
                onClick={() => setViewMode('live')}
                className={`px-2 py-0.5 text-[10px] font-semibold rounded transition-colors ${
                  effectiveMode === 'live'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                LIVE
              </button>
              <button
                type="button"
                onClick={() => setViewMode('paper')}
                className={`px-2 py-0.5 text-[10px] font-semibold rounded transition-colors ${
                  effectiveMode === 'paper'
                    ? 'bg-amber-600 text-white shadow'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                PAPER
              </button>
            </div>
          )}

          <div className="text-[11px] font-bold tracking-wide text-zinc-300">
            {effectiveMode === 'live' ? 'OPENALGO POSITIONS' : 'PAPER TRADES TRACKER'}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Total PnL indicator */}
          {effectiveMode === 'live' ? (
            <div className="flex items-center gap-1.5 text-[11px]">
              <span className="text-zinc-400 text-[10px]">TOTAL P&amp;L:</span>
              <span
                className={`font-bold ${
                  liveTotalPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                }`}
              >
                {liveTotalPnl >= 0 ? '+' : ''}
                {liveTotalPnl.toFixed(2)}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-3 text-[11px]">
              <div className="flex items-center gap-1">
                <span className="text-zinc-500 text-[9px]">REALIZED:</span>
                <span
                  className={`font-medium ${
                    paperTotalRealized >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                  }`}
                >
                  {paperTotalRealized >= 0 ? '+' : ''}₹{paperTotalRealized.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-zinc-400 text-[10px]">UNREALIZED:</span>
                <span
                  className={`font-bold ${
                    paperTotalUnrealized >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                  }`}
                >
                  {paperTotalUnrealized >= 0 ? '+' : ''}₹{paperTotalUnrealized.toFixed(2)}
                </span>
              </div>
            </div>
          )}

          {effectiveMode === 'paper' && (
            <button
              type="button"
              onClick={openNewTradeModal}
              className="px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 transition-colors shadow"
            >
              <span>+</span>
              <span>New Trade</span>
            </button>
          )}
        </div>
      </div>

      {/* ─── LIVE MODE CONTENT ───────────────────────────────────────────────── */}
      {effectiveMode === 'live' && (
        <div className="flex-1 overflow-auto">
          {isLiveLoading ? (
            <div className="h-full w-full flex items-center justify-center font-mono text-xs text-white">
              LOADING POSITIONS...
            </div>
          ) : isLiveError ? (
            <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2">
              <span className="text-terminal-red">POSITIONS UNAVAILABLE</span>
              <span className="text-white/70 text-[10px]">
                {liveError instanceof Error ? liveError.message : 'Unknown error'}
              </span>
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead className="bg-[#121620] text-zinc-300 text-[10px] sticky top-0 uppercase tracking-wider border-b border-[#222733]">
                <tr>
                  <th className="p-1.5 border-r border-[#222733]">SYMBOL</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">QTY</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">AVG</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">LTP</th>
                  <th className="p-1.5 text-right">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {openLivePositions.map((row, i) => {
                  const pnl = parseFloat(row.pnl ?? '0');
                  const isPos = pnl >= 0;
                  const colorClass = isPos ? 'text-terminal-green' : 'text-terminal-red';
                  const qty = Number(row.quantity);

                  const tickKey = `${row.symbol}.${row.exchange}`;
                  const liveLtp = tickData[tickKey]?.ltp;
                  const ltpDisplay = liveLtp != null ? liveLtp.toFixed(2) : row.ltp ?? '—';

                  return (
                    <tr
                      key={i}
                      className="border-b border-[#1c2230] hover:bg-[#141924] transition-colors"
                    >
                      <td className="p-1.5 border-r border-[#1c2230] text-amber-400 font-bold">
                        <span>{row.symbol}</span>
                        <span className="text-zinc-500 text-[9px] ml-1.5 font-normal">
                          {row.product}
                        </span>
                      </td>
                      <td
                        className={`p-1.5 text-right border-r border-[#1c2230] font-medium ${
                          qty >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                        }`}
                      >
                        {qty}
                      </td>
                      <td className="p-1.5 text-right border-r border-[#1c2230] text-zinc-300">
                        {parseFloat(row.average_price).toFixed(2)}
                      </td>
                      <td className="p-1.5 text-right border-r border-[#1c2230] text-amber-300">
                        {ltpDisplay}
                      </td>
                      <td className={`p-1.5 text-right font-bold ${colorClass}`}>
                        {isPos ? '+' : ''}
                        {pnl.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
                {openLivePositions.length === 0 && (
                  <tr>
                    <td colSpan={5} className="p-8 text-zinc-500 text-center">
                      No open positions in OpenAlgo
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ─── PAPER TRADES CONTENT ────────────────────────────────────────────── */}
      {effectiveMode === 'paper' && (
        <div className="flex-1 overflow-auto">
          {isPaperLoading ? (
            <div className="h-full w-full flex items-center justify-center font-mono text-xs text-zinc-400">
              LOADING PAPER TRADES...
            </div>
          ) : isPaperError ? (
            <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2">
              <span className="text-terminal-red">FAILED TO LOAD PAPER TRADES</span>
              <span className="text-zinc-400 text-[10px]">
                {paperError instanceof Error ? paperError.message : 'Unknown error'}
              </span>
            </div>
          ) : paperTrades.length === 0 ? (
            <div className="h-full w-full flex flex-col items-center justify-center font-mono gap-3 p-4 text-center">
              <div className="text-zinc-400 text-xs">No paper trades active</div>
              <div className="text-zinc-500 text-[11px] max-w-sm">
                Create simulated dummy positions to practice risk management, track buy/sell legs,
                and analyze technical states without OpenAlgo broker setup.
              </div>
              <button
                type="button"
                onClick={openNewTradeModal}
                className="mt-2 px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-bold uppercase tracking-wider"
              >
                + Create First Paper Trade
              </button>
            </div>
          ) : (
            <table className="w-full text-left border-collapse">
              <thead className="bg-[#121620] text-zinc-400 text-[10px] sticky top-0 uppercase tracking-wider border-b border-[#222733]">
                <tr>
                  <th className="p-1.5 border-r border-[#222733]">STOCK / STATE</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">QTY</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">AVG BUY</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">LTP</th>
                  <th className="p-1.5 border-r border-[#222733] text-right">P&amp;L (% / ₹)</th>
                  <th className="p-1.5 text-center">ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {paperTrades.map((trade) => {
                  const isClosed = trade.remaining_quantity <= 0;
                  const tickKey = `${trade.symbol}.NSE`;
                  const ltp = tickData[tickKey]?.ltp ?? trade.last_close ?? trade.average_buy_price;

                  // Unrealized P&L
                  const diff = ltp - trade.average_buy_price;
                  const pnlAmount = isClosed ? trade.realized_pnl : diff * trade.remaining_quantity;
                  const pnlPct =
                    trade.average_buy_price > 0
                      ? (diff / trade.average_buy_price) * 100
                      : 0;
                  const isPos = pnlAmount >= 0;
                  const pnlColor = isPos ? 'text-terminal-green' : 'text-terminal-red';

                  return (
                    <tr
                      key={trade.id}
                      className={`border-b border-[#1c2230] hover:bg-[#141924] transition-colors ${
                        isClosed ? 'opacity-60 bg-black/40' : ''
                      }`}
                    >
                      {/* Symbol, PE badge, Technical State */}
                      <td className="p-1.5 border-r border-[#1c2230]">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-amber-400 font-bold text-xs">{trade.symbol}</span>
                            {renderBadge(trade.technical_state)}
                            {trade.pe != null && (
                              <span className="px-1 py-0.2 rounded text-[9px] font-mono bg-zinc-800 text-zinc-300 border border-zinc-700">
                                P/E: {trade.pe.toFixed(1)}
                              </span>
                            )}
                            {isClosed && (
                              <span className="px-1 py-0.2 rounded text-[9px] font-bold bg-zinc-800 text-zinc-400 border border-zinc-700">
                                CLOSED
                              </span>
                            )}
                          </div>
                          {trade.company_name && (
                            <span className="text-zinc-500 text-[9px] truncate max-w-[180px]">
                              {trade.company_name}
                            </span>
                          )}
                          {trade.legs.length > 1 && (
                            <span className="text-blue-400/80 text-[8px]">
                              {trade.legs.length} order legs (averaged)
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Quantity */}
                      <td className="p-1.5 text-right border-r border-[#1c2230]">
                        <div className="font-bold text-zinc-200">
                          {trade.remaining_quantity}
                        </div>
                        {trade.total_sold_quantity > 0 && (
                          <div className="text-zinc-500 text-[9px]">
                            sold {trade.total_sold_quantity} of {trade.total_buy_quantity}
                          </div>
                        )}
                      </td>

                      {/* Avg Buy */}
                      <td className="p-1.5 text-right border-r border-[#1c2230] text-zinc-300">
                        ₹{trade.average_buy_price.toFixed(2)}
                      </td>

                      {/* LTP */}
                      <td className="p-1.5 text-right border-r border-[#1c2230] text-amber-300 font-semibold">
                        ₹{ltp.toFixed(2)}
                      </td>

                      {/* P&L */}
                      <td className={`p-1.5 text-right border-r border-[#1c2230] font-bold ${pnlColor}`}>
                        <div className="flex flex-col items-end">
                          <span>
                            {isPos ? '+' : ''}₹{pnlAmount.toFixed(2)}
                          </span>
                          {!isClosed && (
                            <span className="text-[10px] font-medium opacity-90">
                              ({isPos ? '+' : ''}{pnlPct.toFixed(2)}%)
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Action buttons */}
                      <td className="p-1.5 text-center">
                        <div className="flex items-center justify-center gap-1">
                          <button
                            type="button"
                            onClick={() => openManageModal(trade, 'add')}
                            className="px-2 py-0.5 text-[9px] font-bold bg-blue-900/60 hover:bg-blue-700 text-blue-200 rounded border border-blue-700/50 uppercase"
                            title="Update / Add to Order"
                          >
                            Update
                          </button>
                          {!isClosed && (
                            <button
                              type="button"
                              onClick={() => openManageModal(trade, 'sell')}
                              className="px-2 py-0.5 text-[9px] font-bold bg-rose-950/60 hover:bg-rose-800 text-rose-200 rounded border border-rose-700/50 uppercase"
                              title="Sell position"
                            >
                              Sell
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ─── CREATE NEW PAPER TRADE MODAL ────────────────────────────────────── */}
      {isAddOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#11151f] border border-[#2d3748] rounded shadow-2xl w-full max-w-md p-4 text-xs font-mono flex flex-col gap-3 animate-in fade-in zoom-in-95 duration-100">
            <div className="flex items-center justify-between pb-2 border-b border-[#222733]">
              <span className="font-bold text-amber-400 text-sm">NEW PAPER TRADE</span>
              <button
                type="button"
                onClick={() => setIsAddOpen(false)}
                className="text-zinc-500 hover:text-white text-base leading-none"
              >
                ✕
              </button>
            </div>

            <div className="flex flex-col gap-3">
              {/* Symbol Input with Autocomplete */}
              <div className="relative">
                <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                  Stock Symbol
                </label>
                <input
                  type="text"
                  value={symbolInput}
                  onChange={(e) => handleSymbolSearch(e.target.value)}
                  placeholder="e.g. RELIANCE, TATAMOTORS..."
                  className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500 font-bold uppercase"
                />
                {isSearchingSymbol && (
                  <span className="absolute right-2.5 top-7 text-[9px] text-zinc-500">
                    searching...
                  </span>
                )}
                {symbolSuggestions.length > 0 && (
                  <div className="absolute left-0 right-0 top-full mt-1 bg-[#1a2130] border border-[#2d3748] rounded shadow-xl max-h-40 overflow-auto z-10">
                    {symbolSuggestions.map((item) => (
                      <button
                        type="button"
                        key={item.symbol}
                        onClick={() => {
                          setSymbolInput(item.symbol);
                          setSymbolSuggestions([]);
                        }}
                        className="w-full text-left px-2.5 py-1.5 hover:bg-blue-900/40 border-b border-[#242c3d] flex justify-between items-center text-[11px]"
                      >
                        <span className="font-bold text-amber-400">{item.symbol}</span>
                        <span className="text-zinc-400 text-[10px] truncate max-w-[200px]">
                          {item.companyName}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Price & Quantity Grid */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                    Buy Price (₹)
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={buyPriceInput}
                    onChange={(e) => setBuyPriceInput(e.target.value)}
                    placeholder="0.00"
                    className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                    Quantity
                  </label>
                  <input
                    type="number"
                    min="1"
                    value={buyQtyInput}
                    onChange={(e) => setBuyQtyInput(e.target.value)}
                    placeholder="10"
                    className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                  Strategy / Trade Notes (Optional)
                </label>
                <textarea
                  value={notesInput}
                  onChange={(e) => setNotesInput(e.target.value)}
                  placeholder="e.g. 200 EMA pullback entry with 2% target"
                  rows={2}
                  className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500 text-[11px] resize-none"
                />
              </div>

              {createTradeMutation.isError && (
                <div className="p-2 rounded bg-rose-950/50 border border-rose-800 text-rose-300 text-[11px]">
                  {createTradeMutation.error instanceof Error
                    ? createTradeMutation.error.message
                    : 'Failed to create trade'}
                </div>
              )}

              {/* Submit buttons */}
              <div className="flex justify-end gap-2 pt-2 border-t border-[#222733]">
                <button
                  type="button"
                  onClick={() => setIsAddOpen(false)}
                  className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={
                    !symbolInput.trim() ||
                    !buyPriceInput ||
                    !buyQtyInput ||
                    createTradeMutation.isPending
                  }
                  onClick={() => {
                    createTradeMutation.mutate({
                      symbol: symbolInput.trim().toUpperCase(),
                      price: parseFloat(buyPriceInput),
                      quantity: parseInt(buyQtyInput, 10),
                      notes: notesInput.trim() || undefined,
                    });
                  }}
                  className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-bold uppercase tracking-wider shadow"
                >
                  {createTradeMutation.isPending ? 'Creating...' : 'Open Position'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── UPDATE / MANAGE TRADE MODAL ─────────────────────────────────────── */}
      {managingTrade && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#11151f] border border-[#2d3748] rounded shadow-2xl w-full max-w-lg p-4 text-xs font-mono flex flex-col gap-3 animate-in fade-in zoom-in-95 duration-100">
            {/* Header */}
            <div className="flex items-center justify-between pb-2 border-b border-[#222733]">
              <div className="flex items-center gap-2">
                <span className="font-bold text-amber-400 text-sm">{managingTrade.symbol}</span>
                <span className="text-zinc-500">|</span>
                <span className="text-zinc-300 text-[11px]">
                  Avg: ₹{managingTrade.average_buy_price.toFixed(2)}
                </span>
                <span className="text-zinc-500">|</span>
                <span className="text-zinc-300 text-[11px]">
                  Qty: {managingTrade.remaining_quantity}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setManagingTrade(null)}
                className="text-zinc-500 hover:text-white text-base leading-none"
              >
                ✕
              </button>
            </div>

            {/* Navigation tabs inside modal */}
            <div className="flex border-b border-[#222733] gap-1">
              <button
                type="button"
                onClick={() => setActiveManageTab('add')}
                className={`px-3 py-1.5 text-[11px] font-bold uppercase border-b-2 transition-colors ${
                  activeManageTab === 'add'
                    ? 'border-blue-500 text-blue-400'
                    : 'border-transparent text-zinc-400 hover:text-white'
                }`}
              >
                Add to Position
              </button>
              <button
                type="button"
                onClick={() => setActiveManageTab('sell')}
                className={`px-3 py-1.5 text-[11px] font-bold uppercase border-b-2 transition-colors ${
                  activeManageTab === 'sell'
                    ? 'border-rose-500 text-rose-400'
                    : 'border-transparent text-zinc-400 hover:text-white'
                }`}
              >
                Sell / Close
              </button>
              <button
                type="button"
                onClick={() => setActiveManageTab('history')}
                className={`px-3 py-1.5 text-[11px] font-bold uppercase border-b-2 transition-colors ${
                  activeManageTab === 'history'
                    ? 'border-amber-500 text-amber-400'
                    : 'border-transparent text-zinc-400 hover:text-white'
                }`}
              >
                Orders &amp; Edit Base ({managingTrade.legs.length})
              </button>
            </div>

            {/* TAB 1: ADD TO POSITION (Averages up/down) */}
            {activeManageTab === 'add' && (
              <div className="flex flex-col gap-3 py-1">
                <div className="p-2 rounded bg-blue-950/30 border border-blue-900/50 text-blue-300 text-[11px] leading-relaxed">
                  Adding to this order will purchase more shares and calculate the new average buy
                  price automatically.
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                      Purchase Price (₹)
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={addLegPrice}
                      onChange={(e) => setAddLegPrice(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                      Additional Quantity
                    </label>
                    <input
                      type="number"
                      min="1"
                      value={addLegQty}
                      onChange={(e) => setAddLegQty(e.target.value)}
                      placeholder="10"
                      className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                    Notes
                  </label>
                  <input
                    type="text"
                    value={addLegNotes}
                    onChange={(e) => setAddLegNotes(e.target.value)}
                    placeholder="e.g. Pyramid buy on breakout"
                    className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-blue-500 text-[11px]"
                  />
                </div>

                {addLegMutation.isError && (
                  <div className="p-2 rounded bg-rose-950/50 border border-rose-800 text-rose-300 text-[11px]">
                    {addLegMutation.error instanceof Error
                      ? addLegMutation.error.message
                      : 'Failed to add leg'}
                  </div>
                )}

                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    disabled={!addLegPrice || !addLegQty || addLegMutation.isPending}
                    onClick={() => {
                      addLegMutation.mutate({
                        tradeId: managingTrade.id,
                        payload: {
                          action: 'BUY',
                          price: parseFloat(addLegPrice),
                          quantity: parseInt(addLegQty, 10),
                          notes: addLegNotes.trim() || undefined,
                        },
                      });
                    }}
                    className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-bold uppercase tracking-wider shadow"
                  >
                    {addLegMutation.isPending ? 'Adding...' : 'Add to Position'}
                  </button>
                </div>
              </div>
            )}

            {/* TAB 2: SELL / CLOSE */}
            {activeManageTab === 'sell' && (
              <div className="flex flex-col gap-3 py-1">
                <div className="p-2 rounded bg-rose-950/30 border border-rose-900/50 text-rose-300 text-[11px] leading-relaxed">
                  Enter the quantity sold and price to realize profit/loss. Selling all remaining{' '}
                  <span className="font-bold text-white">{managingTrade.remaining_quantity}</span>{' '}
                  shares will mark this position as CLOSED.
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                      Sold Price (₹)
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={sellLegPrice}
                      onChange={(e) => setSellLegPrice(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-rose-500"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                      Quantity Sold (Max: {managingTrade.remaining_quantity})
                    </label>
                    <input
                      type="number"
                      min="1"
                      max={managingTrade.remaining_quantity}
                      value={sellLegQty}
                      onChange={(e) => setSellLegQty(e.target.value)}
                      placeholder={String(managingTrade.remaining_quantity)}
                      className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-rose-500"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-zinc-400 uppercase tracking-wider font-semibold block mb-1">
                    Notes
                  </label>
                  <input
                    type="text"
                    value={sellLegNotes}
                    onChange={(e) => setSellLegNotes(e.target.value)}
                    placeholder="e.g. Target reached / stop loss triggered"
                    className="w-full bg-[#181f2e] border border-[#2d3748] rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-rose-500 text-[11px]"
                  />
                </div>

                {addLegMutation.isError && (
                  <div className="p-2 rounded bg-rose-950/50 border border-rose-800 text-rose-300 text-[11px]">
                    {addLegMutation.error instanceof Error
                      ? addLegMutation.error.message
                      : 'Failed to sell leg'}
                  </div>
                )}

                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    disabled={
                      !sellLegPrice ||
                      !sellLegQty ||
                      parseInt(sellLegQty, 10) > managingTrade.remaining_quantity ||
                      addLegMutation.isPending
                    }
                    onClick={() => {
                      addLegMutation.mutate({
                        tradeId: managingTrade.id,
                        payload: {
                          action: 'SELL',
                          price: parseFloat(sellLegPrice),
                          quantity: parseInt(sellLegQty, 10),
                          notes: sellLegNotes.trim() || undefined,
                        },
                      });
                    }}
                    className="px-4 py-1.5 rounded bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white font-bold uppercase tracking-wider shadow"
                  >
                    {addLegMutation.isPending ? 'Executing...' : 'Confirm Sell'}
                  </button>
                </div>
              </div>
            )}

            {/* TAB 3: ORDER HISTORY & EDIT ORIGINAL / ADDITIONS */}
            {activeManageTab === 'history' && (
              <div className="flex flex-col gap-2 max-h-64 overflow-auto">
                <div className="text-[10px] text-zinc-400">
                  You can edit the quantity/price of the base trade or any addition. The average
                  price is recalculated immediately.
                </div>
                <table className="w-full text-left border-collapse text-[11px]">
                  <thead className="bg-[#181f2e] text-zinc-400 text-[9px] uppercase border-b border-[#2d3748]">
                    <tr>
                      <th className="p-1">Action</th>
                      <th className="p-1 text-right">Qty</th>
                      <th className="p-1 text-right">Price</th>
                      <th className="p-1">Notes</th>
                      <th className="p-1 text-center">Edit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {managingTrade.legs.map((leg, idx) => {
                      const isEditing = editingLegId === leg.id;
                      const isBuy = leg.action.toUpperCase() === 'BUY';
                      return (
                        <tr
                          key={leg.id}
                          className="border-b border-[#1c2230] hover:bg-[#151a24]"
                        >
                          <td className="p-1">
                            <span
                              className={`font-bold text-[9px] px-1 py-0.5 rounded ${
                                isBuy
                                  ? 'bg-blue-900/40 text-blue-300'
                                  : 'bg-rose-900/40 text-rose-300'
                              }`}
                            >
                              {idx === 0 ? 'BASE BUY' : leg.action}
                            </span>
                          </td>
                          <td className="p-1 text-right">
                            {isEditing ? (
                              <input
                                type="number"
                                min="1"
                                value={editLegQty}
                                onChange={(e) => setEditLegQty(e.target.value)}
                                className="w-14 bg-black border border-blue-500 px-1 py-0.5 text-right text-white"
                              />
                            ) : (
                              leg.quantity
                            )}
                          </td>
                          <td className="p-1 text-right">
                            {isEditing ? (
                              <input
                                type="number"
                                step="any"
                                value={editLegPrice}
                                onChange={(e) => setEditLegPrice(e.target.value)}
                                className="w-16 bg-black border border-blue-500 px-1 py-0.5 text-right text-white"
                              />
                            ) : (
                              `₹${leg.price.toFixed(2)}`
                            )}
                          </td>
                          <td className="p-1 text-zinc-400 text-[10px] truncate max-w-[120px]">
                            {isEditing ? (
                              <input
                                type="text"
                                value={editLegNotes}
                                onChange={(e) => setEditLegNotes(e.target.value)}
                                className="w-full bg-black border border-blue-500 px-1 py-0.5 text-white"
                              />
                            ) : (
                              leg.notes || '—'
                            )}
                          </td>
                          <td className="p-1 text-center">
                            {isEditing ? (
                              <div className="flex items-center justify-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => {
                                    updateLegMutation.mutate({
                                      legId: leg.id,
                                      payload: {
                                        quantity: parseInt(editLegQty, 10),
                                        price: parseFloat(editLegPrice),
                                        notes: editLegNotes,
                                      },
                                    });
                                  }}
                                  className="px-1.5 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white text-[9px] rounded font-bold"
                                >
                                  Save
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setEditingLegId(null)}
                                  className="px-1.5 py-0.5 bg-zinc-700 text-zinc-300 text-[9px] rounded"
                                >
                                  ✕
                                </button>
                              </div>
                            ) : (
                              <div className="flex items-center justify-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setEditingLegId(leg.id);
                                    setEditLegQty(String(leg.quantity));
                                    setEditLegPrice(String(leg.price));
                                    setEditLegNotes(leg.notes || '');
                                  }}
                                  className="px-1.5 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-blue-300 text-[9px] rounded font-semibold"
                                >
                                  Edit
                                </button>
                                {managingTrade.legs.length > 1 && (
                                  <button
                                    type="button"
                                    onClick={() => deleteLegMutation.mutate(leg.id)}
                                    className="px-1.5 py-0.5 bg-rose-950 hover:bg-rose-800 text-rose-300 text-[9px] rounded"
                                    title="Delete this leg"
                                  >
                                    ✕
                                  </button>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                {/* Option to wipe whole trade */}
                <div className="pt-2 border-t border-[#222733] flex justify-between items-center">
                  <span className="text-[10px] text-zinc-500">Need to remove completely?</span>
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm(`Permanently delete paper trade for ${managingTrade.symbol}?`)) {
                        deleteTradeMutation.mutate(managingTrade.id);
                      }
                    }}
                    className="px-2 py-0.5 bg-red-950/60 hover:bg-red-800 text-red-300 text-[9px] rounded border border-red-800/40 uppercase font-semibold"
                  >
                    Delete Entire Trade
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
