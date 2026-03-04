'use client';

import React, { useState } from 'react';
import { useAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import { activeCommandAtom, wsConnectedAtom, fundsAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';

export function CommandBar() {
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [, setFunds] = useAtom(fundsAtom);
  const [inputVal, setInputVal] = useState('');

  // Fetch account funds every 30s
  useQuery({
    queryKey: ['funds'],
    queryFn: async () => {
      const res = await OpenAlgoClient.getFunds();
      setFunds(res.data);
      return res.data;
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 1,
  });

  const [funds] = useAtom(fundsAtom);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cmd = inputVal.trim().toUpperCase();
    if (cmd) {
      setActiveCommand(cmd);
      setInputVal('');
    }
  };

  return (
    <div className="flex items-center bg-blue-900 text-white h-8 px-2 border-b border-terminal-gray font-sans font-bold text-sm shrink-0 gap-3">
      {/* WS connection indicator */}
      <div className="flex items-center gap-1 flex-shrink-0" title={wsConnected ? 'OpenAlgo WS Connected' : 'OpenAlgo WS Disconnected'}>
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            wsConnected ? 'bg-terminal-green' : 'bg-terminal-red'
          }`}
        />
        <span className="text-[10px] font-mono text-blue-300 hidden sm:inline">
          {wsConnected ? 'LIVE' : 'OFFLINE'}
        </span>
      </div>

      {/* Command prompt */}
      <span className="text-blue-300">&gt;</span>
      <form onSubmit={handleSubmit} className="flex-1 flex">
        <input
          id="terminal-command-input"
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          placeholder="CHART · WATCH · ORDER · POS · TOP · SETTINGS"
          className="bg-transparent text-white placeholder-blue-300/60 w-full outline-none uppercase font-mono text-xs tracking-wider"
          autoComplete="off"
        />
      </form>

      {/* Funds display */}
      {funds && (
        <div className="flex items-center gap-1 flex-shrink-0 text-[10px] font-mono">
          <span className="text-blue-300">CASH:</span>
          <span className="text-terminal-amber">₹{parseFloat(funds.availablecash).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
        </div>
      )}

      {/* Last command */}
      <div className="flex-shrink-0 text-[10px] font-mono hidden md:block">
        CMD: <span className="text-terminal-amber">{activeCommand || '—'}</span>
      </div>
    </div>
  );
}
