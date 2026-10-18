'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import Link from 'next/link';
import { X, Settings as SettingsIcon } from 'lucide-react';
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
  showSettingsModalAtom,
  settingsModalTabAtom,
  type SettingsTabId,
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

// Bento UI Component - modeled directly after CompanyTabs/FundamentalsTab.tsx
function BentoCard({
  children,
  className = '',
  title,
  icon,
  badge,
  blurb,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
  icon?: string;
  badge?: React.ReactNode;
  blurb?: string;
}) {
  return (
    <div
      className={`bg-[#09090b] border border-[#27272a] rounded p-3 flex flex-col justify-between transition-colors duration-200 hover:bg-zinc-900/80 ${className}`}
    >
      <div className="flex flex-col gap-2">
        {(title || badge || icon) && (
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 min-w-0">
              {icon && (
                <span className="text-terminal-amber text-xs w-4 text-center shrink-0">
                  {icon}
                </span>
              )}
              {title && (
                <span className="text-[10px] uppercase font-mono tracking-wider text-zinc-400 font-semibold truncate">
                  {title}
                </span>
              )}
            </div>
            {badge && <div className="shrink-0 flex items-center">{badge}</div>}
          </div>
        )}
        {blurb && (
          <p className="text-white/50 text-[10px] leading-relaxed">{blurb}</p>
        )}
        <div className="flex flex-col gap-2">{children}</div>
      </div>
    </div>
  );
}

const SETTINGS_TABS: { id: SettingsTabId; label: string }[] = [
  { id: 'workspace', label: 'WORKSPACE' },
  { id: 'connections', label: 'CONNECTIONS' },
  { id: 'intelligence', label: 'INTELLIGENCE' },
  { id: 'automation', label: 'AUTOMATION' },
  { id: 'system', label: 'SYSTEM' },
];

export interface SettingsModalProps {
  isOpen?: boolean;
  onClose?: () => void;
  initialTab?: SettingsTabId;
}

