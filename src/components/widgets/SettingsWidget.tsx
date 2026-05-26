'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import Link from 'next/link';
import {
  wsConnectedAtom,
  fundsAtom,
  watchlistColumnsAtom,
  moversColumnsAtom,
  watchlistsAtom,
  activeWatchlistIdAtom,
  panelCountAtom,
  panelSizesAtom,
  type Watchlist,
  type PanelCount,
} from '@/store/terminalStore';

const NOTIF_CONFIG_KEYS = [
  'notif.rsi_oversold_threshold',
  'notif.rsi_overbought_threshold',
  'notif.volatility_spike_ratio',
  'notif.atr_expansion_threshold',
  'notif.momentum_surge_threshold',
  'notif.return_1w_spike_threshold',
  'notif.streak_days_threshold',
  'notif.near_52w_threshold',
  'notif.deal_significance_pct',
  'notif.deal_absolute_threshold_cr',
] as const;

const NOTIF_CONFIG_LABELS: Record<(typeof NOTIF_CONFIG_KEYS)[number], string> = {
  'notif.rsi_oversold_threshold': 'RSI Oversold',
  'notif.rsi_overbought_threshold': 'RSI Overbought',
  'notif.volatility_spike_ratio': 'Volatility Spike Ratio',
  'notif.atr_expansion_threshold': 'ATR Expansion',
  'notif.momentum_surge_threshold': 'Momentum Surge',
  'notif.return_1w_spike_threshold': '1W Return Spike',
  'notif.streak_days_threshold': 'Streak Days',
  'notif.near_52w_threshold': 'Near 52W Threshold',
  'notif.deal_significance_pct': 'Deal Min % of Mkt Cap',
  'notif.deal_absolute_threshold_cr': 'Deal Min Value (₹ Cr)',
};

type NotifConfigKey = (typeof NOTIF_CONFIG_KEYS)[number];

type NotifConfigState = Record<NotifConfigKey, string>;

const DEFAULT_NOTIF_CONFIG: NotifConfigState = {
  'notif.rsi_oversold_threshold': '30',
  'notif.rsi_overbought_threshold': '70',
  'notif.volatility_spike_ratio': '1.5',
  'notif.atr_expansion_threshold': '4',
  'notif.momentum_surge_threshold': '70',
  'notif.return_1w_spike_threshold': '10',
  'notif.streak_days_threshold': '5',
  'notif.near_52w_threshold': '3',
  'notif.deal_significance_pct': '0.05',
  'notif.deal_absolute_threshold_cr': '2',
};

