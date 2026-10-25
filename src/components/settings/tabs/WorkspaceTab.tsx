'use client';

import React, { useState } from 'react';
import type { PanelCount, Watchlist, SavedLayout } from '@/store/terminalStore';
import { BentoCard } from './BentoCard';

export const WATCHLIST_COLUMNS = [
  { key: 'ltp', label: 'LTP' },
  { key: 'chg', label: 'CHG%' },
  { key: 'msfv', label: 'MS FV' },
  { key: 'momentum', label: 'MOMENTUM' },
  { key: '1w', label: '1W%' },
  { key: '1m', label: '1M%' },
  { key: '3m', label: '3M%' },
  { key: '6m', label: '6M%' },
  { key: '1y', label: '1Y%' },
  { key: 'results', label: 'RESULTS' },
  { key: '2y', label: '2Y%' },
  { key: '3y', label: '3Y%' },
  { key: '5y', label: '5Y%' },
  { key: '52wh', label: '52W HIGH' },
  { key: '52wl', label: '52W LOW' },
  { key: 'alerts', label: 'ALERTS' },
];

export const MOVERS_COLUMNS = [
  { key: 'open', label: 'OPEN' },
  { key: 'high', label: 'HIGH' },
  { key: 'low', label: 'LOW' },
  { key: 'vol', label: 'VOL' },
  { key: 'trnvr', label: 'TRNVR' },
  { key: 'ca', label: 'CA' },
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
          <span className="text-white/70 text-[10px]">{col.label}</span>
        </label>
      ))}
    </div>
  );
}

export interface WorkspaceTabProps {
  panelCount: PanelCount;
  onPanelCountChange: (count: PanelCount) => void;
  tickerSource: string;
  onTickerSourceChange: (source: string) => void;
  watchlists: Watchlist[];
  savedLayouts: Record<string, SavedLayout>;
  syncStatus: { status: 'idle' | 'pending' | 'synced' | 'error'; pendingCount: number };
  isAuthenticated: boolean;
  onDeleteLayout: (name: string) => void;
  onRenameLayout: (oldName: string, newName: string) => void;
  watchlistCols: string[];
  onWatchlistColsChange: (key: string, checked: boolean) => void;
  moversCols: string[];
  onMoversColsChange: (key: string, checked: boolean) => void;
}