export function SettingsModal({ isOpen: controlledIsOpen, onClose: controlledOnClose, initialTab }: SettingsModalProps = {}) {
  const [globalIsOpen, setGlobalIsOpen] = useAtom(showSettingsModalAtom);
  const [globalTab, setGlobalTab] = useAtom(settingsModalTabAtom);

  const isOpen = controlledIsOpen !== undefined ? controlledIsOpen : globalIsOpen;
  const handleClose = useCallback(() => {
    if (controlledOnClose) {
      controlledOnClose();
    } else {
      setGlobalIsOpen(false);
    }
  }, [controlledOnClose, setGlobalIsOpen]);

  const [activeTab, setActiveTab] = useState<SettingsTabId>(initialTab ?? globalTab ?? 'workspace');

  useEffect(() => {
    if (initialTab) {
      setActiveTab(initialTab);
    } else if (globalTab) {
      setActiveTab(globalTab);
    }
  }, [initialTab, globalTab, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleClose]);

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
  const [aiProvider, setAiProvider] = useState('aistudio');
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

  // Headless-browser provisioning status (provision-on-consent fetch).
  interface BrowserProvision {
    state: 'unknown' | 'ready' | 'missing' | 'downloading' | 'failed';
    downloaded: number;
    total: number;
    version: string | null;
    error: string | null;
  }
  const [browserProvision, setBrowserProvision] = useState<BrowserProvision | null>(null);
  const [browserFetchBusy, setBrowserFetchBusy] = useState(false);

  const refreshBrowserStatus = async () => {
    try {
      const res = await fetch('/api/py/system_config/browser-status', { credentials: 'include' });
      if (!res.ok) return false;
      const data = await res.json();
      setBrowserProvision({
        state: data.state ?? 'unknown',
        downloaded: data.downloaded ?? 0,
        total: data.total ?? 0,
        version: data.version ?? null,
        error: data.error ?? null,
      });
      return (data.state ?? 'unknown') === 'ready';
    } catch {
      /* backend cold — leave last known status */
      return false;
    }
  };

  const handleBrowserRetry = async () => {
    setBrowserFetchBusy(true);
    try {
      const res = await fetch('/api/py/system_config/browser-fetch', {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) {
        setConsentSyncStatus(`Browser fetch failed (HTTP ${res.status}) — will retry automatically`);
        setTimeout(() => setConsentSyncStatus(null), 5000);
      }
      await refreshBrowserStatus();
    } catch (e) {
      console.error('Failed to trigger browser fetch:', e);
      setConsentSyncStatus('Could not reach backend to start browser fetch');
      setTimeout(() => setConsentSyncStatus(null), 5000);
    } finally {
      setBrowserFetchBusy(false);
    }
  };

  // Poll provisioning status while consented and not yet ready. Stops on
  // `ready` so healthy clients don't poll the endpoint forever.
  useEffect(() => {
    if (scrapingConsent !== true) {
      setBrowserProvision(null);
      return;
    }
    let timer: ReturnType<typeof setInterval> | null = null;
    const poll = async () => {
      const ready = await refreshBrowserStatus();
      if (ready && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
    void poll();
    timer = setInterval(() => {
      void poll();
    }, 5000);
    return () => {
      if (timer !== null) clearInterval(timer);
    };
  }, [scrapingConsent]);

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
          // Migrate retired values to zen-paid (same key slot): legacy "zen"
          // and the retired "zen-free" (external free tier is gated).
          if (stored === 'zen' || stored === 'zen-free') {
            setAiProvider('zen-paid');
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
  // OAuth/subscription providers (gemini, codex) need no key.
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

    if (aiProvider !== 'gemini' && aiProvider !== 'codex' && !key) {
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


  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200 select-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div className="relative w-full max-w-5xl bg-[#09090b] border border-[#27272a] rounded-lg shadow-2xl flex flex-col max-h-[90vh] h-[85vh] overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#27272a] bg-[#121216] shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
              <SettingsIcon className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold tracking-wider text-white uppercase font-mono">
                  TERMINAL SETTINGS
                </h2>
              </div>
              <p className="text-[11px] text-zinc-400 font-sans">
                Configure workspace layouts, broker connections, AI models, and market alerts.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {apiKeySaveStatus ? (
              <span className="text-[10px] text-terminal-green animate-pulse">{apiKeySaveStatus}</span>
            ) : (
              <span className="text-white/30 text-[10px] hidden sm:inline">Changes save automatically</span>
            )}
            <button
              type="button"
              onClick={handleClose}
              aria-label="Close settings"
              className="p-1.5 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center border-b border-[#27272a] px-5 py-1 gap-1 shrink-0 bg-[#0c0c0f] flex-wrap">
          {SETTINGS_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => {
                setActiveTab(tab.id);
                setGlobalTab(tab.id);
              }}
              className={`px-3 py-1.5 text-xs font-mono transition-all duration-200 border rounded cursor-pointer ${
                activeTab === tab.id
                  ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/10 font-bold'
                  : 'border-transparent text-white/60 hover:text-white hover:bg-zinc-800/60'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Scrollable Tab Content / Bento Grid Body */}
        <div className="flex-1 overflow-y-auto p-4 bg-[#09090b] select-text">
          <div key={activeTab} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2.5 max-w-full animate-in fade-in duration-200">
          {/* TAB 1: WORKSPACE */}
          {activeTab === 'workspace' && (
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
              </BentoCard>

              {/* Saved Layouts */}
              {Object.keys(savedLayouts).length > 0 && (
                <BentoCard
                  icon="❏"
                  title="Saved Layouts"
                  blurb="Named snapshots of your panel arrangement. Load one with :name in the command bar."
                  badge={
                    auth?.user ? (
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
                </BentoCard>
              )}

              {/* Table Columns */}
              <BentoCard
                icon="☰"
                title="Table Columns"
                blurb="Choose which columns appear in the Watch and Movers tables. Changes apply instantly."
                className="col-span-1 md:col-span-2 lg:col-span-4"
              >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="flex flex-col gap-1.5 bg-black/30 border border-zinc-800/80 p-2.5 rounded">
                    <span className="text-terminal-amber text-[10px] uppercase tracking-wider font-semibold">Watch table</span>
                    <ColumnCheckboxes
                      columns={WATCHLIST_COLUMNS}
                      selected={watchlistCols}
                      onChange={handleWatchlistChange}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5 bg-black/30 border border-zinc-800/80 p-2.5 rounded">
                    <span className="text-terminal-amber text-[10px] uppercase tracking-wider font-semibold">Movers table</span>
                    <ColumnCheckboxes
                      columns={MOVERS_COLUMNS}
                      selected={moversCols}
                      onChange={handleMoversChange}
                    />
                  </div>
                </div>
              </BentoCard>
            </>
          )}

          {/* TAB 2: CONNECTIONS */}
          {activeTab === 'connections' && (
            <>
              {/* Market Connection */}
              <BentoCard
                icon="⇄"
                title="Market Connection"
                blurb="Live socket health for market data, plus the broker bridge endpoint."
                className="col-span-1 md:col-span-2 lg:col-span-2"
              >
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
              </BentoCard>

              {/* Account Funds */}
              {openAlgoAvailable && funds && (
                <BentoCard
                  icon="₹"
                  title="Account Funds"
                  blurb="Live broker balances pulled via OpenAlgo. ORDER and POS use these for sizing and margin display."
                  className="col-span-1 md:col-span-2 lg:col-span-2"
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
                </BentoCard>
              )}
            </>
          )}

          {/* TAB 3: INTELLIGENCE */}
          {activeTab === 'intelligence' && (
            <>
              {/* Data Extraction & Privacy */}
              <BentoCard
                icon="◐"
                title="Data Extraction & Privacy"
                blurb="Controls whether the terminal may run headless browser automation to harvest deep fundamentals and premium news tokens. Safe Mode disables all external scraping."
                badge={
                  <span
                    className={`text-[10px] px-1.5 py-0.5 font-mono ${
                      scrapingConsent === true
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                        : scrapingConsent === null
                        ? 'bg-amber-950 text-amber-400 border border-amber-800'
                        : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
                    }`}
                  >
                    {scrapingConsent === true
                      ? 'Advanced Extraction Active'
                      : scrapingConsent === null
                      ? 'Consent Required'
                      : 'Safe Mode (Anonymous)'}
                  </span>
                }
                className="col-span-1 md:col-span-2 lg:col-span-4"
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
                  {scrapingConsent === true && browserProvision && browserProvision.state !== 'ready' && (
                    <div className="mt-1 rounded border border-zinc-700/60 bg-zinc-900/60 px-2.5 py-2 text-[10px] font-mono">
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className={
                            browserProvision.state === 'failed'
                              ? 'text-red-400'
                              : browserProvision.state === 'downloading'
                              ? 'text-terminal-amber animate-pulse'
                              : 'text-zinc-400'
                          }
                        >
                          {browserProvision.state === 'downloading'
                            ? `Downloading extraction browser${
                                browserProvision.total > 0
                                  ? ` — ${Math.round((browserProvision.downloaded / browserProvision.total) * 100)}%`
                                  : '…'
                              }`
                            : browserProvision.state === 'failed'
                            ? `Browser download failed${browserProvision.error ? `: ${browserProvision.error}` : ''}`
                            : 'Extraction browser not installed yet — starting download…'}
                        </span>
                        {(browserProvision.state === 'failed' || browserProvision.state === 'missing') && (
                          <button
                            type="button"
                            onClick={handleBrowserRetry}
                            disabled={browserFetchBusy}
                            className="shrink-0 px-2 py-0.5 rounded border border-blue-500 bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60 cursor-pointer"
                          >
                            {browserFetchBusy ? 'Starting…' : 'Retry'}
                          </button>
                        )}
                      </div>
                      {browserProvision.state === 'downloading' && browserProvision.total > 0 && (
                        <div className="mt-1.5 h-1 rounded bg-zinc-800 overflow-hidden">
                          <div
                            className="h-full bg-terminal-amber transition-all"
                            style={{
                              width: `${Math.min(
                                100,
                                Math.round((browserProvision.downloaded / browserProvision.total) * 100),
                              )}%`,
                            }}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </BentoCard>

              {auth?.user?.is_admin && (
                <>
                  {/* OpenAlgo Configuration */}
                  <BentoCard
                    icon="⌁"
                    title="OpenAlgo Configuration"
                    blurb="Order-execution bridge. The URL points at your local OpenAlgo server; the key authenticates this terminal. Used by ORDER and POS."
                    className="col-span-1 md:col-span-2 lg:col-span-2"
                  >
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
                  </BentoCard>

                  {/* AI Provider */}
                  <BentoCard
                    icon="✦"
                    title="AI Provider"
                    blurb="Engine behind AI chat, background picks and summaries. Keys save automatically as you type."
                    badge={
                      aiAuthStatus ? (
                        <span className={aiAuthStatus.is_configured ? 'text-[10px] text-terminal-green' : 'text-[10px] text-terminal-red'}>
                          {aiAuthStatus.is_configured ? '✅ Connected' : '❌ Not Connected'}
                        </span>
                      ) : undefined
                    }
                    className="col-span-1 md:col-span-2 lg:col-span-2"
                  >
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-col gap-1.5 text-xs">
                        <span className="text-white/50 text-[10px] leading-relaxed">
                          Best results need a paid subscription or pay-as-you-go provider. Free models work well too depending on provider/model — Google Pro has a good free tier and also comes free with Jio Sub and can be used with this app.
                        </span>
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
                            <div className="p-2 border border-terminal-amber/30 bg-terminal-amber/10 rounded text-[10px] text-zinc-300 leading-relaxed">
                              <span className="text-terminal-amber font-semibold block mb-0.5">Notice: Gemini Model Updates</span>
                              Google now exclusively supports Gemini 3.8 Flash (High, Medium, and Low tiers). Gemini 3.1 Pro and Flash models below 3.8 have been retired by Google. All existing sessions and worker configurations are automatically remapped to Gemini 3.8 Flash internally.
                            </div>
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
                  </BentoCard>

                  {/* Background Worker Models */}
                  <BentoCard
                    icon="◇"
                    title="Background Worker Models"
                    blurb="Models for the background AI-picks worker. The hunter scans the market; the verifier double-checks. Applies to future runs."
                    className="col-span-1 md:col-span-2 lg:col-span-4"
                  >
                    <div className={`flex flex-col gap-2 ${!aiAuthStatus?.is_configured ? 'opacity-50 pointer-events-none' : ''}`}>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
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
                            <option value="">Select</option>
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
                            <option value="">Select</option>
                            {aiAvailableModels.map(m => (
                              <option key={m.id} value={m.id}>{m.label}</option>
                            ))}
                          </select>
                          <span className="text-white/50 text-[10px]">Double-checks the hunter&apos;s picks — a faster, less capable model is fine.</span>
                        </label>
                      </div>
                    </div>
                  </BentoCard>
                </>
              )}
            </>
          )}

          {/* TAB 4: AUTOMATION */}
          {activeTab === 'automation' && (
            <>
              {auth?.user?.is_admin ? (
                <BentoCard
                  icon="⚙"
                  title="Global Scan Settings"
                  blurb="Thresholds that trigger scanner alerts and notifications. Each field auto-saves and applies to future scans. Admin only."
                  className="col-span-1 md:col-span-2 lg:col-span-4"
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
                </BentoCard>
              ) : (
                <BentoCard
                  icon="⚙"
                  title="Global Scan Settings"
                  className="col-span-1 md:col-span-2 lg:col-span-4"
                >
                  <span className="text-white/50 text-[10px]">Admin access required to configure global scan thresholds.</span>
                </BentoCard>
              )}
            </>
          )}

          {/* TAB 5: SYSTEM */}
          {activeTab === 'system' && (
            <>
              {/* Watchlists Management */}
              <BentoCard
                icon="▤"
                title="Watchlists"
                blurb="Your symbol lists. The default list cannot be deleted. ● marks the active list."
                className="col-span-1 md:col-span-2 lg:col-span-2"
              >
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
                            type="button"
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
              </BentoCard>

              {/* Updates & Shortcuts */}
              <BentoCard
                icon="⌨"
                title="Updates & Shortcuts"
                blurb="Desktop updater and command-bar reference."
                className="col-span-1 md:col-span-2 lg:col-span-2"
              >
                <div className="flex flex-col gap-2">
                  {typeof window !== 'undefined' && window.electronAPI && (
                    <div className="flex flex-col items-start gap-2 border-b border-terminal-gray/40 pb-2">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
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
                          type="button"
                          onClick={handleInstallUpdate}
                          className="px-2 py-1 text-[10px] bg-terminal-green text-terminal-bg font-bold animate-pulse"
                        >
                          INSTALL & RESTART
                        </button>
                      )}
                    </div>
                  )}

                  <div className="text-white text-[10px]">
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
              </BentoCard>

              {/* Admin Links */}
              {auth?.user?.is_admin && (
                <BentoCard
                  icon="⧉"
                  title="Links"
                  blurb="Jump to background task monitoring."
                  className="col-span-1 md:col-span-2 lg:col-span-4"
                >
                  <div className="flex flex-col gap-1">
                    <Link
                      href="/jobs"
                      className="text-white hover:text-terminal-amber text-[10px] transition-colors"
                    >
                      → Jobs (background tasks)
                    </Link>
                  </div>
                </BentoCard>
              )}
            </>
          )}
        </div>
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-between px-5 py-2.5 border-t border-[#27272a] bg-[#0c0c0f] shrink-0 text-[11px] font-mono text-zinc-400">
          <div className="flex items-center gap-2">
            <span className="text-zinc-500">Press <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">ESC</kbd> to close</span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-500">Changes apply immediately</span>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-white font-mono text-xs border border-zinc-700 transition-colors cursor-pointer"
          >
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
}
