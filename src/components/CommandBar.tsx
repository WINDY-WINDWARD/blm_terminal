'use client';

import React, { useState, useMemo } from 'react';
import { useAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import { activeCommandAtom, wsConnectedAtom, fundsAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';

interface WidgetCommand {
  cmd: string;
  desc: string;
}

const WIDGET_COMMANDS: WidgetCommand[] = [
  { cmd: 'CHART', desc: 'Candlestick chart' },
  { cmd: 'WATCH', desc: 'Watchlist' },
  { cmd: 'ORDER', desc: 'Order entry & book' },
  { cmd: 'POS', desc: 'Positions & P&L' },
  { cmd: 'TOP', desc: 'Top movers' },
  { cmd: 'SETTINGS', desc: 'App settings' },
  { cmd: 'FDM', desc: 'Fundamentals' },
  { cmd: 'DEALS', desc: 'Bulk/block deals' },
  { cmd: 'LARGEDEALS', desc: 'Large deals snapshot' },
  { cmd: 'BREAKOUTS', desc: '52-week breakouts' },
  { cmd: 'NEWS', desc: 'Market & company news' },
  { cmd: 'ANALYSIS', desc: 'Sector & industry analysis' },
];

export function CommandBar() {
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [, setFunds] = useAtom(fundsAtom);
  const [inputVal, setInputVal] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const dropdownRef = React.useRef<HTMLDivElement>(null);

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

  // Derive suggestions: prefix matches first, then includes matches
  const suggestions = useMemo(() => {
    if (!inputVal.trim()) return [];
    const upper = inputVal.toUpperCase();
    const prefix = WIDGET_COMMANDS.filter((w) => w.cmd.startsWith(upper));
    const includes = WIDGET_COMMANDS.filter(
      (w) => !w.cmd.startsWith(upper) && w.cmd.includes(upper)
    );
    return [...prefix, ...includes].slice(0, 10);
  }, [inputVal]);

  const showSuggestions = inputVal.length > 0 && suggestions.length > 0;

  const handleSelect = (cmd: string) => {
    setActiveCommand(cmd);
    setInputVal('');
    setSelectedIdx(-1);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedIdx >= 0 && suggestions[selectedIdx]) {
      handleSelect(suggestions[selectedIdx].cmd);
    } else {
      const cmd = inputVal.trim().toUpperCase();
      if (cmd) {
        setActiveCommand(cmd);
        setInputVal('');
        setSelectedIdx(-1);
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showSuggestions) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((prev) => (prev + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((prev) => (prev === 0 ? suggestions.length - 1 : prev - 1));
    } else if (e.key === 'Tab') {
      e.preventDefault();
      const idx = selectedIdx >= 0 ? selectedIdx : 0;
      setInputVal(suggestions[idx].cmd);
      setSelectedIdx(-1);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setInputVal('');
      setSelectedIdx(-1);
    }
  };

  const renderDropdown = () => {
    if (!showSuggestions) return null;

    return (
      <div
        ref={dropdownRef}
        className="absolute top-8 left-0 right-0 bg-zinc-900 border border-terminal-gray rounded shadow-lg z-50 max-h-48 overflow-y-auto"
      >
        {suggestions.map((suggestion, idx) => (
          <div
            key={suggestion.cmd}
            onClick={() => handleSelect(suggestion.cmd)}
            className={`flex justify-between items-center px-3 py-1.5 text-xs font-mono cursor-pointer transition-colors ${
              idx === selectedIdx
                ? 'bg-blue-800/60 text-white'
                : 'bg-zinc-900 text-blue-200 hover:bg-zinc-800'
            }`}
          >
            <span className="text-terminal-amber font-bold">{suggestion.cmd}</span>
            <span className="text-blue-300/70 ml-2">{suggestion.desc}</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="flex items-center bg-blue-900 text-white h-8 px-2 border-b border-terminal-gray font-sans font-bold text-sm shrink-0 gap-3 relative">
      {/* WS connection indicator */}
      <div
        className="flex items-center gap-1 flex-shrink-0"
        title={wsConnected ? 'OpenAlgo WS Connected' : 'OpenAlgo WS Disconnected'}
      >
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
      <form onSubmit={handleSubmit} className="flex-1 flex relative">
        <input
          id="terminal-command-input"
          type="text"
          value={inputVal}
          onChange={(e) => {
            setInputVal(e.target.value);
            setSelectedIdx(-1);
          }}
          onKeyDown={handleKeyDown}
          onBlur={() => {
            setTimeout(() => setSelectedIdx(-1), 250);
          }}
          placeholder="CHART · WATCH · ORDER · POS · TOP · SETTINGS · FDM · DEALS · LARGEDEALS · BREAKOUTS · NEWS · ANALYSIS"
          className="bg-transparent text-white placeholder-blue-300/60 w-full outline-none uppercase font-mono text-xs tracking-wider"
          autoComplete="off"
        />
        {renderDropdown()}
      </form>

      {/* Funds display */}
      {funds && (
        <div className="flex items-center gap-1 flex-shrink-0 text-[10px] font-mono">
          <span className="text-blue-300">CASH:</span>
          <span className="text-terminal-amber">
            ₹{parseFloat(funds.availablecash).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
      )}

      {/* Last command */}
      <div className="flex-shrink-0 text-[10px] font-mono hidden md:block">
        CMD: <span className="text-terminal-amber">{activeCommand || '—'}</span>
      </div>
    </div>
  );
}
