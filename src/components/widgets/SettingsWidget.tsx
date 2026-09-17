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
  tickerSourceAtom,
  panelCountAtom,
  panelSizesAtom,
  selectedPanelsAtom,
  mergedGroupsAtom,
  authAtom,
  savedLayoutsAtom,
  layoutSyncStatusAtom,
  layoutToastAtom,
  advancedScrapingConsentAtom,
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
import { AI_PROVIDERS, AI_PROVIDER_MAP } from '@/lib/aiProviders';
import { AiProviderInstructions } from '@/components/AiProviderInstructions';

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
          <span className="text-white/70 text-[10px]">{col.label}</span>
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
          <span className="text-white/40 text-[9px] leading-snug">
            {NOTIF_CONFIG_HELP[key]}
          </span>
        </label>
      ))}
    </div>
  );
}

// Plain-language explanation for every scan threshold.
const NOTIF_CONFIG_HELP: Record<NotifConfigKey, string> = {
  'notif.rsi_oversold_threshold': 'Alert when RSI falls below this level (oversold bounce watch).',
  'notif.rsi_overbought_threshold': 'Alert when RSI rises above this level (pullback watch).',
  'notif.volatility_spike_ratio': 'Alert when the day range exceeds this multiple of its recent average.',
  'notif.atr_expansion_threshold': 'Alert when ATR expands past this multiple of baseline (volatility regime change).',
  'notif.momentum_surge_threshold': 'Alert when the momentum score crosses above this level.',
  'notif.return_1w_spike_threshold': 'Alert when the 1-week return exceeds this percent.',
  'notif.streak_days_threshold': 'Alert after this many consecutive up or down days.',
  'notif.near_52w_threshold': 'Alert when price trades within this % of the 52-week high or low.',
  'notif.deal_significance_pct': 'Bulk/block deals above this fraction of market cap trigger alerts (0.05 = 5%).',
  'notif.deal_absolute_threshold_cr': '…or above this ₹ Cr value when market cap is unknown.',
};

// Partition group: eyebrow label + hairline rule + sections.
function Group({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <div id={id} className="flex flex-col gap-2 scroll-mt-24">
      <div className="flex items-center gap-2">
        <span className="text-white/35 text-[10px] font-bold uppercase tracking-[0.25em]">
          {title}
        </span>
        <div className="flex-1 border-t border-terminal-border" />
      </div>
      {children}
    </div>
  );
}

// Collapsible settings section card: icon + title + optional status badge,
// one-line description, then the controls.
function Section({
  icon,
  title,
  blurb,
  badge,
  defaultOpen = true,
  children,
}: {
  icon: string;
  title: string;
  blurb?: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border border-terminal-border bg-terminal-panel">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-white/[0.03] transition-colors text-left"
      >
        <span className="text-terminal-amber text-xs w-4 text-center shrink-0">{icon}</span>
        <span className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest">
          {title}
        </span>
        {badge && <span className="ml-1 flex items-center">{badge}</span>}
        <span className={`text-white/40 text-[10px] ${badge ? '' : 'ml-auto'}`}>
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open && blurb && (
        <p className="px-2 pb-1.5 text-white/50 text-[10px] leading-relaxed">{blurb}</p>
      )}
      {open && <div className="px-2 pb-2 flex flex-col gap-2">{children}</div>}
    </section>
  );
}

