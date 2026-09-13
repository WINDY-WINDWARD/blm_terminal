'use client';

import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { useAtom, useAtomValue } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import {
  activeCommandAtom,
  wsConnectedAtom,
  fundsAtom,
  activeSymbolAtom,
  activeExchangeAtom,
  savedLayoutsAtom,
} from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';

interface WidgetCommand {
  cmd: string;
  desc: string;
}

interface SymbolSuggestion {
  symbol: string;
  companyName: string;
}

const WIDGET_COMMANDS: WidgetCommand[] = [
  { cmd: 'CHART', desc: 'Candlestick chart' },
  { cmd: 'WATCH', desc: 'Watchlist' },
  { cmd: 'POS', desc: 'Positions & P&L' },
  { cmd: 'TOP', desc: 'Top movers' },
  { cmd: 'SETTINGS', desc: 'App settings' },
  { cmd: 'FDM', desc: 'Fundamentals' },
  { cmd: 'DEALS', desc: 'Bulk/block deals' },
  { cmd: 'LARGEDEALS', desc: 'Large deals snapshot' },
  { cmd: 'BREAKOUTS', desc: '52-week breakouts' },
  { cmd: 'NEWS', desc: 'Market & company news' },
  { cmd: 'ANALYSIS', desc: 'Sector & industry analysis' },
  { cmd: 'NOTIF', desc: 'Notifications generated' },
  { cmd: 'ANNC', desc: 'NSE announcements feed' },
  { cmd: 'SCAN', desc: 'Global market scanner' },
  { cmd: 'SCREENER', desc: 'Stock screener with multi-timeframe filters' },
  { cmd: 'DOCS', desc: 'Panel documentation' },
  { cmd: 'AI', desc: 'Live market AI chat' },
  { cmd: 'PORTFOLIO', desc: 'Portfolio optimizer (MPT)' },
  { cmd: 'ADMIN', desc: 'Admin Dashboard' },
  { cmd: 'PICKS', desc: 'AI Swing Trade Picks' },
  { cmd: 'CLEAR', desc: 'Clear focused slot (empty slot)' },
  { cmd: 'LOGOUT', desc: 'End session and log out' },
];

