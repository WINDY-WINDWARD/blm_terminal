'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAtom } from 'jotai';
import { wsConnectedAtom, fundsAtom, watchlistColumnsAtom, moversColumnsAtom } from '@/store/terminalStore';

const WATCHLIST_COLUMNS = [
  { key: 'ltp', label: 'LTP' },
  { key: 'chg', label: 'CHG%' },
  { key: '1w', label: '1W%' },
  { key: '1m', label: '1M%' },
  { key: '3m', label: '3M%' },
  { key: '6m', label: '6M%' },
  { key: '1y', label: '1Y%' },
  { key: '2y', label: '2Y%' },
  { key: '3y', label: '3Y%' },
  { key: '5y', label: '5Y%' },
  { key: '52wh', label: '52W HIGH' },
  { key: '52wl', label: '52W LOW' },
];

const MOVERS_COLUMNS = [
  { key: 'close', label: 'CLOSE' },
  { key: 'chg', label: 'CHG%' },
  { key: '1w', label: '1W%' },
  { key: '1m', label: '1M%' },
  { key: '3m', label: '3M%' },
  { key: '6m', label: '6M%' },
  { key: '1y', label: '1Y%' },
  { key: '2y', label: '2Y%' },
  { key: '3y', label: '3Y%' },
  { key: '5y', label: '5Y%' },
  { key: '52wh', label: '52W HIGH' },
  { key: '52wl', label: '52W LOW' },
];

function ColumnCheckboxes({
  columns,
  selected,
  onChange,
}: {
  columns: { key: string; label: string }[];
  selected: string[];
  onChange: (key: string, checked: boolean) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-x-2 gap-y-1">
      {columns.map((col) => (
        <label key={col.key} className="flex items-center gap-1 cursor-pointer">
          <input
            type="checkbox"
            checked={selected.includes(col.key)}
            onChange={(e) => onChange(col.key, e.target.checked)}
            className="accent-terminal-amber"
          />
          <span className="text-terminal-amber text-[10px]">{col.label}</span>
        </label>
      ))}
    </div>
  );
}

export function SettingsWidget() {
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [funds] = useAtom(fundsAtom);
  const [watchlistCols, setWatchlistCols] = useAtom(watchlistColumnsAtom);
  const [moversCols, setMoversCols] = useAtom(moversColumnsAtom);

  const [loading, setLoading] = useState(true);

  // Keep a ref with the latest columns so the debounced save never reads a stale closure
  const latestCols = useRef({ watchlist: watchlistCols, movers: moversCols });
  useEffect(() => {
    latestCols.current = { watchlist: watchlistCols, movers: moversCols };
  }, [watchlistCols, moversCols]);

  const saveTimerRef = useRef<NodeJS.Timeout | null>(null);

  const scheduleSave = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const { watchlist, movers } = latestCols.current;
      fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ watchlistColumns: watchlist, moversColumns: movers }),
      }).catch(console.error);
    }, 300);
  }, []);

  useEffect(() => {
    fetch('/api/settings')
      .then((res) => res.json())
      .then((data) => {
        if (data.watchlistColumns) {
          setWatchlistCols(data.watchlistColumns);
        }
        if (data.moversColumns) {
          setMoversCols(data.moversColumns);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [setWatchlistCols, setMoversCols]);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  const handleWatchlistChange = (key: string, checked: boolean) => {
    const newCols = checked
      ? [...watchlistCols, key]
      : watchlistCols.filter((c) => c !== key);
    setWatchlistCols(newCols);
    scheduleSave();
  };

  const handleMoversChange = (key: string, checked: boolean) => {
    const newCols = checked
      ? [...moversCols, key]
      : moversCols.filter((c) => c !== key);
    setMoversCols(newCols);
    scheduleSave();
  };

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

      {/* Watchlist Columns */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Watchlist Columns
        </div>
        {loading ? (
          <div className="text-terminal-gray">Loading...</div>
        ) : (
          <ColumnCheckboxes
            columns={WATCHLIST_COLUMNS}
            selected={watchlistCols}
            onChange={handleWatchlistChange}
          />
        )}
      </div>

      {/* Movers Columns */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Movers Columns
        </div>
        {loading ? (
          <div className="text-terminal-gray">Loading...</div>
        ) : (
          <ColumnCheckboxes
            columns={MOVERS_COLUMNS}
            selected={moversCols}
            onChange={handleMoversChange}
          />
        )}
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