export function WorkspaceTab({
  panelCount,
  onPanelCountChange,
  tickerSource,
  onTickerSourceChange,
  watchlists,
  savedLayouts,
  syncStatus,
  isAuthenticated,
  onDeleteLayout,
  onRenameLayout,
  watchlistCols,
  onWatchlistColsChange,
  moversCols,
  onMoversColsChange,
}: WorkspaceTabProps) {
  const [renamingLayout, setRenamingLayout] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const handleStartRename = (layout: SavedLayout) => {
    setRenamingLayout(layout.name);
    setRenameValue(layout.name);
  };

  const handleFinishRename = (oldName: string) => {
    onRenameLayout(oldName, renameValue);
    setRenamingLayout(null);
  };

  return (
    <>
      {/* Window Layout */}
      <BentoCard
        icon="▦"
        title="Window Layout"
        blurb="How many panels share the screen. Switching counts resets panel sizes and merges."
        className="col-span-1 md:col-span-2 lg:col-span-2"
      >
        <div className="flex flex-col gap-1" data-tour="layout-controls">
          <div className="flex flex-wrap gap-2">
            {[2, 4, 6, 8].map((count) => {
              const isActive = panelCount === count;
              return (
                <button
                  key={count}
                  type="button"
                  onClick={() => onPanelCountChange(count as PanelCount)}
                  className={`min-w-10 border px-2 py-1 text-[10px] font-bold uppercase transition-colors ${
                    isActive
                      ? 'border-terminal-amber bg-terminal-amber text-black'
                      : 'border-terminal-gray text-white hover:border-terminal-amber hover:text-terminal-amber'
                  }`}
                >
                  {count}
                </button>
              );
            })}
          </div>
        </div>
      </BentoCard>

      {/* Ticker Source */}
      <BentoCard
        icon="◉"
        title="Ticker Source"
        blurb="Feed for the scrolling ticker bar at the top of the terminal."
        className="col-span-1 md:col-span-2 lg:col-span-2"
      >
        <div className="flex flex-col gap-1">
          <select
            value={tickerSource}
            onChange={(e) => onTickerSourceChange(e.target.value)}
            className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
          >
            <option value="default">Default (First Watchlist)</option>
            <option value="top">Top Movers (Gainers + Losers)</option>
            {watchlists.map((wl) => (
              <option key={wl.id} value={`watchlist:${wl.id}`}>
                Watchlist: {wl.name}
              </option>
            ))}
          </select>
        </div>
      </BentoCard>

      {/* Saved Layouts */}
      {Object.keys(savedLayouts).length > 0 && (
        <BentoCard
          icon="❏"
          title="Saved Layouts"
          blurb="Named snapshots of your panel arrangement. Load one with :name in the command bar."
          badge={
            isAuthenticated ? (
              <span
                className={`text-[9px] font-mono uppercase tracking-wider ${
                  syncStatus.status === 'error'
                    ? 'text-terminal-red'
                    : syncStatus.status === 'pending'
                    ? 'text-terminal-amber/70'
                    : 'text-terminal-green/70'
                }`}
              >
                {syncStatus.status === 'pending'
                  ? `Syncing (${syncStatus.pendingCount})`
                  : syncStatus.status === 'error'
                  ? 'Sync Error'
                  : 'Synced'}
              </span>
            ) : undefined
          }
          className="col-span-1 md:col-span-2 lg:col-span-4"
        >
          <div className="flex flex-col gap-1">
            <div className="flex flex-col gap-0.5">
              {Object.values(savedLayouts)
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((layout) => {
                  const widgetList = Object.values(layout.activePanels)
                    .slice(0, layout.panelCount)
                    .join(', ');
                  return (
                    <div key={layout.name} className="flex items-center justify-between gap-2 group">
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        {renamingLayout === layout.name ? (
                          <input
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={() => handleFinishRename(layout.name)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleFinishRename(layout.name);
                              if (e.key === 'Escape') setRenamingLayout(null);
                            }}
                            autoFocus
                            className="bg-black border border-terminal-amber text-terminal-amber text-xs px-1 py-0.5 outline-none font-mono w-24"
                          />
                        ) : (
                          <span className="text-terminal-amber font-bold text-xs font-mono">
                            :{layout.name}
                          </span>
                        )}
                        <span className="text-white/40 text-[9px] shrink-0">
                          {layout.panelCount}P
                        </span>
                        <span className="text-white/30 text-[9px] truncate">
                          {widgetList}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleStartRename(layout)}
                          className="text-white/30 hover:text-terminal-amber text-xs transition-colors px-0.5"
                          title="Rename layout"
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          onClick={() => onDeleteLayout(layout.name)}
                          className="text-terminal-red/50 hover:text-terminal-red text-xs font-bold transition-colors px-0.5"
                          title="Delete layout"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </BentoCard>
      )}

      {/* Table Columns */}
      <BentoCard
        icon="☰"
        title="Table Columns"
        blurb="Choose which columns appear in the Watch and Movers tables. Drag table headers inside either widget to change their order."
        className="col-span-1 md:col-span-2 lg:col-span-4"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5 bg-black/30 border border-zinc-800/80 p-2.5 rounded">
            <span className="text-terminal-amber text-[10px] uppercase tracking-wider font-semibold">Watch table</span>
            <ColumnCheckboxes
              columns={WATCHLIST_COLUMNS}
              selected={watchlistCols}
              onChange={onWatchlistColsChange}
            />
          </div>
          <div className="flex flex-col gap-1.5 bg-black/30 border border-zinc-800/80 p-2.5 rounded">
            <span className="text-terminal-amber text-[10px] uppercase tracking-wider font-semibold">Movers optional columns</span>
            <span className="text-[10px] text-zinc-400">Ticker, change, and 1W–1Y momentum stay visible. Use header drag to reorder.</span>
            <ColumnCheckboxes
              columns={MOVERS_COLUMNS}
              selected={moversCols}
              onChange={onMoversColsChange}
            />
          </div>
        </div>
      </BentoCard>
    </>
  );
}