const SETTINGS_INDEX = [
  { id: 'sec-workspace', label: 'Workspace' },
  { id: 'sec-connections', label: 'Connections' },
  { id: 'sec-intelligence', label: 'Intelligence' },
  { id: 'sec-automation', label: 'Automation' },
  { id: 'sec-system', label: 'System' },
];

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
  const [tickerSource, setTickerSource] = useAtom(tickerSourceAtom);
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
  const [aiProvider, setAiProvider] = useState('zen-free');
  const [aiZenApiKeyInput, setAiZenApiKeyInput] = useState('');
  const [aiGoApiKeyInput, setAiGoApiKeyInput] = useState('');
  const [aiAistudioApiKeyInput, setAiAistudioApiKeyInput] = useState('');
  const [aiGroqApiKeyInput, setAiGroqApiKeyInput] = useState('');
  const [aiNvidiaApiKeyInput, setAiNvidiaApiKeyInput] = useState('');
  const [aiAnthropicApiKeyInput, setAiAnthropicApiKeyInput] = useState('');
  const [aiClaudeCodeTokenInput, setAiClaudeCodeTokenInput] = useState('');
  const [aiOpenaiApiKeyInput, setAiOpenaiApiKeyInput] = useState('');
  const [aiOpenrouterApiKeyInput, setAiOpenrouterApiKeyInput] = useState('');
  const [aiDeepseekApiKeyInput, setAiDeepseekApiKeyInput] = useState('');
  const [aiXaiApiKeyInput, setAiXaiApiKeyInput] = useState('');
  const [aiTogetherApiKeyInput, setAiTogetherApiKeyInput] = useState('');
  const [aiCopilotGhTokenInput, setAiCopilotGhTokenInput] = useState('');
  const [aiHunterModel, setAiHunterModel] = useState('');
  const [aiVerifierModel, setAiVerifierModel] = useState('');
  const [aiAvailableModels, setAiAvailableModels] = useState<{id: string, label: string}[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  // Codex (ChatGPT subscription) device-code login state
  const [codexLogin, setCodexLogin] = useState<{device_auth_id: string, user_code: string, verification_url: string, interval?: number} | null>(null);
  const [codexStatus, setCodexStatus] = useState<{logged_in: boolean} | null>(null);
  
  // OTA Updater state
  const [updaterStatus, setUpdaterStatus] = useState<string>('');
  const [updaterProgress, setUpdaterProgress] = useState<{ percent: number } | null>(null);
  const [updateReady, setUpdateReady] = useState(false);

  // Advanced Web Extraction / Scraping Consent
  const [scrapingConsent, setScrapingConsent] = useAtom(advancedScrapingConsentAtom);
  const [consentSyncStatus, setConsentSyncStatus] = useState<string | null>(null);

  const handleUpdateConsent = async (val: boolean) => {
    setScrapingConsent(val);
    try {
      setConsentSyncStatus('Updating...');
      await fetch('/api/py/system_config/consent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ consent: val }),
      });
      setConsentSyncStatus(val ? 'Advanced Extraction Enabled' : 'Safe Mode Enabled');
      setTimeout(() => setConsentSyncStatus(null), 3000);
    } catch (e) {
      console.error('Failed to sync consent:', e);
      setConsentSyncStatus('Error syncing setting');
      setTimeout(() => setConsentSyncStatus(null), 3000);
    }
  };

  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI) {
      window.electronAPI.getAppVersion?.().then((ver) => {
        if (ver) setAppVersion(ver);
      }).catch(() => {});

      window.electronAPI.onUpdaterMessage((msg) => {
        setUpdaterStatus(msg.status);
        if (msg.status === 'progress' && msg.data) {
          setUpdaterProgress(msg.data as { percent: number });
        } else if (msg.status === 'downloaded') {
          setUpdateReady(true);
        }
      });
    }
  }, []);

  const handleCheckForUpdates = () => {
    if (window.electronAPI) {
      setUpdaterStatus('checking');
      window.electronAPI.checkForUpdates();
    }
  };

  const handleInstallUpdate = () => {
    if (window.electronAPI) {
      window.electronAPI.installUpdate();
    }
  };

  const [apiKeySaveStatus, setApiKeySaveStatus] = useState<string | null>(null);
  const [aiAuthStatus, setAiAuthStatus] = useState<{provider: string, is_configured: boolean} | null>(null);

  useEffect(() => {
    fetch('/api/py/ai/status')
      .then(r => r.json())
      .then(d => setAiAuthStatus(d))
      .catch(console.error);
  }, []);

  const refreshCodexStatus = () => {
    fetch('/api/py/auth/codex/status')
      .then(r => r.json())
      .then(d => setCodexStatus(d))
      .catch(console.error);
  };

  useEffect(() => {
    refreshCodexStatus();
  }, []);

  const handleCodexLoginStart = () => {
    fetch('/api/py/auth/codex/login/start', { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        if (d.error) {
          setApiKeySaveStatus('Codex login failed: ' + d.error);
          return;
        }
        setCodexLogin(d);
        setApiKeySaveStatus('Enter the code in your browser, then wait…');
        const intervalMs = Math.max(3, Number(d.interval) || 5) * 1000;
        // Device codes expire (~15 min) — stop polling then and ask to restart.
        const deadline = Date.now() + 15 * 60 * 1000;
        const interval = setInterval(() => {
          if (Date.now() > deadline) {
            clearInterval(interval);
            setCodexLogin(null);
            setApiKeySaveStatus('Codex code expired — click Sign in again for a fresh code.');
            return;
          }
          fetch(`/api/py/auth/codex/login/poll?device_auth_id=${encodeURIComponent(d.device_auth_id)}&user_code=${encodeURIComponent(d.user_code)}`)
            .then(r => r.json())
            .then(st => {
              if (st.status === 'complete') {
                clearInterval(interval);
                setCodexLogin(null);
                setApiKeySaveStatus('Codex Auth Successful!');
                setTimeout(() => setApiKeySaveStatus(null), 3000);
                refreshCodexStatus();
                fetch('/api/py/system-config/ai.provider', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: 'codex' }) }).then(() => {
                  setAiProvider('codex');
                  fetch('/api/py/ai/status').then(r => r.json()).then(s => setAiAuthStatus(s));
                });
              } else if (st.status === 'error') {
                clearInterval(interval);
                setCodexLogin(null);
                setApiKeySaveStatus('Codex login failed: ' + (st.error || 'unknown error'));
              }
            })
            .catch(() => {});
        }, intervalMs);
      })
      .catch(err => setApiKeySaveStatus('Failed to initiate Codex login: ' + err));
  };

  const handleCodexLogout = () => {
    fetch('/api/py/auth/codex/logout', { method: 'POST' })
      .then(() => {
        refreshCodexStatus();
        fetch('/api/py/ai/status').then(r => r.json()).then(s => setAiAuthStatus(s));
      })
      .catch(console.error);
  };



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
          setAppVersion((prev) => prev || (data['app.version'] as string));
        }
        if (typeof data['openalgo.url'] === 'string') {
          setOpenAlgoUrlInput(data['openalgo.url']);
        }
        if (typeof data['openalgo.api_key'] === 'string') {
          setOpenAlgoApiKeyInput(data['openalgo.api_key']);
        }
        if (typeof data['ai.provider'] === 'string') {
          const stored = data['ai.provider'] as string;
          // Migrate legacy "zen": paid when a key is stored, else free.
          if (stored === 'zen') {
            const hasKey = typeof data['ai.zen_api_key'] === 'string' && (data['ai.zen_api_key'] as string).trim() !== '';
            setAiProvider(hasKey ? 'zen-paid' : 'zen-free');
          } else {
            setAiProvider(stored);
          }
        }
        if (typeof data['ai.zen_api_key'] === 'string') setAiZenApiKeyInput(data['ai.zen_api_key']);
        if (typeof data['ai.go_api_key'] === 'string') setAiGoApiKeyInput(data['ai.go_api_key']);
        if (typeof data['ai.aistudio_api_key'] === 'string') setAiAistudioApiKeyInput(data['ai.aistudio_api_key']);
        if (typeof data['ai.groq_api_key'] === 'string') setAiGroqApiKeyInput(data['ai.groq_api_key']);
        if (typeof data['ai.nvidia_api_key'] === 'string') setAiNvidiaApiKeyInput(data['ai.nvidia_api_key']);
        if (typeof data['ai.anthropic_api_key'] === 'string') setAiAnthropicApiKeyInput(data['ai.anthropic_api_key']);
        if (typeof data['ai.claude_code_token'] === 'string') setAiClaudeCodeTokenInput(data['ai.claude_code_token']);
        if (typeof data['ai.openai_api_key'] === 'string') setAiOpenaiApiKeyInput(data['ai.openai_api_key']);
        if (typeof data['ai.openrouter_api_key'] === 'string') setAiOpenrouterApiKeyInput(data['ai.openrouter_api_key']);
        if (typeof data['ai.deepseek_api_key'] === 'string') setAiDeepseekApiKeyInput(data['ai.deepseek_api_key']);
        if (typeof data['ai.xai_api_key'] === 'string') setAiXaiApiKeyInput(data['ai.xai_api_key']);
        if (typeof data['ai.together_api_key'] === 'string') setAiTogetherApiKeyInput(data['ai.together_api_key']);
        if (typeof data['ai.copilot_gh_token'] === 'string') setAiCopilotGhTokenInput(data['ai.copilot_gh_token']);
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


  // Data-driven map: provider id -> credential input binding.
  // Labels/placeholders/hints/DB slots come from the shared aiProviders meta;
  // OAuth/subscription providers (gemini, codex) and zen-free need no key.
  const aiKeyStates: Record<string, { value: string; set: (v: string) => void }> = {
    'zen-paid': { value: aiZenApiKeyInput, set: setAiZenApiKeyInput },
    'go': { value: aiGoApiKeyInput, set: setAiGoApiKeyInput },
    'aistudio': { value: aiAistudioApiKeyInput, set: setAiAistudioApiKeyInput },
    'groq': { value: aiGroqApiKeyInput, set: setAiGroqApiKeyInput },
    'nvidia': { value: aiNvidiaApiKeyInput, set: setAiNvidiaApiKeyInput },
    'anthropic': { value: aiAnthropicApiKeyInput, set: setAiAnthropicApiKeyInput },
    'claude-code': { value: aiClaudeCodeTokenInput, set: setAiClaudeCodeTokenInput },
    'openai': { value: aiOpenaiApiKeyInput, set: setAiOpenaiApiKeyInput },
    'openrouter': { value: aiOpenrouterApiKeyInput, set: setAiOpenrouterApiKeyInput },
    'deepseek': { value: aiDeepseekApiKeyInput, set: setAiDeepseekApiKeyInput },
    'xai': { value: aiXaiApiKeyInput, set: setAiXaiApiKeyInput },
    'together': { value: aiTogetherApiKeyInput, set: setAiTogetherApiKeyInput },
    'copilot': { value: aiCopilotGhTokenInput, set: setAiCopilotGhTokenInput },
  };
  const aiKeyBindings: Record<string, { value: string; set: (v: string) => void; dbKey: string; label: string; placeholder: string; hint?: string }> = Object.fromEntries(
    Object.entries(aiKeyStates).map(([id, s]) => {
      const meta = AI_PROVIDER_MAP[id];
      return [id, { ...s, dbKey: meta?.credentialDbKey ?? '', label: meta?.credentialLabel ?? id, placeholder: meta?.placeholder ?? '', hint: meta?.hint }];
    }),
  );
  const activeKeyBinding = aiKeyBindings[aiProvider];

  useEffect(() => {
    const key = activeKeyBinding?.value ?? '';

    if (aiProvider !== 'gemini' && aiProvider !== 'zen-free' && aiProvider !== 'codex' && !key) {
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
  }, [aiProvider, aiZenApiKeyInput, aiGoApiKeyInput, aiAistudioApiKeyInput, aiGroqApiKeyInput, aiNvidiaApiKeyInput, aiAnthropicApiKeyInput, aiClaudeCodeTokenInput, aiOpenaiApiKeyInput, aiOpenrouterApiKeyInput, aiDeepseekApiKeyInput, aiXaiApiKeyInput, aiTogetherApiKeyInput, aiCopilotGhTokenInput]);

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
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto p-3 gap-3">
      <div className="sticky top-0 z-10 -mx-3 -mt-3 px-3 pt-3 pb-2 bg-terminal-bg/95 backdrop-blur-sm border-b border-terminal-gray">
        <div className="flex items-center justify-between gap-2">
          <div className="text-terminal-amber font-bold text-sm">SETTINGS</div>
          {apiKeySaveStatus ? (
            <span className="text-[10px] text-terminal-green animate-pulse">{apiKeySaveStatus}</span>
          ) : (
            <span className="text-white/30 text-[10px]">Changes save automatically</span>
          )}
        </div>
        <div className="flex flex-wrap gap-1 mt-1.5">
          {SETTINGS_INDEX.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => scrollToSection(s.id)}
              className="px-2 py-0.5 text-[10px] uppercase tracking-wider border border-terminal-border text-white/60 hover:text-terminal-amber hover:border-terminal-amber transition-colors"
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <Group id="sec-workspace" title="Workspace">
      <Section
        icon="▦"
        title="Window Layout"
        blurb="How many panels share the screen. Switching counts resets panel sizes and merges."
      >
      {/* Window Layout */}
      <div className="flex flex-col gap-1" data-tour="layout-controls">
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
      </div>
      </Section>

      <Section
        icon="◉"
        title="Ticker Source"
        blurb="Feed for the scrolling ticker bar at the top of the terminal."
      >
      {/* Ticker Source */}
      <div className="flex flex-col gap-1">
        <select
          value={tickerSource}
          onChange={(e) => setTickerSource(e.target.value)}
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
      </Section>

      {/* Saved Layouts */}
      {Object.keys(savedLayouts).length > 0 && (
      <Section
        icon="❏"
        title="Saved Layouts"
        blurb="Named snapshots of your panel arrangement. Load one with :name in the command bar."
        badge={auth?.user ? (
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
        ) : undefined}
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
        </div>
      </Section>
      )}

      <Section
        icon="☰"
        title="Table Columns"
        blurb="Choose which columns appear in the Watch and Movers tables. Changes apply instantly."
      >
      {/* Watchlist Columns */}
      <div className="flex flex-col gap-1">
        <span className="text-white/60 text-[10px]">Watch table</span>
        <ColumnCheckboxes
          columns={WATCHLIST_COLUMNS}
          selected={watchlistCols}
          onChange={handleWatchlistChange}
        />
      </div>
      {/* Movers Columns */}
      <div className="flex flex-col gap-1">
        <span className="text-white/60 text-[10px]">Movers table</span>
        <ColumnCheckboxes
          columns={MOVERS_COLUMNS}
          selected={moversCols}
          onChange={handleMoversChange}
        />
      </div>
      </Section>
      </Group>

      <Group id="sec-connections" title="Connections">
      <Section
        icon="⇄"
        title="Market Connection"
        blurb="Live socket health for market data, plus the broker bridge endpoint."
      >
      {/* Connection Status */}
      <div className="flex flex-col gap-1">
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
      </Section>

      {openAlgoAvailable && funds && (
      <Section
        icon="₹"
        title="Account Funds"
        blurb="Live broker balances pulled via OpenAlgo. ORDER and POS use these for sizing and margin display."
      >
        <div className="flex flex-col gap-1">
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
      </Section>
      )}
      </Group>

      <Group id="sec-intelligence" title="Intelligence">
      <Section
        icon="◐"
        title="Data Extraction & Privacy"
        blurb="Controls whether the terminal may run headless browser automation to harvest deep fundamentals and premium news tokens. Safe Mode disables all external scraping."
        badge={(
          <span
            className={`text-[10px] px-1.5 py-0.5 font-mono ${
              scrapingConsent === true
                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                : scrapingConsent === null
                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
            }`}
          >
            {scrapingConsent === true ? 'Advanced Extraction Active' : scrapingConsent === null ? 'Consent Required' : 'Safe Mode (Anonymous)'}
          </span>
        )}
      >
      <div className="flex flex-col gap-1.5">
        <p className="text-[10px] text-white/60 leading-relaxed">
          When Advanced Extraction is enabled, the terminal operates generic headless automation on your behalf to harvest deep company fundamentals and premium news tokens. In Safe Mode, external scraping is disabled.
        </p>
        <div className="flex items-center gap-2 mt-1">
          <button
            type="button"
            onClick={() => handleUpdateConsent(false)}
            disabled={scrapingConsent !== true}
            className={`px-3 py-1 text-[11px] font-mono rounded border transition ${
              scrapingConsent !== true
                ? 'bg-zinc-800/60 text-zinc-500 border-zinc-700/50 cursor-not-allowed opacity-60'
                : 'bg-zinc-800 text-zinc-300 border-zinc-600 hover:bg-zinc-700 hover:text-white cursor-pointer'
            }`}
          >
            Disable (Safe Mode)
          </button>
          <button
            type="button"
            onClick={() => handleUpdateConsent(true)}
            disabled={scrapingConsent === true}
            className={`px-3 py-1 text-[11px] font-mono rounded border transition ${
              scrapingConsent === true
                ? 'bg-zinc-800/60 text-zinc-500 border-zinc-700/50 cursor-not-allowed opacity-60'
                : 'bg-blue-600 text-white border-blue-500 hover:bg-blue-500 cursor-pointer font-semibold shadow-sm'
            }`}
          >
            Enable Advanced Extraction
          </button>
        </div>
        {consentSyncStatus && (
          <div className="text-[10px] text-terminal-amber animate-pulse mt-0.5">
            {consentSyncStatus}
          </div>
        )}
      </div>
      </Section>

      {auth?.user?.is_admin && (
      <>
      <Section
        icon="⌁"
        title="OpenAlgo Configuration"
        blurb="Order-execution bridge. The URL points at your local OpenAlgo server; the key authenticates this terminal. Used by ORDER and POS."
      >
          {/* OpenAlgo Section */}
          <div className="flex flex-col gap-2">
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
                <span className="text-white/50 text-[10px]">Address of your local OpenAlgo server (order-execution bridge).</span>
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
                <span className="text-white/50 text-[10px]">From your OpenAlgo server config — authenticates order placement.</span>
              </label>
              
            </div>
          </div>
      </Section>

      <Section
        icon="✦"
        title="AI Provider"
        blurb="Engine behind AI chat, background picks and summaries. Keys save automatically as you type."
        badge={aiAuthStatus ? (
          <span className={aiAuthStatus.is_configured ? 'text-[10px] text-terminal-green' : 'text-[10px] text-terminal-red'}>
            {aiAuthStatus.is_configured ? '✅ Connected' : '❌ Not Connected'}
          </span>
        ) : undefined}
      >
          {/* AI Provider Section */}
          <div className="flex flex-col gap-2">
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
                  {AI_PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id}>{p.label}</option>
                  ))}
                </select>
              </label>

              {aiProvider === 'gemini' ? (
                <div className="flex flex-col gap-1 mt-1">
                  <span className="text-white/70 text-[10px]">Use your existing Google subscription via the Google Antigravity proxy — no API key needed.</span>
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
              ) : aiProvider === 'zen-free' ? (
                <span className="text-green-300/80 text-[10px]">No API key required — free models available immediately.</span>
              ) : aiProvider === 'codex' ? (
                <div className="flex flex-col gap-1 mt-1">
                  <span className="text-white/70 text-[10px]">Use your ChatGPT Plus/Pro subscription via the Codex backend — no API key needed.</span>
                  {codexStatus?.logged_in ? (
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-terminal-green text-[10px]">✅ Signed in to Codex</span>
                      <button
                        type="button"
                        onClick={handleCodexLogout}
                        className="px-2 py-0.5 border border-terminal-border text-white/70 hover:text-white text-[10px] uppercase transition-colors"
                      >
                        Sign out
                      </button>
                    </div>
                  ) : codexLogin ? (
                    <div className="flex flex-col gap-1 mt-1 border border-terminal-border p-2">
                      <span className="text-white/70 text-[10px]">1. Open this URL in your browser:</span>
                      <a href={codexLogin.verification_url} target="_blank" rel="noreferrer" className="text-terminal-amber text-[10px] underline break-all">
                        {codexLogin.verification_url}
                      </a>
                      <span className="text-white/70 text-[10px]">2. Enter this code:</span>
                      <span className="text-white font-mono text-lg font-bold tracking-widest">{codexLogin.user_code}</span>
                      <span className="text-white/50 text-[10px] animate-pulse">Waiting for sign-in…</span>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={handleCodexLoginStart}
                      className="px-3 py-1 bg-terminal-amber/20 border border-terminal-amber text-terminal-amber hover:bg-terminal-amber hover:text-black font-bold text-xs uppercase transition-colors self-start"
                    >
                      Sign in with ChatGPT
                    </button>
                  )}
                </div>
              ) : activeKeyBinding ? (
                <label className="flex flex-col gap-0.5">
                  <span className="text-white/70 text-[10px]">{activeKeyBinding.label}:</span>
                  <input
                    type="password"
                    value={activeKeyBinding.value}
                    onChange={(e) => {
                      activeKeyBinding.set(e.target.value);
                      scheduleSystemConfigSave(activeKeyBinding.dbKey, e.target.value);
                    }}
                    placeholder={activeKeyBinding.placeholder}
                    className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                  />
                  {activeKeyBinding.hint && (
                    <span className="text-white/50 text-[10px]">{activeKeyBinding.hint}</span>
                  )}
                </label>
              ) : null}

              <AiProviderInstructions providerId={aiProvider} />

              
            </div>
          </div>
      </Section>

      <Section
        icon="◇"
        title="Background Worker Models"
        blurb="Models for the background AI-picks worker. The hunter scans the market; the verifier double-checks. Applies to future runs."
      >
          {/* AI Models Section */}
          <div className={`flex flex-col gap-2 ${!aiAuthStatus?.is_configured ? 'opacity-50 pointer-events-none' : ''}`}>
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
                <span className="text-white/50 text-[10px]">Scans the market for opportunities — pick a smarter, more capable model.</span>
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
                <span className="text-white/50 text-[10px]">Double-checks the hunter's picks — a faster, less capable model is fine.</span>
              </label>

              
            </div>
          </div>
      </Section>
      </>
      )}
      </Group>

      <Group id="sec-automation" title="Automation">
      {auth?.user?.is_admin && (
      <Section
        icon="⚙"
        title="Global Scan Settings"
        blurb="Thresholds that trigger scanner alerts and notifications. Each field auto-saves and applies to future scans. Admin only."
      >
        <div className="flex flex-col gap-1">
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
      </Section>
      )}
      </Group>

      <Group id="sec-system" title="System">
      <Section
        icon="▤"
        title="Watchlists"
        blurb="Your symbol lists. The default list cannot be deleted. ● marks the active list."
      >
      {/* Watchlists Management */}
      <div className="flex flex-col gap-1">
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
      </Section>

      {auth?.user?.is_admin && (
      <Section icon="⧉" title="Links" blurb="Jump to background task monitoring.">
      {/* Links (Admin Only) */}
      <div className="flex flex-col gap-1">
          <Link
            href="/jobs"
            className="text-white hover:text-terminal-amber text-[10px] transition-colors"
          >
            → Jobs (background tasks)
          </Link>
        </div>
      </Section>
      )}

      <Section
        icon="⌨"
        title="Updates & Shortcuts"
        defaultOpen={false}
        blurb="Desktop updater and command-bar reference."
      >
      {/* Tips */}
      <div className="flex flex-col gap-0.5 mt-auto">
        
        {typeof window !== 'undefined' && window.electronAPI && (
          <div className="border-t border-terminal-gray pt-2 mt-2 mb-2 flex flex-col items-start gap-2">
            <div className="flex items-center gap-2">
              <button
                onClick={handleCheckForUpdates}
                className="px-2 py-1 text-[10px] bg-terminal-amber text-terminal-bg font-bold"
              >
                CHECK FOR UPDATES
              </button>
              {updaterStatus && (
                <span className="text-[10px] text-white/60">
                  {updaterStatus === 'checking' && 'Checking...'}
                  {updaterStatus === 'available' && 'Update available! Prompt shown.'}
                  {updaterStatus === 'not-available' && 'App is up to date'}
                  {updaterStatus === 'error' && 'Update check failed'}
                  {updaterStatus === 'progress' && updaterProgress && `Downloading: ${Math.round(updaterProgress.percent)}%`}
                  {updaterStatus === 'downloaded' && 'Update downloaded & ready'}
                </span>
              )}
            </div>
            {updateReady && (
              <button
                onClick={handleInstallUpdate}
                className="px-2 py-1 text-[10px] bg-terminal-green text-terminal-bg font-bold animate-pulse"
              >
                INSTALL & RESTART
              </button>
            )}
          </div>
        )}

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
      </Section>
      </Group>
    </div>
  );
}
