'use client';

import type { UseQueryResult } from '@tanstack/react-query';
import type { RouteModelCatalogResponse, RouteModelCatalogEntry } from '@/types/aiRoutes';
import type { PanelCount, Watchlist, SavedLayout } from '@/store/terminalStore';
import type { FundsData } from '@/lib/openalgo';
import type { BrowserProvision, NotifConfigState, NotifConfigKey } from './types';
import type { WorkspaceTabProps } from './WorkspaceTab';
import type { ConnectionsTabProps } from './ConnectionsTab';
import type { IntelligenceTabProps } from './IntelligenceTab';
import type { AutomationTabProps } from './AutomationTab';
import type { SystemTabProps } from './SystemTab';

export interface SettingsTabPropsBundle {
  workspaceProps: WorkspaceTabProps;
  connectionsProps: ConnectionsTabProps;
  intelligenceProps: IntelligenceTabProps;
  automationProps: AutomationTabProps;
  systemProps: SystemTabProps;
}

export function buildTabPropsBundle(params: {
  panelCount: PanelCount;
  handlePanelCountChange: (count: PanelCount) => void;
  tickerSource: string;
  setTickerSource: (val: string) => void;
  watchlists: Watchlist[];
  savedLayouts: Record<string, SavedLayout>;
  syncStatus: { status: 'idle' | 'pending' | 'synced' | 'error'; pendingCount: number };
  isAuthenticated: boolean;
  handleDeleteLayout: (name: string) => void;
  handleRenameLayout: (oldName: string, newName: string) => void;
  watchlistCols: string[];
  handleWatchlistChange: (key: string, checked: boolean) => void;
  moversCols: string[];
  handleMoversChange: (key: string, checked: boolean) => void;
  wsConnected: boolean;
  openAlgoAvailable: boolean;
  openAlgoUrlInput: string;
  setOpenAlgoUrlInput: (val: string) => void;
  scheduleSystemConfigSave: (key: string, value: string) => void;
  openAlgoApiKeyInput: string;
  setOpenAlgoApiKeyInput: (val: string) => void;
  setOpenAlgoKeyConfigured: (val: boolean) => void;
  openAlgoKeyConfigured: boolean;
  funds: FundsData | null;
  isAdmin: boolean;
  scrapingConsent: boolean | null;
  handleUpdateConsent: (val: boolean) => void;
  consentSyncStatus: string | null;
  browserProvision: BrowserProvision | null;
  browserFetchBusy: boolean;
  handleBrowserRetry: () => void;
  aiAuthStatus: { provider: string; is_configured: boolean } | null;
  activeRoute: { display_label?: string; id?: string } | undefined;
  activeRouteId?: string;
  isRoutesLoading: boolean;
  oauthAccountCount: number;
  customEndpointCount: number;
  directKeyCount: number;
  openManageProviders: () => void;
  configError: string | null;
  fetchSystemConfig: () => void;
  aiHunterModel: string;
  setAiHunterModel: (val: string) => void;
  aiVerifierModel: string;
  setAiVerifierModel: (val: string) => void;
  routeModels: RouteModelCatalogEntry[];
  routeModelsQuery: UseQueryResult<RouteModelCatalogResponse, Error>;
  configLoading: boolean;
  notifConfig: NotifConfigState;
  handleNotifConfigChange: (key: NotifConfigKey, value: string) => void;
  activeWatchlistId: number;
  handleDeleteWatchlist: (id: number, name: string) => void;
  updaterStatus: string;
  updaterProgress: { percent: number } | null;
  updateReady: boolean;
  handleCheckForUpdates: () => void;
  handleInstallUpdate: () => void;
  appVersion: string;
}): SettingsTabPropsBundle {
  return {
    workspaceProps: {
      panelCount: params.panelCount,
      onPanelCountChange: params.handlePanelCountChange,
      tickerSource: params.tickerSource,
      onTickerSourceChange: params.setTickerSource,
      watchlists: params.watchlists,
      savedLayouts: params.savedLayouts,
      syncStatus: params.syncStatus,
      isAuthenticated: params.isAuthenticated,
      onDeleteLayout: params.handleDeleteLayout,
      onRenameLayout: params.handleRenameLayout,
      watchlistCols: params.watchlistCols,
      onWatchlistColsChange: params.handleWatchlistChange,
      moversCols: params.moversCols,
      onMoversColsChange: params.handleMoversChange,
    },
    connectionsProps: {
      wsConnected: params.wsConnected,
      openAlgoAvailable: params.openAlgoAvailable,
      openAlgoUrlInput: params.openAlgoUrlInput,
      onOpenAlgoUrlChange: (val: string) => {
        params.setOpenAlgoUrlInput(val);
        params.scheduleSystemConfigSave('openalgo.url', val);
      },
      openAlgoApiKeyInput: params.openAlgoApiKeyInput,
      onOpenAlgoApiKeyChange: (val: string) => {
        params.setOpenAlgoApiKeyInput(val);
        params.scheduleSystemConfigSave('openalgo.api_key', val);
        if (val.trim()) params.setOpenAlgoKeyConfigured(true);
      },
      openAlgoKeyConfigured: params.openAlgoKeyConfigured,
      funds: params.funds,
      isAdmin: params.isAdmin,
    },
    intelligenceProps: {
      scrapingConsent: params.scrapingConsent,
      onUpdateConsent: params.handleUpdateConsent,
      consentSyncStatus: params.consentSyncStatus,
      browserProvision: params.browserProvision,
      browserFetchBusy: params.browserFetchBusy,
      onBrowserRetry: params.handleBrowserRetry,
      isAdmin: params.isAdmin,
      aiAuthStatus: params.aiAuthStatus,
      activeRoute: params.activeRoute,
      activeRouteId: params.activeRouteId,
      isRoutesLoading: params.isRoutesLoading,
      oauthAccountCount: params.oauthAccountCount,
      customEndpointCount: params.customEndpointCount,
      directKeyCount: params.directKeyCount,
      onOpenManageProviders: params.openManageProviders,
      configError: params.configError,
      onRetryConfig: params.fetchSystemConfig,
      aiHunterModel: params.aiHunterModel,
      onAiHunterModelChange: (value: string) => {
        params.setAiHunterModel(value);
        params.scheduleSystemConfigSave('ai.hunter_model', value);
      },
      aiVerifierModel: params.aiVerifierModel,
      onAiVerifierModelChange: (value: string) => {
        params.setAiVerifierModel(value);
        params.scheduleSystemConfigSave('ai.verifier_model', value);
      },
      routeModels: params.routeModels,
      routeModelsQuery: params.routeModelsQuery,
      configLoading: params.configLoading,
    },
    automationProps: {
      isAdmin: params.isAdmin,
      configLoading: params.configLoading,
      configError: params.configError,
      notifConfig: params.notifConfig,
      onNotifConfigChange: params.handleNotifConfigChange,
      onRetryConfig: params.fetchSystemConfig,
    },
    systemProps: {
      watchlists: params.watchlists,
      activeWatchlistId: params.activeWatchlistId,
      onDeleteWatchlist: params.handleDeleteWatchlist,
      updaterStatus: params.updaterStatus,
      updaterProgress: params.updaterProgress,
      updateReady: params.updateReady,
      onCheckForUpdates: params.handleCheckForUpdates,
      onInstallUpdate: params.handleInstallUpdate,
      appVersion: params.appVersion,
      isAdmin: params.isAdmin,
    },
  };
}
