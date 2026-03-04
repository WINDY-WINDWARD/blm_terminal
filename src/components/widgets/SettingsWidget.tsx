'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { wsConnectedAtom, fundsAtom } from '@/store/terminalStore';

interface TopSymbolEntry {
  id: number;
  symbol: string;
  exchange: string;
}

async function fetchTopSymbols(): Promise<TopSymbolEntry[]> {
  const res = await fetch('/api/top-symbols');
  if (!res.ok) throw new Error('Failed to fetch top symbols');
  return res.json() as Promise<TopSymbolEntry[]>;
}

async function addTopSymbol(symbol: string, exchange: string): Promise<TopSymbolEntry> {
  const res = await fetch('/api/top-symbols', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, exchange }),
  });
  if (!res.ok) throw new Error('Failed to add symbol');
  return res.json() as Promise<TopSymbolEntry>;
}

async function removeTopSymbol(id: number): Promise<void> {
  const res = await fetch(`/api/top-symbols?id=${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to remove symbol');
}

export function SettingsWidget() {
  const qc = useQueryClient();
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [funds] = useAtom(fundsAtom);

  const [newSymbol, setNewSymbol] = useState('');
  const [newExchange, setNewExchange] = useState('NSE');

  const { data: topSymbols = [], isLoading, isError } = useQuery({
    queryKey: ['top-symbols'],
    queryFn: fetchTopSymbols,
    staleTime: 30_000,
  });

  const addMutation = useMutation({
    mutationFn: ({ symbol, exchange }: { symbol: string; exchange: string }) =>
      addTopSymbol(symbol, exchange),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['top-symbols'] });
      setNewSymbol('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => removeTopSymbol(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['top-symbols'] }),
  });

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const s = newSymbol.trim().toUpperCase();
    const ex = newExchange.trim().toUpperCase();
    if (!s || !ex) return;
    addMutation.mutate({ symbol: s, exchange: ex });
  };

  const EXCHANGES = ['NSE', 'BSE', 'NFO', 'MCX', 'BFO', 'CDS'];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto p-3 gap-4">
      <div className="text-terminal-amber font-bold text-sm border-b border-terminal-gray pb-1">
        SETTINGS
      </div>

      {/* Connection Status */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Connection
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              wsConnected ? 'bg-terminal-green' : 'bg-terminal-red'
            }`}
          />
          <span className={wsConnected ? 'text-terminal-green' : 'text-terminal-red'}>
            WebSocket: {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
          </span>
        </div>
        <div className="text-terminal-gray text-[10px]">
          OpenAlgo URL: {process.env.NEXT_PUBLIC_OPENALGO_URL ?? 'http://localhost:5000'}
        </div>
        <div className="text-terminal-gray text-[10px]">
          WebSocket: {process.env.NEXT_PUBLIC_OPENALGO_WS_URL ?? 'ws://localhost:8765'}
        </div>
      </div>

      {/* Funds */}
      {funds && (
        <div className="flex flex-col gap-1">
          <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
            Account Funds
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            {[
              ['Available Cash', funds.availablecash],
              ['Collateral', funds.collateral],
              ['M2M Realized', funds.m2mrealized],
              ['M2M Unrealized', funds.m2munrealized],
              ['Utilised Debits', funds.utiliseddebits],
            ].map(([label, val]) => (
              <React.Fragment key={label}>
                <span className="text-terminal-gray">{label}:</span>
                <span className="text-terminal-amber text-right">{val}</span>
              </React.Fragment>
            ))}
          </div>
        </div>
      )}

      {/* Top Movers Symbol Management */}
      <div className="flex flex-col gap-2">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest">
          Top Movers Symbols
        </div>

        {/* Add symbol form */}
        <form onSubmit={handleAdd} className="flex gap-1">
          <select
            value={newExchange}
            onChange={(e) => setNewExchange(e.target.value)}
            className="bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 w-16 text-xs outline-none"
          >
            {EXCHANGES.map((ex) => (
              <option key={ex} value={ex}>{ex}</option>
            ))}
          </select>
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
            placeholder="SYMBOL"
            className="flex-1 bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase"
          />
          <button
            type="submit"
            disabled={addMutation.isPending}
            className="px-2 py-0.5 bg-blue-800 hover:bg-blue-700 text-white border border-blue-500 disabled:opacity-50"
          >
            +ADD
          </button>
        </form>

        {addMutation.isError && (
          <div className="text-terminal-red text-[10px]">
            {addMutation.error instanceof Error ? addMutation.error.message : 'Error adding symbol'}
          </div>
        )}

        {/* Symbol list */}
        {isLoading && <div className="text-terminal-gray">Loading...</div>}
        {isError && <div className="text-terminal-red">Failed to load symbols</div>}

        <div className="flex flex-col gap-0.5">
          {topSymbols.map((entry) => (
            <div
              key={entry.id}
              className="flex items-center justify-between px-1 py-0.5 hover:bg-zinc-900 border border-terminal-gray"
            >
              <span>
                <span className="text-terminal-gray text-[10px] mr-1">{entry.exchange}</span>
                <span className="text-terminal-amber">{entry.symbol}</span>
              </span>
              <button
                onClick={() => removeMutation.mutate(entry.id)}
                disabled={removeMutation.isPending}
                className="text-terminal-gray hover:text-terminal-red text-[10px] px-1"
                title="Remove"
              >
                ✕
              </button>
            </div>
          ))}
          {topSymbols.length === 0 && !isLoading && (
            <div className="text-terminal-gray text-center py-2">
              No symbols added yet.
            </div>
          )}
        </div>
      </div>

      {/* Tips */}
      <div className="flex flex-col gap-0.5 mt-auto">
        <div className="text-terminal-gray text-[10px] border-t border-terminal-gray pt-2">
          Commands: CHART · WATCH · ORDER · POS · TOP · SETTINGS
        </div>
        <div className="text-terminal-gray text-[10px]">
          Press / or Escape to focus command bar
        </div>
        <div className="text-terminal-gray text-[10px]">
          F1 = BUY · F2 = SELL (in ORDER widget)
        </div>
      </div>
    </div>
  );
}
