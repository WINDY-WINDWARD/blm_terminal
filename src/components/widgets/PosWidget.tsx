'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAtom, useAtomValue } from 'jotai';
import {
  tickDataAtom,
  openAlgoAvailableAtom,
  activeSymbolAtom,
  fundsAtom,
} from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import type { PositionData, PlaceOrderParams } from '@/lib/openalgo';
import {
  fetchPaperTrades,
  createPaperTrade,
  addPaperTradeLeg,
  updatePaperTradeLeg,
  deletePaperTradeLeg,
  deletePaperTrade,
  type PaperTrade,
} from '@/lib/paperTrades';

export interface PosWidgetProps {
  panelId?: string;
}

export function PosWidget({ panelId: _panelId }: PosWidgetProps = {}) {
  const [tickData] = useAtom(tickDataAtom);
  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);
  const globalSymbol = useAtomValue(activeSymbolAtom);
  const funds = useAtomValue(fundsAtom);
  const queryClient = useQueryClient();

  // Mode: 'live' or 'paper'. If OpenAlgo is unavailable, force 'paper'.
  const [viewMode, setViewMode] = useState<'live' | 'paper'>('paper');
  const effectiveMode = openAlgoAvailable ? viewMode : 'paper';

  // Sub-tab for Paper Trades: 'open' or 'closed'
  const [paperTab, setPaperTab] = useState<'open' | 'closed'>('open');

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

  // Live square off confirm modal state
  const [confirmSquareOffPosition, setConfirmSquareOffPosition] = useState<PositionData | null>(null);
  const [isSquaringOff, setIsSquaringOff] = useState(false);
  const [squareOffStatus, setSquareOffStatus] = useState<string | null>(null);

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
    refetch: refetchLivePositions,
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
    refetch: _refetchPaperTrades,
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
    mutationFn: ({
      tradeId,
      payload,
    }: {
      tradeId: number;
      payload: { action: 'BUY' | 'SELL'; quantity: number; price: number; notes?: string };
    }) => addPaperTradeLeg(tradeId, payload),
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
    mutationFn: ({
      legId,
      payload,
    }: {
      legId: number;
      payload: { quantity?: number; price?: number; notes?: string };
    }) => updatePaperTradeLeg(legId, payload),
    onSuccess: (updatedTrade) => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      setManagingTrade(updatedTrade);
      setEditingLegId(null);
    },
  });

  const deleteLegMutation = useMutation({
    mutationFn: (legId: number) => deletePaperTradeLeg(legId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      if (!result || 'detail' in result || (result as PaperTrade).legs?.length === 0) {
        setManagingTrade(null);
      } else {
        setManagingTrade(result as PaperTrade);
      }
      setEditingLegId(null);
    },
  });

  const deleteTradeMutation = useMutation({
    mutationFn: (tradeId: number) => deletePaperTrade(tradeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['paper-trades'] });
      setManagingTrade(null);
      setEditingLegId(null);
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
          const mapped = data.slice(0, 8).map((item: Record<string, unknown>) => ({
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

  // ─── Live Square Off Action ───────────────────────────────────────────────
  const handleSquareOffLivePosition = async (pos: PositionData) => {
    setIsSquaringOff(true);
    setSquareOffStatus(`Routing square off for ${pos.symbol}...`);
    try {
      const qtyNum = Math.abs(Number(pos.quantity));
      const side = Number(pos.quantity) > 0 ? 'SELL' : 'BUY';
      const params: PlaceOrderParams = {
        symbol: pos.symbol,
        exchange: pos.exchange || 'NSE',
        action: side,
        quantity: String(qtyNum),
        price: '0',
        order_type: 'MARKET',
        product: (pos.product as 'MIS' | 'CNC' | 'NRML') || 'MIS',
      };
      const res = await OpenAlgoClient.placeOrder(params);
      setSquareOffStatus(`Square off placed: ${res.message || 'Complete'}`);
      void queryClient.invalidateQueries({ queryKey: ['positionbook'] });
      void queryClient.invalidateQueries({ queryKey: ['orderbook'] });
      void queryClient.invalidateQueries({ queryKey: ['funds'] });
      setTimeout(() => {
        setConfirmSquareOffPosition(null);
        setSquareOffStatus(null);
      }, 1500);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to square off';
      setSquareOffStatus(`Error: ${msg}`);
    } finally {
      setIsSquaringOff(false);
    }
  };

  // ─── Calculations ──────────────────────────────────────────────────────────
  const positions: PositionData[] = posData?.data ?? [];
  const openLivePositions = positions.filter((p) => Number(p.quantity) !== 0);
  const liveTotalPnl = openLivePositions.reduce((acc, p) => acc + parseFloat(p.pnl ?? '0'), 0);
  const liveRealizedPnl = parseFloat(funds?.m2mrealized ?? '0') || 0;

  // Split paper trades into open and closed
  const openPaperTrades = useMemo(
    () => paperTrades.filter((t) => t.remaining_quantity > 0 && t.status !== 'CLOSED'),
    [paperTrades]
  );

  const closedPaperTrades = useMemo(
    () => paperTrades.filter((t) => t.remaining_quantity <= 0 || t.status === 'CLOSED'),
    [paperTrades]
  );

  const displayedPaperTrades = paperTab === 'open' ? openPaperTrades : closedPaperTrades;

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

  const paperTotalCombined = paperTotalRealized + paperTotalUnrealized;

  const renderBadge = (state: string) => {
    switch (state) {
      case 'VOLATILE':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/30">
            VOLATILE
          </span>
        );
      case 'BUY':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            BUY TREND
          </span>
        );
      case 'SELL':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-rose-500/10 text-rose-400 border border-rose-500/30">
            SELL TREND
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-[#18181f] text-zinc-300 border border-[#27272a]">
            HOLD
          </span>
        );
    }
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-[#09090b] text-white overflow-hidden select-none">
      {/* Top Deck Banner & Controls */}
      <div className="bg-[#0c0c0f] border-b border-[#27272a] px-3 py-2 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-2.5">
          <span className="text-terminal-amber font-mono font-bold text-xs tracking-wider">◈ BLM TERMINAL</span>
          <span className="text-zinc-600 font-mono text-xs">|</span>
          <span className="text-white font-mono font-bold text-xs tracking-wide">POSITIONS DECK</span>

          {/* Conditional Toggle between Live and Paper */}
          {openAlgoAvailable && (
            <div className="flex rounded bg-[#121216] p-0.5 border border-[#27272a] ml-1">
              <button
                type="button"
                onClick={() => setViewMode('live')}
                className={`px-2.5 py-0.5 text-[10px] font-bold rounded transition-all ${
                  effectiveMode === 'live'
                    ? 'bg-terminal-amber text-black shadow-sm'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                LIVE
              </button>
              <button
                type="button"
                onClick={() => setViewMode('paper')}
                className={`px-2.5 py-0.5 text-[10px] font-bold rounded transition-all ${
                  effectiveMode === 'paper'
                    ? 'bg-terminal-amber text-black shadow-sm'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                PAPER
              </button>
            </div>
          )}

          {/* Sub-tabs for Paper Trades (OPEN vs CLOSED) */}
          {effectiveMode === 'paper' && (
            <div className="flex rounded bg-[#121216] p-0.5 border border-[#27272a] ml-1">
              <button
                type="button"
                onClick={() => setPaperTab('open')}
                className={`px-2 py-0.5 text-[10px] font-bold rounded transition-all ${
                  paperTab === 'open'
                    ? 'bg-[#27272a] text-white'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                OPEN ({openPaperTrades.length})
              </button>
              <button
                type="button"
                onClick={() => setPaperTab('closed')}
                className={`px-2 py-0.5 text-[10px] font-bold rounded transition-all ${
                  paperTab === 'closed'
                    ? 'bg-[#27272a] text-white'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                CLOSED ({closedPaperTrades.length})
              </button>
            </div>
          )}
        </div>

        {/* Right Action Controls */}
        <div className="flex items-center gap-2">
          {effectiveMode === 'paper' ? (
            <button
              type="button"
              onClick={openNewTradeModal}
              className="px-2.5 py-1 rounded bg-[#121216] border border-terminal-amber/60 text-terminal-amber hover:bg-terminal-amber hover:text-black text-xs font-mono font-bold tracking-wider flex items-center gap-1 transition-all shadow-sm"
            >
              <span>+</span>
              <span>NEW POSITION</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void refetchLivePositions()}
              className="px-2.5 py-1 rounded bg-[#121216] border border-[#27272a] text-zinc-300 hover:border-terminal-amber hover:text-terminal-amber text-xs font-mono font-bold transition-all"
            >
              ↻ REFRESH
            </button>
          )}
        </div>
      </div>

      {/* Main Content Body */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">

        {/* ─── TOP KPI CARDS (Total P&L, Realized P&L, Unrealized P&L) ─────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* Card 1: Total P&L */}
          <div className="bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 shadow-md">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                {effectiveMode === 'live' ? 'TOTAL LIVE P&L' : 'TOTAL SIMULATED P&L'}
              </span>
              <span className="text-xs">
                {(effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined) >= 0 ? (
                  <span className="text-emerald-400">▲</span>
                ) : (
                  <span className="text-rose-400">▼</span>
                )}
              </span>
            </div>
            <div
              className={`text-lg sm:text-xl font-mono font-bold tabular-nums ${
                (effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined) >= 0
                  ? 'text-emerald-400'
                  : 'text-rose-400'
              }`}
            >
              {(effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined) >= 0 ? '+' : ''}
              ₹{(effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined).toLocaleString('en-IN', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
              {effectiveMode === 'live' ? 'Aggregate Net M2M' : 'Realized + Floating Combined'}
            </div>
          </div>

          {/* Card 2: Realized P&L */}
          <div className="bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 shadow-md">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                REALIZED P&L
              </span>
              <span className="text-blue-400 text-xs">●</span>
            </div>
            <div
              className={`text-lg sm:text-xl font-mono font-bold tabular-nums ${
                (effectiveMode === 'live' ? liveRealizedPnl : paperTotalRealized) >= 0
                  ? 'text-emerald-400'
                  : 'text-rose-400'
              }`}
            >
              {(effectiveMode === 'live' ? liveRealizedPnl : paperTotalRealized) >= 0 ? '+' : ''}
              ₹{(effectiveMode === 'live' ? liveRealizedPnl : paperTotalRealized).toLocaleString('en-IN', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
              {effectiveMode === 'live' ? 'Settled Day Closed Turnover' : 'Booked Across Closed Trades'}
            </div>
          </div>

          {/* Card 3: Unrealized P&L */}
          <div className="bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 shadow-md">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                UNREALIZED P&L
              </span>
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            </div>
            <div
              className={`text-lg sm:text-xl font-mono font-bold tabular-nums ${
                (effectiveMode === 'live' ? liveTotalPnl : paperTotalUnrealized) >= 0
                  ? 'text-emerald-400'
                  : 'text-rose-400'
              }`}
            >
              {(effectiveMode === 'live' ? liveTotalPnl : paperTotalUnrealized) >= 0 ? '+' : ''}
              ₹{(effectiveMode === 'live' ? liveTotalPnl : paperTotalUnrealized).toLocaleString('en-IN', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
              Floating Live Across {effectiveMode === 'live' ? openLivePositions.length : openPaperTrades.length} Active Positions
            </div>
          </div>
        </div>

        {/* ─── BENTO POSITIONS MATRIX TABLE CARD ──────────────────────────────── */}
        <div className="bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-700/60 transition-colors rounded-md p-3 shadow-md flex-1 flex flex-col overflow-hidden">
          {/* Card Table Header */}
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-[#27272a]">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                {effectiveMode === 'live'
                  ? `LIVE POSITIONS // CONTRACT MATRIX (${openLivePositions.length} ACTIVE)`
                  : `PAPER POSITIONS // ${paperTab.toUpperCase()} CONTRACTS (${displayedPaperTrades.length} ACTIVE)`}
              </span>
              <span
                className={`text-xs font-mono font-bold px-2 py-0.5 rounded border tabular-nums ${
                  (effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined) >= 0
                    ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
                    : 'text-rose-400 bg-rose-500/10 border-rose-500/30'
                }`}
              >
                NET: {(effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined) >= 0 ? '+' : ''}
                ₹{(effectiveMode === 'live' ? liveTotalPnl : paperTotalCombined).toFixed(2)}
              </span>
            </div>

            {effectiveMode === 'paper' && (
              <button
                type="button"
                onClick={openNewTradeModal}
                className="px-2 py-0.5 text-xs font-mono font-bold rounded bg-[#121216] border border-[#27272a] text-terminal-amber hover:border-terminal-amber transition-all"
              >
                + ADD POSITION
              </button>
            )}
          </div>

          {/* Table Container */}
          <div className="overflow-x-auto custom-scroll flex-1">
            {/* ─── LIVE OPENALGO POSITIONS TABLE ─────────────────────────────────── */}
            {effectiveMode === 'live' && (
              <>
                {isLiveLoading ? (
                  <div className="h-48 w-full flex items-center justify-center font-mono text-xs text-white">
                    LOADING POSITIONS...
                  </div>
                ) : isLiveError ? (
                  <div className="h-48 w-full flex flex-col items-center justify-center font-mono text-xs gap-2">
                    <span className="text-terminal-red">POSITIONS UNAVAILABLE</span>
                    <span className="text-white/70 text-[10px]">
                      {liveError instanceof Error ? liveError.message : 'Unknown error'}
                    </span>
                  </div>
                ) : (
                  <table className="w-full text-left font-mono text-xs border-collapse">
                    <thead>
                      <tr className="text-[10px] uppercase text-zinc-300 border-b border-[#27272a] bg-[#121216] sticky top-0 z-10">
                        <th className="py-2 px-2.5 font-bold">INSTRUMENT</th>
                        <th className="py-2 px-2 font-bold">PRODUCT</th>
                        <th className="py-2 px-2 text-right font-bold">NET QTY</th>
                        <th className="py-2 px-2 text-right font-bold">AVG BUY (₹)</th>
                        <th className="py-2 px-2 text-right font-bold">LTP (₹)</th>
                        <th className="py-2 px-2 text-right font-bold">CURRENT VALUE (₹)</th>
                        <th className="py-2 px-3 text-right font-bold">P&L</th>
                        <th className="py-2 px-2.5 text-center font-bold">ACTIONS</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#27272a]/60">
                      {openLivePositions.map((row, i) => {
                        const pnl = parseFloat(row.pnl ?? '0');
                        const isPos = pnl >= 0;
                        const qtyNum = Number(row.quantity);
                        const avgPrice = parseFloat(row.average_price) || 0;
                        const tickKey = `${row.symbol}.${row.exchange}`;
                        const liveLtp = tickData[tickKey]?.ltp ?? (parseFloat(row.ltp ?? '0') || avgPrice);
                        const currentValue = Math.abs(qtyNum) * liveLtp;

                        return (
                          <tr key={i} className="hover:bg-zinc-900/60 transition-colors">
                            <td className="py-2.5 px-2.5 font-bold text-white flex items-center gap-2">
                              <span
                                className={`w-1.5 h-1.5 rounded-full ${isPos ? 'bg-emerald-400' : 'bg-rose-400'}`}
                              />
                              <span>{row.symbol}</span>
                              <span className="text-[10px] text-zinc-400 font-normal">{row.exchange}</span>
                            </td>
                            <td className="py-2.5 px-2">
                              <span className="text-[10px] bg-[#14141a] text-zinc-200 px-1.5 py-0.5 rounded border border-[#27272a] font-bold">
                                {row.product}
                              </span>
                            </td>
                            <td
                              className={`py-2.5 px-2 text-right font-bold tabular-nums ${
                                qtyNum >= 0 ? 'text-emerald-400' : 'text-rose-400'
                              }`}
                            >
                              {qtyNum > 0 ? `+${qtyNum}` : qtyNum}
                            </td>
                            <td className="py-2.5 px-2 text-right text-zinc-200 tabular-nums">
                              ₹{avgPrice.toFixed(2)}
                            </td>
                            <td className="py-2.5 px-2 text-right font-bold text-white tabular-nums">
                              ₹{liveLtp.toFixed(2)}
                            </td>
                            <td className="py-2.5 px-2 text-right text-zinc-100 font-bold tabular-nums">
                              ₹{currentValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td className="py-2.5 px-3 text-right">
                              <span
                                className={`inline-block font-bold px-2 py-0.5 rounded text-xs tabular-nums border shadow-sm ${
                                  isPos
                                    ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.25)]'
                                    : 'bg-rose-500/10 border-rose-500/40 text-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.25)]'
                                }`}
                              >
                                {isPos ? '+' : ''}₹{pnl.toFixed(2)}
                              </span>
                            </td>
                            <td className="py-2.5 px-2.5 text-center">
                              <button
                                type="button"
                                onClick={() => setConfirmSquareOffPosition(row)}
                                className="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500/20 transition-all"
                              >
                                ✕ SQUARE OFF
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                      {openLivePositions.length === 0 && (
                        <tr>
                          <td colSpan={8} className="py-12 text-center text-zinc-400 font-mono text-xs">
                            No open positions in OpenAlgo gateway
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                )}
              </>
            )}

            {/* ─── PAPER TRADES TABLE ───────────────────────────────────────────── */}
            {effectiveMode === 'paper' && (
              <>
                {isPaperLoading ? (
                  <div className="h-48 w-full flex items-center justify-center font-mono text-xs text-zinc-400">
                    LOADING PAPER TRADES...
                  </div>
                ) : isPaperError ? (
                  <div className="h-48 w-full flex flex-col items-center justify-center font-mono text-xs gap-2">
                    <span className="text-terminal-red">FAILED TO LOAD PAPER TRADES</span>
                    <span className="text-zinc-400 text-[10px]">
                      {paperError instanceof Error ? paperError.message : 'Unknown error'}
                    </span>
                  </div>
                ) : displayedPaperTrades.length === 0 ? (
                  <div className="h-48 w-full flex flex-col items-center justify-center font-mono gap-3 p-4 text-center">
                    <div className="text-zinc-300 text-xs font-bold">
                      {paperTab === 'open' ? 'No open paper positions' : 'No closed paper positions'}
                    </div>
                    <div className="text-zinc-400 text-[11px] max-w-sm">
                      {paperTab === 'open'
                        ? 'Simulate risk management, multi-leg averaging, and monitor real-time WebSocket tick movements.'
                        : 'Positions that have been completely sold out will appear here with audited realized returns.'}
                    </div>
                    {paperTab === 'open' && (
                      <button
                        type="button"
                        onClick={openNewTradeModal}
                        className="mt-1 px-3 py-1 bg-terminal-amber text-black hover:bg-amber-400 rounded text-xs font-bold uppercase tracking-wider"
                      >
                        + Create First Paper Trade
                      </button>
                    )}
                  </div>
                ) : (
                  <table className="w-full text-left font-mono text-xs border-collapse">
                    <thead>
                      <tr className="text-[10px] uppercase text-zinc-300 border-b border-[#27272a] bg-[#121216] sticky top-0 z-10">
                        <th className="py-2 px-2.5 font-bold">INSTRUMENT / STATE</th>
                        <th className="py-2 px-2 text-right font-bold">NET QTY</th>
                        <th className="py-2 px-2 text-right font-bold">AVG BUY (₹)</th>
                        <th className="py-2 px-2 text-right font-bold">LTP (₹)</th>
                        <th className="py-2 px-2 text-right font-bold">CURRENT VALUE (₹)</th>
                        <th className="py-2 px-3 text-right font-bold">P&L (% / ₹)</th>
                        <th className="py-2 px-2.5 text-center font-bold">ACTIONS</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#27272a]/60">
                      {displayedPaperTrades.map((trade) => {
                        const isClosed = trade.remaining_quantity <= 0 || trade.status === 'CLOSED';
                        const tickKey = `${trade.symbol}.NSE`;
                        const ltp = tickData[tickKey]?.ltp ?? trade.last_close ?? trade.average_buy_price;

                        const diff = ltp - trade.average_buy_price;
                        const pnlAmount = isClosed ? trade.realized_pnl : diff * trade.remaining_quantity;
                        const pnlPct =
                          trade.average_buy_price > 0
                            ? (diff / trade.average_buy_price) * 100
                            : 0;
                        const isPos = pnlAmount >= 0;
                        const holdingValue = trade.remaining_quantity * ltp;

                        return (
                          <tr
                            key={trade.id}
                            className={`hover:bg-zinc-900/60 transition-colors ${
                              isClosed ? 'opacity-60 bg-black/40' : ''
                            }`}
                          >
                            {/* Instrument, Technical state, legs */}
                            <td className="py-2.5 px-2.5">
                              <div className="flex flex-col gap-0.5">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                  <span className="font-bold text-white text-xs">{trade.symbol}</span>
                                  {trade.pe != null && (
                                    <span className="text-zinc-400 text-[10px]">
                                      P/E: {trade.pe?.toFixed(1)}
                                    </span>
                                  )}
                                  {trade.technical_state && renderBadge(trade.technical_state)}
                                </div>
                                {trade.company_name && (
                                  <span className="text-zinc-400 text-[10px] truncate max-w-[180px]">
                                    {trade.company_name}
                                  </span>
                                )}
                                {trade.legs.length > 1 && (
                                  <span className="text-terminal-amber text-[9px] font-bold">
                                    {trade.legs.length} order legs (averaged)
                                  </span>
                                )}
                              </div>
                            </td>

                            {/* Net Qty */}
                            <td className="py-2.5 px-2 text-right">
                              <div className="font-bold text-white tabular-nums">
                                {trade.remaining_quantity > 0 ? `+${trade.remaining_quantity}` : trade.remaining_quantity}
                              </div>
                              {trade.total_sold_quantity > 0 && (
                                <div className="text-zinc-400 text-[9px]">
                                  sold {trade.total_sold_quantity} of {trade.total_buy_quantity}
                                </div>
                              )}
                            </td>

                            {/* Avg Buy */}
                            <td className="py-2.5 px-2 text-right text-zinc-200 tabular-nums">
                              ₹{trade.average_buy_price.toFixed(2)}
                            </td>

                            {/* LTP */}
                            <td className="py-2.5 px-2 text-right font-bold text-white tabular-nums">
                              ₹{ltp.toFixed(2)}
                            </td>

                            {/* Current Value */}
                            <td className="py-2.5 px-2 text-right text-zinc-100 font-bold tabular-nums">
                              ₹{holdingValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>

                            {/* P&L */}
                            <td className="py-2.5 px-3 text-right">
                              <span
                                className={`inline-block font-bold px-2 py-0.5 rounded text-xs tabular-nums border shadow-sm ${
                                  isPos
                                    ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.25)]'
                                    : 'bg-rose-500/10 border-rose-500/40 text-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.25)]'
                                }`}
                              >
                                {isPos ? '+' : ''}₹{pnlAmount.toFixed(2)}{' '}
                                {!isClosed && (
                                  <span className="text-[10px] opacity-90">
                                    ({isPos ? '+' : ''}{pnlPct.toFixed(2)}%)
                                  </span>
                                )}
                              </span>
                            </td>

                            {/* Actions */}
                            <td className="py-2.5 px-2.5 text-center">
                              <div className="inline-flex items-center gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => openManageModal(trade, 'add')}
                                  className="px-2 py-0.5 rounded text-[11px] font-bold bg-[#14141a] border border-[#27272a] text-terminal-amber hover:border-terminal-amber transition-all"
                                  title="Add leg / average position"
                                >
                                  + ADD LEG
                                </button>
                                {!isClosed && (
                                  <button
                                    type="button"
                                    onClick={() => openManageModal(trade, 'sell')}
                                    className="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500/20 transition-all"
                                    title="Sell / close position"
                                  >
                                    ✕ SQUARE OFF
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
              </>
            )}
          </div>
        </div>

      </div>

      {/* ─── MODAL 1: CREATE NEW PAPER TRADE / POSITION ──────────────────────── */}
      {isAddOpen && (
        <div className="fixed inset-0 bg-[#09090b]/85 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0c0c0f] border border-[#27272a] rounded-md shadow-2xl w-full max-w-md p-4 text-xs font-mono flex flex-col gap-3.5">
            <div className="flex items-center justify-between pb-2 border-b border-[#27272a]">
              <span className="font-bold text-terminal-amber text-xs uppercase tracking-wider">
                NEW POSITION // PAPER TRADE TICKET
              </span>
              <button
                type="button"
                onClick={() => setIsAddOpen(false)}
                className="text-zinc-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="flex flex-col gap-3">
              {/* Symbol Input with Autocomplete */}
              <div className="relative">
                <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                  STOCK SYMBOL
                </label>
                <input
                  type="text"
                  value={symbolInput}
                  onChange={(e) => handleSymbolSearch(e.target.value)}
                  placeholder="e.g. RELIANCE, TATAMOTORS..."
                  className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold uppercase outline-none focus:border-terminal-amber"
                />
                {isSearchingSymbol && (
                  <span className="absolute right-2.5 top-8 text-[9px] text-zinc-400">
                    searching...
                  </span>
                )}
                {symbolSuggestions.length > 0 && (
                  <div className="absolute left-0 right-0 top-full mt-1 bg-[#121216] border border-[#27272a] rounded shadow-xl max-h-40 overflow-auto z-20">
                    {symbolSuggestions.map((item) => (
                      <button
                        type="button"
                        key={item.symbol}
                        onClick={() => {
                          setSymbolInput(item.symbol);
                          setSymbolSuggestions([]);
                        }}
                        className="w-full text-left px-2.5 py-1.5 hover:bg-terminal-amber/10 border-b border-[#27272a] flex justify-between items-center text-[11px]"
                      >
                        <span className="font-bold text-terminal-amber">{item.symbol}</span>
                        <span className="text-zinc-300 text-[10px] truncate max-w-[200px]">
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
                  <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                    BUY PRICE (₹)
                  </label>
                  <input
                    type="number"
                    step="any"
                    value={buyPriceInput}
                    onChange={(e) => setBuyPriceInput(e.target.value)}
                    placeholder="0.00"
                    className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold tabular-nums outline-none focus:border-terminal-amber"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                    QUANTITY
                  </label>
                  <input
                    type="number"
                    min="1"
                    value={buyQtyInput}
                    onChange={(e) => setBuyQtyInput(e.target.value)}
                    placeholder="10"
                    className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold tabular-nums outline-none focus:border-terminal-amber"
                  />
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                  STRATEGY NOTES (OPTIONAL)
                </label>
                <input
                  type="text"
                  value={notesInput}
                  onChange={(e) => setNotesInput(e.target.value)}
                  placeholder="e.g. Swing entry on 200 EMA support"
                  className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono text-xs outline-none focus:border-terminal-amber"
                />
              </div>

              {createTradeMutation.isError && (
                <div className="p-2 rounded bg-rose-500/10 border border-rose-500/40 text-rose-400 text-[11px]">
                  {createTradeMutation.error instanceof Error
                    ? createTradeMutation.error.message
                    : 'Failed to create trade'}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-[#27272a]">
              <button
                type="button"
                onClick={() => setIsAddOpen(false)}
                className="px-3 py-1.5 rounded bg-[#121216] border border-[#27272a] text-zinc-300 hover:border-zinc-500"
              >
                CANCEL
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
                className="px-4 py-1.5 rounded bg-terminal-amber text-black hover:bg-amber-400 font-bold uppercase tracking-wider disabled:opacity-50"
              >
                {createTradeMutation.isPending ? 'CREATING...' : 'CONFIRM POSITION'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── MODAL 2: MANAGE TRADE LEG / UPDATE POSITION ─────────────────────── */}
      {managingTrade && (
        <div className="fixed inset-0 bg-[#09090b]/85 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0c0c0f] border border-[#27272a] rounded-md shadow-2xl w-full max-w-lg p-4 text-xs font-mono flex flex-col gap-3.5">
            <div className="flex items-center justify-between pb-2 border-b border-[#27272a]">
              <div className="flex items-center gap-2">
                <span className="font-bold text-terminal-amber text-xs uppercase tracking-wider">
                  MANAGE POSITION //
                </span>
                <span className="bg-[#121216] border border-[#27272a] text-white px-2 py-0.5 rounded font-bold">
                  {managingTrade.symbol}
                </span>
                <span className="text-[10px] text-zinc-400">
                  Avg: ₹{managingTrade.average_buy_price.toFixed(2)} • Net: {managingTrade.remaining_quantity}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setManagingTrade(null)}
                className="text-zinc-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {/* Navigation Tabs Inside Modal */}
            <div className="grid grid-cols-3 gap-1 p-0.5 bg-[#121216] border border-[#27272a] rounded">
              <button
                type="button"
                onClick={() => setActiveManageTab('add')}
                className={`py-1.5 text-[11px] font-bold uppercase rounded text-center transition-all ${
                  activeManageTab === 'add'
                    ? 'bg-emerald-600 text-white shadow-sm'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                + ADD LEG (AVG)
              </button>
              <button
                type="button"
                onClick={() => setActiveManageTab('sell')}
                className={`py-1.5 text-[11px] font-bold uppercase rounded text-center transition-all ${
                  activeManageTab === 'sell'
                    ? 'bg-rose-600 text-white shadow-sm'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                ✕ SELL / CLOSE
              </button>
              <button
                type="button"
                onClick={() => setActiveManageTab('history')}
                className={`py-1.5 text-[11px] font-bold uppercase rounded text-center transition-all ${
                  activeManageTab === 'history'
                    ? 'bg-terminal-amber text-black shadow-sm'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                ORDERS ({managingTrade.legs.length})
              </button>
            </div>

            {/* TAB 1: ADD TO POSITION */}
            {activeManageTab === 'add' && (
              <div className="flex flex-col gap-3 py-1">
                <div className="p-2 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[11px]">
                  Adding a buy leg acquires more shares and recalculates the weighted average price dynamically.
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                      PURCHASE PRICE (₹)
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={addLegPrice}
                      onChange={(e) => setAddLegPrice(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold tabular-nums outline-none focus:border-terminal-amber"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                      ADDITIONAL QUANTITY
                    </label>
                    <input
                      type="number"
                      min="1"
                      value={addLegQty}
                      onChange={(e) => setAddLegQty(e.target.value)}
                      placeholder="10"
                      className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold tabular-nums outline-none focus:border-terminal-amber"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                    EXECUTION STRATEGY NOTE
                  </label>
                  <input
                    type="text"
                    value={addLegNotes}
                    onChange={(e) => setAddLegNotes(e.target.value)}
                    placeholder="e.g. Pyramid buy on VWAP bounce"
                    className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono text-xs outline-none focus:border-terminal-amber"
                  />
                </div>

                {addLegMutation.isError && (
                  <div className="p-2 rounded bg-rose-500/10 border border-rose-500/40 text-rose-400 text-[11px]">
                    {addLegMutation.error instanceof Error
                      ? addLegMutation.error.message
                      : 'Failed to add leg'}
                  </div>
                )}

                <div className="flex justify-end pt-2 border-t border-[#27272a]">
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
                    className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-bold uppercase tracking-wider disabled:opacity-50"
                  >
                    {addLegMutation.isPending ? 'EXECUTING...' : 'CONFIRM ADD LEG'}
                  </button>
                </div>
              </div>
            )}

            {/* TAB 2: SELL / CLOSE POSITION */}
            {activeManageTab === 'sell' && (
              <div className="flex flex-col gap-3 py-1">
                <div className="p-2 rounded bg-rose-500/10 border border-rose-500/30 text-rose-300 text-[11px]">
                  Selling books realized profit/loss and decrements remaining holdings. Max available: {managingTrade.remaining_quantity}.
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                      SELL PRICE (₹)
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={sellLegPrice}
                      onChange={(e) => setSellLegPrice(e.target.value)}
                      placeholder="0.00"
                      className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold tabular-nums outline-none focus:border-terminal-amber"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                      QUANTITY TO SELL
                    </label>
                    <input
                      type="number"
                      min="1"
                      max={managingTrade.remaining_quantity}
                      value={sellLegQty}
                      onChange={(e) => setSellLegQty(e.target.value)}
                      placeholder={String(managingTrade.remaining_quantity)}
                      className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono font-bold tabular-nums outline-none focus:border-terminal-amber"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-zinc-300 uppercase tracking-wider font-bold block mb-1">
                    EXECUTION STRATEGY NOTE
                  </label>
                  <input
                    type="text"
                    value={sellLegNotes}
                    onChange={(e) => setSellLegNotes(e.target.value)}
                    placeholder="e.g. Target reached / Stop loss triggered"
                    className="w-full bg-[#09090b] border border-[#27272a] rounded p-2 text-white font-mono text-xs outline-none focus:border-terminal-amber"
                  />
                </div>

                {addLegMutation.isError && (
                  <div className="p-2 rounded bg-rose-500/10 border border-rose-500/40 text-rose-400 text-[11px]">
                    {addLegMutation.error instanceof Error
                      ? addLegMutation.error.message
                      : 'Failed to sell leg'}
                  </div>
                )}

                <div className="flex justify-end pt-2 border-t border-[#27272a]">
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
                    className="px-4 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white font-bold uppercase tracking-wider disabled:opacity-50"
                  >
                    {addLegMutation.isPending ? 'EXECUTING...' : 'CONFIRM SELL LEG'}
                  </button>
                </div>
              </div>
            )}

            {/* TAB 3: AUDIT & EDIT HISTORY */}
            {activeManageTab === 'history' && (
              <div className="flex flex-col gap-2 max-h-64 overflow-auto">
                <div className="text-[10px] text-zinc-400">
                  Audited order legs for {managingTrade.symbol}. Modifying leg parameters recalculates the position average immediately.
                </div>
                <table className="w-full text-left border-collapse text-[11px]">
                  <thead className="bg-[#121216] text-zinc-300 text-[9px] uppercase border-b border-[#27272a]">
                    <tr>
                      <th className="p-1.5 font-bold">ACTION</th>
                      <th className="p-1.5 text-right font-bold">QTY</th>
                      <th className="p-1.5 text-right font-bold">PRICE (₹)</th>
                      <th className="p-1.5 font-bold">NOTES</th>
                      <th className="p-1.5 text-center font-bold">ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#27272a]/60">
                    {managingTrade.legs.map((leg, idx) => {
                      const isEditing = editingLegId === leg.id;
                      const isBuy = leg.action.toUpperCase() === 'BUY';
                      return (
                        <tr key={leg.id} className="hover:bg-zinc-900/50">
                          <td className="p-1.5">
                            <span
                              className={`font-bold text-[9px] px-1.5 py-0.5 rounded border ${
                                isBuy
                                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                                  : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                              }`}
                            >
                              {idx === 0 ? 'BASE BUY' : leg.action}
                            </span>
                          </td>
                          <td className="p-1.5 text-right font-bold text-white tabular-nums">
                            {isEditing ? (
                              <input
                                type="number"
                                min="1"
                                value={editLegQty}
                                onChange={(e) => setEditLegQty(e.target.value)}
                                className="w-14 bg-[#09090b] border border-terminal-amber px-1 py-0.5 text-right text-white"
                              />
                            ) : (
                              leg.quantity
                            )}
                          </td>
                          <td className="p-1.5 text-right font-bold text-white tabular-nums">
                            {isEditing ? (
                              <input
                                type="number"
                                step="any"
                                value={editLegPrice}
                                onChange={(e) => setEditLegPrice(e.target.value)}
                                className="w-16 bg-[#09090b] border border-terminal-amber px-1 py-0.5 text-right text-white"
                              />
                            ) : (
                              `₹${leg.price.toFixed(2)}`
                            )}
                          </td>
                          <td className="p-1.5 text-zinc-300 text-[10px] truncate max-w-[120px]">
                            {isEditing ? (
                              <input
                                type="text"
                                value={editLegNotes}
                                onChange={(e) => setEditLegNotes(e.target.value)}
                                className="w-full bg-[#09090b] border border-terminal-amber px-1 py-0.5 text-white"
                              />
                            ) : (
                              leg.notes || '—'
                            )}
                          </td>
                          <td className="p-1.5 text-center">
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
                                  className="px-1.5 py-0.5 bg-[#121216] border border-[#27272a] text-zinc-300 text-[9px] rounded"
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
                                  className="px-1.5 py-0.5 bg-[#18181f] border border-[#27272a] text-terminal-amber text-[9px] rounded font-bold"
                                >
                                  Edit
                                </button>
                                {managingTrade.legs.length > 1 && (
                                  <button
                                    type="button"
                                    onClick={() => deleteLegMutation.mutate(leg.id)}
                                    className="px-1.5 py-0.5 bg-rose-500/10 border border-rose-500/30 text-rose-400 text-[9px] rounded"
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
                <div className="pt-2 border-t border-[#27272a] flex justify-between items-center">
                  <span className="text-[10px] text-zinc-400">Permanently delete position:</span>
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm(`Permanently delete paper trade for ${managingTrade.symbol}?`)) {
                        deleteTradeMutation.mutate(managingTrade.id);
                      }
                    }}
                    className="px-2 py-0.5 bg-rose-500/10 border border-rose-500/40 text-rose-400 hover:bg-rose-500/20 text-[9px] rounded uppercase font-bold"
                  >
                    Delete Entire Trade
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ─── MODAL 3: LIVE SQUARE OFF CONFIRMATION ──────────────────────────── */}
      {confirmSquareOffPosition && (
        <div className="fixed inset-0 bg-[#09090b]/85 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0c0c0f] border border-rose-500/40 rounded-md shadow-2xl w-full max-w-sm p-4 text-xs font-mono flex flex-col gap-3">
            <div className="flex items-center justify-between pb-2 border-b border-[#27272a]">
              <span className="font-bold text-rose-400 text-xs uppercase tracking-wider">
                CONFIRM LIVE SQUARE OFF
              </span>
              <button
                type="button"
                onClick={() => setConfirmSquareOffPosition(null)}
                className="text-zinc-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="text-zinc-300 text-xs leading-relaxed">
              Are you sure you want to market square off{' '}
              <span className="font-bold text-white">{confirmSquareOffPosition.symbol}</span>{' '}
              ({confirmSquareOffPosition.quantity} shares on {confirmSquareOffPosition.exchange})?
            </div>

            {squareOffStatus && (
              <div className="p-2 rounded bg-zinc-900 border border-[#27272a] text-terminal-amber text-[10px]">
                {squareOffStatus}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-[#27272a]">
              <button
                type="button"
                onClick={() => setConfirmSquareOffPosition(null)}
                disabled={isSquaringOff}
                className="px-3 py-1.5 rounded bg-[#121216] border border-[#27272a] text-zinc-300 hover:border-zinc-500"
              >
                CANCEL
              </button>
              <button
                type="button"
                disabled={isSquaringOff}
                onClick={() => void handleSquareOffLivePosition(confirmSquareOffPosition)}
                className="px-4 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white font-bold uppercase tracking-wider disabled:opacity-50"
              >
                {isSquaringOff ? 'SQUARING OFF...' : 'YES, SQUARE OFF'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