export function CommandBar() {
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [, setFunds] = useAtom(fundsAtom);
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [activeSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const savedLayouts = useAtomValue(savedLayoutsAtom);

  const [inputVal, setInputVal] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [symbolSuggestions, setSymbolSuggestions] = useState<SymbolSuggestion[]>([]);
  const [statusMsg, setStatusMsg] = useState('');
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const statusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dropdownRef = React.useRef<HTMLDivElement>(null);

  // Rotate placeholder hints every 3 seconds
  useEffect(() => {
    const timer = setInterval(() => {
      setPlaceholderIdx((prev) => (prev + 1) % 4);
    }, 6000);
    return () => clearInterval(timer);
  }, []);

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

  // Detect modes
  const isSymbolMode = inputVal.startsWith('/');
  const isMetaMode = inputVal.startsWith(':');
  const symbolQuery = isSymbolMode ? inputVal.slice(1).toUpperCase() : '';

  // Debounced symbol search
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!isSymbolMode) {
      setSymbolSuggestions([]);
      return;
    }
    if (!symbolQuery) {
      setSymbolSuggestions([]);
      return;
    }

    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(async () => {
      try {
        const res = await fetch(
          `/api/py/stockuniverse/search/${encodeURIComponent(symbolQuery)}`
        );
        if (!res.ok) return;
        const data = (await res.json()) as SymbolSuggestion[];
        setSymbolSuggestions(data.slice(0, 8));
      } catch {
        setSymbolSuggestions([]);
      }
    }, 300);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [symbolQuery, isSymbolMode]);

  // Derive widget command suggestions (only in non-symbol, non-meta mode)
  const widgetSuggestions = useMemo(() => {
    if (isSymbolMode || isMetaMode || !inputVal.trim()) return [];
    const upper = inputVal.toUpperCase();
    const prefix = WIDGET_COMMANDS.filter((w) => w.cmd.startsWith(upper));
    const includes = WIDGET_COMMANDS.filter(
      (w) => !w.cmd.startsWith(upper) && w.cmd.includes(upper)
    );
    return [...prefix, ...includes].slice(0, 10);
  }, [inputVal, isSymbolMode, isMetaMode]);

  // Derive meta-command suggestions (layout save/load) when input starts with ':'
  const metaSuggestions = useMemo(() => {
    if (!isMetaMode) return [];
    const query = inputVal.slice(1).trim().toLowerCase();
    const entries: WidgetCommand[] = [
      { cmd: ':save <name>', desc: 'Save current layout' },
    ];
    // Add existing saved layouts as load commands
    for (const layout of Object.values(savedLayouts)) {
      entries.push({ cmd: `:${layout.name}`, desc: `Load layout (${layout.panelCount} panels)` });
    }
    if (!query) return entries.slice(0, 12);
    // Filter: match against the part after ':'
    return entries
      .filter((e) => {
        const cmdPart = e.cmd.slice(1).toLowerCase();
        return cmdPart.includes(query);
      })
      .slice(0, 12);
  }, [isMetaMode, inputVal, savedLayouts]);

  // Unified suggestions count for keyboard nav
  const totalSuggestions = isMetaMode
    ? metaSuggestions.length
    : isSymbolMode
      ? symbolSuggestions.length
      : widgetSuggestions.length;
  const showSuggestions = totalSuggestions > 0;

  const showStatus = useCallback((msg: string) => {
    setStatusMsg(msg);
    if (statusTimerRef.current) clearTimeout(statusTimerRef.current);
    statusTimerRef.current = setTimeout(() => setStatusMsg(''), 1500);
  }, []);

  const handleSelectWidget = (cmd: string) => {
    setActiveCommand(cmd);
    setInputVal('');
    setSelectedIdx(-1);
    setSymbolSuggestions([]);
  };

  const handleSelectSymbol = (symbol: string) => {
    setActiveSymbol(symbol);
    setActiveExchange('NSE');
    showStatus(`Symbol: ${symbol}`);
    setInputVal('');
    setSelectedIdx(-1);
    setSymbolSuggestions([]);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (isSymbolMode) {
      // Symbol mode: use highlighted suggestion or typed query
      if (selectedIdx >= 0 && symbolSuggestions[selectedIdx]) {
        handleSelectSymbol(symbolSuggestions[selectedIdx].symbol);
      } else if (symbolQuery) {
        handleSelectSymbol(symbolQuery);
      }
      return;
    }

    // Meta-command mode: :save <name> or :<name>
    if (isMetaMode) {
      // If a suggestion is highlighted, use it
      if (selectedIdx >= 0 && metaSuggestions[selectedIdx]) {
        const selected = metaSuggestions[selectedIdx].cmd;
        if (selected === ':save <name>') {
          // Just autocomplete the prefix, user still needs to type a name
          setInputVal(':save ');
          setSelectedIdx(-1);
          return;
        }
        // It's a load command like ":trading"
        const name = selected.slice(1).toLowerCase();
        setActiveCommand(`__LOAD_LAYOUT:${name}`);
        setInputVal('');
        setSelectedIdx(-1);
        return;
      }

      const meta = inputVal.slice(1).trim();
      // :save <name>
      const saveMatch = meta.match(/^save\s+(.+)$/i);
      if (saveMatch) {
        const name = saveMatch[1].trim().toLowerCase();
        if (name && name !== 'save') {
          setActiveCommand(`__SAVE_LAYOUT:${name}`);
        }
        setInputVal('');
        setSelectedIdx(-1);
        return;
      }

      // :<name> (load)
      const name = meta.toLowerCase();
      if (name && name !== 'save') {
        setActiveCommand(`__LOAD_LAYOUT:${name}`);
      }
      setInputVal('');
      setSelectedIdx(-1);
      return;
    }

    // Widget command mode
    if (selectedIdx >= 0 && widgetSuggestions[selectedIdx]) {
      handleSelectWidget(widgetSuggestions[selectedIdx].cmd);
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
    if (e.key === 'Escape') {
      e.preventDefault();
      setInputVal('');
      setSelectedIdx(-1);
      setSymbolSuggestions([]);
      return;
    }

    if (!showSuggestions) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((prev) => (prev + 1) % totalSuggestions);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((prev) => (prev === 0 ? totalSuggestions - 1 : prev - 1));
    } else if (e.key === 'Tab') {
      e.preventDefault();
      const idx = selectedIdx >= 0 ? selectedIdx : 0;
      if (isMetaMode) {
        const cmd = metaSuggestions[idx]?.cmd ?? '';
        setInputVal(cmd === ':save <name>' ? ':save ' : cmd);
      } else if (isSymbolMode) {
        setInputVal('/' + (symbolSuggestions[idx]?.symbol ?? ''));
      } else {
        setInputVal(widgetSuggestions[idx].cmd);
      }
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
        {isMetaMode
          ? metaSuggestions.map((suggestion, idx) => (
              <div
                key={suggestion.cmd}
                onClick={() => {
                  if (suggestion.cmd === ':save <name>') {
                    setInputVal(':save ');
                    setSelectedIdx(-1);
                  } else {
                    const name = suggestion.cmd.slice(1).toLowerCase();
                    setActiveCommand(`__LOAD_LAYOUT:${name}`);
                    setInputVal('');
                    setSelectedIdx(-1);
                  }
                }}
                className={`flex justify-between items-center px-3 py-1.5 text-xs font-mono cursor-pointer transition-colors ${
                  idx === selectedIdx
                    ? 'bg-blue-800/60 text-white'
                    : 'bg-zinc-900 text-blue-200 hover:bg-zinc-800'
                }`}
              >
                <span className="text-terminal-green font-bold">{suggestion.cmd}</span>
                <span className="text-blue-300/70 ml-2">{suggestion.desc}</span>
              </div>
            ))
          : isSymbolMode
            ? symbolSuggestions.map((s, idx) => (
                <div
                  key={s.symbol}
                  onClick={() => handleSelectSymbol(s.symbol)}
                  className={`flex justify-between items-center px-3 py-1.5 text-xs font-mono cursor-pointer transition-colors ${
                    idx === selectedIdx
                      ? 'bg-blue-800/60 text-white'
                      : 'bg-zinc-900 text-blue-200 hover:bg-zinc-800'
                  }`}
                >
                  <span className="text-terminal-amber font-bold">{s.symbol}</span>
                  <span className="text-blue-300/70 ml-2 truncate">{s.companyName}</span>
                </div>
              ))
            : widgetSuggestions.map((suggestion, idx) => (
                <div
                  key={suggestion.cmd}
                  onClick={() => handleSelectWidget(suggestion.cmd)}
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

  const defaultHints = [
    WIDGET_COMMANDS.map((w) => w.cmd).join(' · '),
    'Type a command to open a widget (e.g., CHART, WATCH, POS)…',
    'Type /<symbol> to change the global active company…',
    'Type :save <name> to save layout, or :<name> to load…',
  ];

  const placeholder = isMetaMode
    ? ':save <name> · :<name> to load'
    : isSymbolMode
      ? 'Type symbol or company name…'
      : defaultHints[placeholderIdx];

  return (
    <div className="flex items-center bg-blue-900 text-white h-8 px-2 border-b border-terminal-gray font-sans font-bold text-sm shrink-0 gap-3 relative">
      {/* WS connection indicator */}
      <div
        className="flex items-center gap-1 flex-shrink-0"
        title={wsConnected ? 'Market Data Connected' : 'Market Data Disconnected'}
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

      {/* Command prompt — changes colour in symbol mode */}
      <span className={isMetaMode ? 'text-terminal-green' : isSymbolMode ? 'text-terminal-amber' : 'text-blue-300'}>&gt;</span>

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
          placeholder={placeholder}
          className={`bg-transparent placeholder-blue-300/60 w-full outline-none font-mono text-xs tracking-wider ${
            isMetaMode ? 'text-terminal-green' : isSymbolMode ? 'text-terminal-amber uppercase' : 'text-white uppercase'
          }`}
          autoComplete="off"
        />
        {renderDropdown()}
      </form>

      {/* Status message (symbol set confirmation) */}
      {statusMsg && (
        <div className="flex-shrink-0 text-[10px] font-mono text-terminal-green animate-pulse">
          {statusMsg}
        </div>
      )}

      {/* Funds display */}
      {!statusMsg && funds && (
        <div className="flex items-center gap-1 flex-shrink-0 text-[10px] font-mono">
          <span className="text-blue-300">CASH:</span>
          <span className="text-terminal-amber">
            ₹{parseFloat(funds.availablecash).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
      )}

      {/* Active symbol indicator */}
      <div className="flex-shrink-0 text-[10px] font-mono hidden md:flex items-center gap-1">
        <span className="text-blue-300/60">SYM:</span>
        <span className="text-terminal-amber">{activeSymbol}</span>
      </div>

      {/* Last command */}
      <div className="flex-shrink-0 text-[10px] font-mono hidden md:block">
        CMD: <span className="text-terminal-amber">{activeCommand || '—'}</span>
      </div>
    </div>
  );
}
