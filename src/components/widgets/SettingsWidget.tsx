'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import Link from 'next/link';
import {
  wsConnectedAtom,
  fundsAtom,
  openAlgoAvailableAtom,
  watchlistColumnsAtom,
  moversColumnsAtom,
  watchlistsAtom,
  activeWatchlistIdAtom,
  panelCountAtom,
  panelSizesAtom,
  selectedPanelsAtom,
  mergedGroupsAtom,
  authAtom,
  savedLayoutsAtom,
  layoutSyncStatusAtom,
  layoutToastAtom,
  type Watchlist,
  type PanelCount,
  type SavedLayout,
} from '@/store/terminalStore';
import {
  enqueueQueueOperation,
  updateAndPersistLayouts,
  normalizeRenameNameWithFlag,
} from '@/lib/layouts';
import { useSavedLayoutsSync } from '@/hooks/useSavedLayoutsSync';

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
  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);
  const [watchlistCols, setWatchlistCols] = useAtom(watchlistColumnsAtom);
  const [moversCols, setMoversCols] = useAtom(moversColumnsAtom);
  const [watchlists, setWatchlists] = useAtom(watchlistsAtom);
  const [activeWatchlistId, setActiveWatchlistId] = useAtom(activeWatchlistIdAtom);
  const [panelCount, setPanelCount] = useAtom(panelCountAtom);
  const [, setPanelSizes] = useAtom(panelSizesAtom);
  const [, setSelectedPanels] = useAtom(selectedPanelsAtom);
  const [, setMergedGroups] = useAtom(mergedGroupsAtom);
  const [auth] = useAtom(authAtom);
  const [savedLayouts, setSavedLayouts] = useAtom(savedLayoutsAtom);
  const [syncStatus] = useAtom(layoutSyncStatusAtom);
  const setLayoutToast = useSetAtom(layoutToastAtom);
  const { processPendingQueue } = useSavedLayoutsSync();
  const [notifConfig, setNotifConfig] = useState<NotifConfigState>(DEFAULT_NOTIF_CONFIG);
  const [appVersion, setAppVersion] = useState<string>('');
  const [renamingLayout, setRenamingLayout] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');


  // Runtime API Keys state
  const [openAlgoUrlInput, setOpenAlgoUrlInput] = useState('');
  const [openAlgoApiKeyInput, setOpenAlgoApiKeyInput] = useState('');
  
  // AI Settings
  const [aiProvider, setAiProvider] = useState('zen');
  const [aiZenApiKeyInput, setAiZenApiKeyInput] = useState('');
  const [aiGoApiKeyInput, setAiGoApiKeyInput] = useState('');
  const [aiHunterModel, setAiHunterModel] = useState('');
  const [aiVerifierModel, setAiVerifierModel] = useState('');
  const [aiAvailableModels, setAiAvailableModels] = useState<{id: string, label: string}[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  

  const [apiKeySaveStatus, setApiKeySaveStatus] = useState<string | null>(null);
  const [aiAuthStatus, setAiAuthStatus] = useState<{provider: string, is_configured: boolean} | null>(null);

  useEffect(() => {
    fetch('/api/py/ai/status')
      .then(r => r.json())
      .then(d => setAiAuthStatus(d))
      .catch(console.error);
  }, []);



  const [configLoading, setConfigLoading] = useState(true);


  const systemConfigSaveTimerRef = useRef<Record<string, NodeJS.Timeout>>({});

  const scheduleSystemConfigSave = (key: string, value: string) => {
    const existingTimer = systemConfigSaveTimerRef.current[key];
    if (existingTimer) clearTimeout(existingTimer);
    systemConfigSaveTimerRef.current[key] = setTimeout(() => {
      fetch(`/api/py/system-config/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      }).then(() => {
        setApiKeySaveStatus('Saved');
        setTimeout(() => setApiKeySaveStatus(null), 2000);
        // Specifically for AI provider settings, refresh status
        if (key.startsWith('ai.')) {
          fetch('/api/py/ai/status').then(r => r.json()).then(d => setAiAuthStatus(d));
        }
      }).catch(console.error);
    }, 500);
  };

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
      .then((data: Record<string, unknown>) => {
        setNotifConfig((current) => ({
          ...current,
          ...Object.fromEntries(
            NOTIF_CONFIG_KEYS.map((key) => [
              key,
              data[key] !== undefined ? String(data[key]) : current[key],
            ]),
          ),
        }));
        if (typeof data['app.version'] === 'string') {
          setAppVersion(data['app.version']);
        }
        if (typeof data['openalgo.url'] === 'string') {
          setOpenAlgoUrlInput(data['openalgo.url']);
        }
        if (typeof data['openalgo.api_key'] === 'string') {
          setOpenAlgoApiKeyInput(data['openalgo.api_key']);
        }
        if (typeof data['ai.provider'] === 'string') setAiProvider(data['ai.provider']);
        if (typeof data['ai.zen_api_key'] === 'string') setAiZenApiKeyInput(data['ai.zen_api_key']);
        if (typeof data['ai.go_api_key'] === 'string') setAiGoApiKeyInput(data['ai.go_api_key']);
        if (typeof data['ai.hunter_model'] === 'string') setAiHunterModel(data['ai.hunter_model']);
        if (typeof data['ai.verifier_model'] === 'string') setAiVerifierModel(data['ai.verifier_model']);
      })
      .catch(console.error)
      .finally(() => setConfigLoading(false));
  }, []);

  // Fetch watchlists via React Query (shared cache with WatchWidget)
  useQuery({
    queryKey: ['watchlists'],
    queryFn: async () => {
      const res = await fetch('/api/watchlists');
      if (!res.ok) throw new Error('Failed to fetch watchlists');
      const data = (await res.json()) as Watchlist[];
      setWatchlists(data);
      return data;
    },
    staleTime: 300_000,
  });

  useEffect(() => {
    const timers = configSaveTimerRef.current;
    return () => {
      Object.values(timers).forEach((timer) => {
        if (timer) clearTimeout(timer);
      });
    };
  }, []);


  useEffect(() => {
    let key = '';
    if (aiProvider === 'zen') key = aiZenApiKeyInput;
    if (aiProvider === 'go') key = aiGoApiKeyInput;
    
    if (aiProvider !== 'gemini' && !key) {
      setAiAvailableModels([{ id: '', label: `Enter ${aiProvider} API key to fetch models` }]);
      return;
    }

    setFetchingModels(true);
    fetch(`/api/py/ai/provider-models?provider=${aiProvider}&api_key=${encodeURIComponent(key)}`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) setAiAvailableModels(data);
      })
      .catch(console.error)
      .finally(() => setFetchingModels(false));
  }, [aiProvider, aiZenApiKeyInput, aiGoApiKeyInput]);

  const handleSaveApiKeys = async (e: React.FormEvent) => {

    e.preventDefault();
    setApiKeySaveStatus('Saving...');
    try {
        const updates = [
          { key: 'openalgo.url', value: openAlgoUrlInput },
          { key: 'openalgo.api_key', value: openAlgoApiKeyInput },
          { key: 'ai.provider', value: aiProvider },
          { key: 'ai.zen_api_key', value: aiZenApiKeyInput },
          { key: 'ai.go_api_key', value: aiGoApiKeyInput },
          { key: 'ai.hunter_model', value: aiHunterModel },
          { key: 'ai.verifier_model', value: aiVerifierModel },
        ];

      for (const item of updates) {
        await fetch(`/api/py/system-config/${item.key}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: item.value }),
        });
      }

      setApiKeySaveStatus('Saved successfully!');
      setTimeout(() => setApiKeySaveStatus(null), 3000);
    } catch {
      setApiKeySaveStatus('Failed to save API keys');
      setTimeout(() => setApiKeySaveStatus(null), 3000);
    }
  };

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
    setSelectedPanels([]);
    setMergedGroups({});
  };

  const handleDeleteLayout = (name: string) => {
    if (!confirm(`Delete layout "${name}"?`)) return;
    setSavedLayouts((prev) => {
      const next = { ...prev };
      delete next[name];
      if (auth?.user?.id) {
        updateAndPersistLayouts(auth.user.id, () => next);
      }
      return next;
    });

    // Enqueue exactly one delete operation; processPendingQueue will handle it
    if (auth?.user?.id) {
      const uId = auth.user.id;
      enqueueQueueOperation(uId, { type: 'delete', name });
      processPendingQueue(uId);
    }
  };

  const handleStartRename = (layout: SavedLayout) => {
    setRenamingLayout(layout.name);
    setRenameValue(layout.name);
  };

  const handleFinishRename = (oldName: string) => {
    const rawNewName = renameValue.trim();
    const { name: newName, wasShortened } = normalizeRenameNameWithFlag(
      rawNewName,
      Object.keys(savedLayouts),
      oldName
    );
    setRenamingLayout(null);
    
    if (!newName || newName === oldName || newName === 'save') return;
    
    if (wasShortened) {
      setLayoutToast({
        visible: true,
        message: `Name was shortened to: "${newName}"`,
        type: 'success',
      });
    }
    
    if (savedLayouts[newName]) {
      setLayoutToast({
        visible: true,
        message: `Layout "${newName}" already exists.`,
        type: 'error',
      });
      return;
    }

    // Get the original layout payload for rollback on conflict
    const originalLayout = savedLayouts[oldName];
    if (!originalLayout) return;

    setSavedLayouts((prev) => {
      const next = { ...prev };
      const layout = next[oldName];
      if (!layout) return prev;
      delete next[oldName];
      next[newName] = { ...layout, name: newName };
      if (auth?.user?.id) {
        updateAndPersistLayouts(auth.user.id, () => next);
      }
      return next;
    });

    // Enqueue exactly one rename operation with original payload for rollback
    if (auth?.user?.id) {
      const uId = auth.user.id;
      enqueueQueueOperation(uId, {
        type: 'rename',
        name: oldName,
        oldName,
        newName,
        payload: originalLayout, // Store original layout for rollback on conflict
      });
      processPendingQueue(uId);
    }
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
          Layout changes reset panel sizes and merges.
        </div>
      </div>

      {/* Saved Layouts */}
      {Object.keys(savedLayouts).length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
              Saved Layouts
            </div>
            {auth?.user && (
              <div
                className={`text-[9px] font-mono uppercase tracking-wider mb-1 ${
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
              </div>
            )}
          </div>
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
                        onClick={() => handleStartRename(layout)}
                        className="text-white/30 hover:text-terminal-amber text-xs transition-colors px-0.5"
                        title="Rename layout"
                      >
                        ✎
                      </button>
                      <button
                        onClick={() => handleDeleteLayout(layout.name)}
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
          <div className="text-white/30 text-[9px] mt-0.5">
            Load: type :<span className="text-terminal-amber/50">name</span> in command bar
          </div>
        </div>
      )}

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
            Market WS: {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
          </span>
        </div>
        {openAlgoAvailable && (
          <div className="text-white text-[10px]">
            OpenAlgo URL: {process.env.NEXT_PUBLIC_OPENALGO_URL ?? 'http://localhost:5000'}
          </div>
        )}
      </div>

      {/* Funds */}
      {openAlgoAvailable && funds && (
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

      {/* Runtime API Keys & Integrations */}
      {auth?.user?.is_admin && (
        <div className="flex flex-col gap-4 p-2 border border-terminal-border bg-terminal-panel">
          {/* OpenAlgo Section */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest">
                OpenAlgo Configuration
              </div>
            </div>
            <div className="flex flex-col gap-1.5 text-xs">
              <label className="flex flex-col gap-0.5">
                <span className="text-white/70 text-[10px]">OpenAlgo URL:</span>
                <input
                  type="text"
                  value={openAlgoUrlInput}
                  onChange={(e) => {
                  setOpenAlgoUrlInput(e.target.value);
                  scheduleSystemConfigSave('openalgo.url', e.target.value);
                }}
                  placeholder="http://127.0.0.1:5000"
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-white/70 text-[10px]">OpenAlgo API Key:</span>
                <input
                  type="password"
                  value={openAlgoApiKeyInput}
                  onChange={(e) => {
                  setOpenAlgoApiKeyInput(e.target.value);
                  scheduleSystemConfigSave('openalgo.api_key', e.target.value);
                }}
                  placeholder="Enter OpenAlgo API key"
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                />
              </label>
              
            </div>
          </div>

          <div className="border-b border-terminal-border" />

          {/* AI Provider Section */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest">
                AI Provider Configuration
              </div>
              {aiAuthStatus && (
                <span className={aiAuthStatus.is_configured ? "text-[10px] text-terminal-green" : "text-[10px] text-terminal-red"}>
                  {aiAuthStatus.is_configured ? "✅ Connected" : "❌ Not Connected"}
                </span>
              )}
            </div>
            
            <div className="flex flex-col gap-1.5 text-xs">
              <label className="flex flex-col gap-0.5">
                <span className="text-white/70 text-[10px]">Provider:</span>
                <select
                  value={aiProvider}
                  onChange={(e) => {
                  setAiProvider(e.target.value);
                  scheduleSystemConfigSave('ai.provider', e.target.value);
                }}
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                >
                  <option value="zen">OpenCode Zen</option>
                  <option value="go">OpenCode Go</option>
                  <option value="gemini">Google Gemini (Antigravity)</option>
                </select>
              </label>

              {aiProvider === 'gemini' ? (
                <div className="flex flex-col gap-1 mt-1">
                  <span className="text-white/70 text-[10px]">Gemini Authentication:</span>
                  <button
                    type="button"
                    onClick={() => {
                      fetch('/api/py/auth/gemini/login')
                        .then(r => r.json())
                        .then(d => {
                          if (d.auth_url) {
                            window.open(d.auth_url, '_blank');
                            setApiKeySaveStatus('Awaiting Google OAuth... Check your browser.');
                            const interval = setInterval(() => {
                              fetch('/api/py/auth/gemini/status').then(r => r.json()).then(st => {
                                if (st.configured && st.has_refresh_token) {
                                  clearInterval(interval);
                                  setApiKeySaveStatus('Gemini Auth Successful!');
                                  setTimeout(() => setApiKeySaveStatus(null), 3000);
                                  fetch('/api/py/system-config/ai.provider', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: 'gemini' }) }).then(() => {
                                      fetch('/api/py/ai/status').then(r => r.json()).then(d => setAiAuthStatus(d));
                                  });
                                }
                              });
                            }, 3000);
                          }
                        })
                        .catch(err => setApiKeySaveStatus('Failed to initiate login: ' + err));
                    }}
                    className="px-3 py-1 bg-terminal-amber/20 border border-terminal-amber text-terminal-amber hover:bg-terminal-amber hover:text-black font-bold text-xs uppercase transition-colors self-start"
                  >
                    Login to Gemini
                  </button>
                </div>
              ) : (
                <label className="flex flex-col gap-0.5">
                  <span className="text-white/70 text-[10px]">{aiProvider === 'zen' ? 'Zen' : 'Go'} API Key:</span>
                  <input
                    type="password"
                    value={aiProvider === 'zen' ? aiZenApiKeyInput : aiGoApiKeyInput}
                    onChange={(e) => {
                      if (aiProvider === 'zen') {
                        setAiZenApiKeyInput(e.target.value);
                        scheduleSystemConfigSave('ai.zen_api_key', e.target.value);
                      } else {
                        setAiGoApiKeyInput(e.target.value);
                        scheduleSystemConfigSave('ai.go_api_key', e.target.value);
                      }
                    }}
                    placeholder={`Enter ${aiProvider === 'zen' ? 'Zen' : 'Go'} API key`}
                    className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                  />
                </label>
              )}

              
            </div>
          </div>

          <div className="border-b border-terminal-border" />

          {/* AI Models Section */}
          <div className={`flex flex-col gap-2 ${!aiAuthStatus?.is_configured ? 'opacity-50 pointer-events-none' : ''}`}>
            <div className="flex items-center justify-between">
              <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest">
                Background Worker Models
              </div>
            </div>
            
            <div className="flex flex-col gap-1.5 text-xs">
              <label className="flex flex-col gap-0.5">
                <span className="text-white/70 text-[10px]">Hunter Model:</span>
                <select
                  value={aiHunterModel}
                  onChange={(e) => {
                  setAiHunterModel(e.target.value);
                  scheduleSystemConfigSave('ai.hunter_model', e.target.value);
                }}
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                >
                  <option value="">Default</option>
                  {aiAvailableModels.map(m => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </label>

              <label className="flex flex-col gap-0.5">
                <span className="text-white/70 text-[10px]">Verifier Model:</span>
                <select
                  value={aiVerifierModel}
                  onChange={(e) => {
                  setAiVerifierModel(e.target.value);
                  scheduleSystemConfigSave('ai.verifier_model', e.target.value);
                }}
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                >
                  <option value="">Default</option>
                  {aiAvailableModels.map(m => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </label>

              
            </div>
          </div>
          
          {apiKeySaveStatus && (
            <div className="text-[10px] text-terminal-green animate-pulse mt-2">
              {apiKeySaveStatus}
            </div>
          )}
        </div>
      )}
      {/* Notification Thresholds (Admin Only) */}
      {auth?.user?.is_admin && (
        <div className="flex flex-col gap-1">
          <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
            Global Scan Settings (Admin)
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
      )}

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

      {/* Links (Admin Only) */}
      {auth?.user?.is_admin && (
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
      )}

      {/* Tips */}
      <div className="flex flex-col gap-0.5 mt-auto">
        <div className="text-white text-[10px] border-t border-terminal-gray pt-2">
          Commands: CHART · WATCH · ORDER · POS · TOP · SETTINGS · FDM · DEALS · LARGEDEALS · BREAKOUTS · NEWS · ANALYSIS · PORTFOLIO
        </div>
        <div className="text-white text-[10px]">
          Layouts: :save &lt;name&gt; · :&lt;name&gt; to load
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