const WATCHLIST_COLUMNS = [
  { key: 'ltp', label: 'LTP' },
  { key: 'chg', label: 'CHG%' },
  { key: 'msfv', label: 'MS FV' },
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

const MOVERS_COLUMNS = [
  { key: 'close', label: 'CLOSE' },
  { key: 'chg', label: 'CHG%' },
  { key: 'open', label: 'OPEN' },
  { key: 'high', label: 'HIGH' },
  { key: 'low', label: 'LOW' },
  { key: 'vol', label: 'VOL' },
  { key: 'trnvr', label: 'TRNVR' },
  { key: 'ca', label: 'CA' },
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

function ThresholdInputs({
  values,
  onChange,
  disabled,
}: {
  values: NotifConfigState;
  onChange: (key: NotifConfigKey, value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {NOTIF_CONFIG_KEYS.map((key) => (
        <label key={key} className="flex flex-col gap-1">
          <span className="text-terminal-amber text-[10px] uppercase tracking-widest">
            {NOTIF_CONFIG_LABELS[key]}
          </span>
          <input
            type="number"
            step="any"
            value={values[key]}
            disabled={disabled}
            onChange={(e) => onChange(key, e.target.value)}
            className="bg-black border border-terminal-gray text-white text-xs px-2 py-1 outline-none focus:border-terminal-amber disabled:opacity-60"
          />
        </label>
      ))}
    </div>
  );
}

export function SettingsWidget() {
  const qc = useQueryClient();
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [funds] = useAtom(fundsAtom);
  const [watchlistCols, setWatchlistCols] = useAtom(watchlistColumnsAtom);
  const [moversCols, setMoversCols] = useAtom(moversColumnsAtom);
  const [watchlists, setWatchlists] = useAtom(watchlistsAtom);
  const [activeWatchlistId, setActiveWatchlistId] = useAtom(activeWatchlistIdAtom);
  const [panelCount, setPanelCount] = useAtom(panelCountAtom);
  const [, setPanelSizes] = useAtom(panelSizesAtom);
  const [notifConfig, setNotifConfig] = useState<NotifConfigState>(DEFAULT_NOTIF_CONFIG);
  const [appVersion, setAppVersion] = useState<string>('');

  const [configLoading, setConfigLoading] = useState(true);

  const configSaveTimerRef = useRef<Partial<Record<NotifConfigKey, NodeJS.Timeout>>>({});

  const scheduleNotifConfigSave = (key: NotifConfigKey, value: string) => {
    const existingTimer = configSaveTimerRef.current[key];
    if (existingTimer) clearTimeout(existingTimer);
    configSaveTimerRef.current[key] = setTimeout(() => {
      fetch(`/api/py/system-config/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: Number(value) }),
      }).catch(console.error);
    }, 300);
  };

  useEffect(() => {
    fetch('/api/py/system-config')
      .then((res) => res.json())
      .then((data: Partial<Record<NotifConfigKey, number>> & { 'app.version'?: string }) => {
        setNotifConfig((current) => ({
          ...current,
          ...Object.fromEntries(
            NOTIF_CONFIG_KEYS.map((key) => [
              key,
              data[key] !== undefined ? String(data[key]) : current[key],
            ]),
          ),
        }));
        if (data['app.version']) {
          setAppVersion(data['app.version']);
        }
      })
      .catch(console.error)
      .finally(() => setConfigLoading(false));
  }, []);

  // Fetch watchlists on mount
  useEffect(() => {
    fetch('/api/watchlists')
      .then((res) => res.json())
      .then((data: Watchlist[]) => {
        setWatchlists(data);
      })
      .catch(console.error);
  }, [setWatchlists]);

  useEffect(() => {
    const timers = configSaveTimerRef.current;
    return () => {
      Object.values(timers).forEach((timer) => {
        if (timer) clearTimeout(timer);
      });
    };
  }, []);

  const handleWatchlistChange = (key: string, checked: boolean) => {
    const newCols = checked
      ? [...watchlistCols, key]
      : watchlistCols.filter((c) => c !== key);
    setWatchlistCols(newCols);
  };

  const handleMoversChange = (key: string, checked: boolean) => {
    const newCols = checked
      ? [...moversCols, key]
      : moversCols.filter((c) => c !== key);
    setMoversCols(newCols);
  };

  const handlePanelCountChange = (count: PanelCount) => {
    setPanelCount(count);
    setPanelSizes(null);
  };

  const handleNotifConfigChange = (key: NotifConfigKey, value: string) => {
    setNotifConfig((current) => ({ ...current, [key]: value }));
    if (!configLoading) {
      scheduleNotifConfigSave(key, value);
    }
  };

  const handleDeleteWatchlist = async (id: number, name: string) => {
    if (!confirm(`Delete watchlist "${name}"? All items will be deleted.`)) return;
    try {
      const res = await fetch(`/api/watchlists/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Failed to delete watchlist');
        return;
      }
      // Refresh watchlists
      const data = await fetch('/api/watchlists').then(r => r.json()) as Watchlist[];
      setWatchlists(data);
      // Switch to default if current was deleted
      if (activeWatchlistId === id) {
        setActiveWatchlistId(1);
      }
      void qc.invalidateQueries({ queryKey: ['watchlist'] });
    } catch (err) {
      console.error('Failed to delete watchlist:', err);
      alert('Failed to delete watchlist');
    }
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto p-3 gap-4">
      <div className="text-terminal-amber font-bold text-sm border-b border-terminal-gray pb-1">
        SETTINGS
      </div>

      {/* Window Layout */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Window Layout
        </div>
        <div className="flex flex-wrap gap-2">
          {[2, 4, 6, 8].map((count) => {
            const isActive = panelCount === count;
            return (
              <button
                key={count}
                onClick={() => handlePanelCountChange(count as PanelCount)}
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
        <div className="text-white text-[10px]">
          Layout changes reset panel sizes.
        </div>
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
        <div className="text-white text-[10px]">
          OpenAlgo URL: {process.env.NEXT_PUBLIC_OPENALGO_URL ?? 'http://localhost:5000'}
        </div>
        <div className="text-white text-[10px]">
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
                <span className="text-white">{label}:</span>
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
        <ColumnCheckboxes
          columns={WATCHLIST_COLUMNS}
          selected={watchlistCols}
          onChange={handleWatchlistChange}
        />
      </div>

      {/* Movers Columns */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Movers Columns
        </div>
        <ColumnCheckboxes
          columns={MOVERS_COLUMNS}
          selected={moversCols}
          onChange={handleMoversChange}
        />
      </div>

      {/* Notification Thresholds */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Notification Thresholds
        </div>
        {configLoading ? (
          <div className="text-white">Loading...</div>
        ) : (
          <ThresholdInputs
            values={notifConfig}
            onChange={handleNotifConfigChange}
            disabled={configLoading}
          />
        )}
      </div>

      {/* Watchlists Management */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Watchlists
        </div>
        <div className="flex flex-col gap-0.5">
          {watchlists.map((wl) => (
            <div key={wl.id} className="flex items-center justify-between gap-2">
              <span className="text-white">
                {wl.name}
                {activeWatchlistId === wl.id && (
                  <span className="ml-1 text-terminal-green text-[9px]">●</span>
                )}
              </span>
              {wl.id !== 1 && (
                <button
                  onClick={() => handleDeleteWatchlist(wl.id, wl.name)}
                  className="text-terminal-red hover:text-red-400 text-xs font-bold px-1"
                  title="Delete watchlist"
                >
                  ✕
                </button>
              )}
              {wl.id === 1 && (
                <span className="text-white/40 text-[9px]">default</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Links */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Links
        </div>
        <Link
          href="/jobs"
          className="text-white hover:text-terminal-amber text-[10px] transition-colors"
        >
          → Jobs (background tasks)
        </Link>
      </div>

      {/* Tips */}
      <div className="flex flex-col gap-0.5 mt-auto">
        <div className="text-white text-[10px] border-t border-terminal-gray pt-2">
          Commands: CHART · WATCH · ORDER · POS · TOP · SETTINGS · FDM · DEALS · LARGEDEALS · BREAKOUTS · NEWS · ANALYSIS
        </div>
        <div className="text-white text-[10px]">
          Press / or Escape to focus command bar
        </div>
        <div className="text-white text-[10px]">
          F1 = BUY · F2 = SELL (in ORDER widget)
        </div>
        {appVersion && (
          <div className="text-white/40 text-[10px] mt-1">
            v{appVersion}
          </div>
        )}
      </div>
    </div>
  );
}
