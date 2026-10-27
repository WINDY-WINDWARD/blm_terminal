'use client';

import React, { useState, useEffect } from 'react';
import { useAtom, useAtomValue } from 'jotai';
import {
  wsConnectedAtom,
  fundsAtom,
  openAlgoAvailableAtom,
  tickerSourceAtom,
  panelCountAtom,
  authAtom,
  layoutSyncStatusAtom,
  advancedScrapingConsentAtom,
  type SettingsTabId,
} from '@/store/terminalStore';
import { SettingsHeader, SettingsTabBar, SettingsFooter } from '@/components/settings/tabs/SettingsChrome';
import { SettingsTabRenderer } from '@/components/settings/tabs/SettingsTabRenderer';
import { buildTabPropsBundle } from '@/components/settings/tabs/tabProps';
import { useSettingsConfig } from '@/components/settings/tabs/useSettingsConfig';
import { useBrowserProvisioning } from '@/components/settings/tabs/useBrowserProvisioning';
import { useDesktopUpdater } from '@/components/settings/tabs/useDesktopUpdater';
import { useLayoutManager } from '@/components/settings/tabs/useLayoutManager';
import { useWatchlistSettings } from '@/components/settings/tabs/useWatchlistSettings';
import { useIntelligenceRoutes } from '@/components/settings/tabs/useIntelligenceRoutes';
import { useSettingsModalTabs } from '@/components/settings/tabs/useSettingsModalTabs';

export interface SettingsModalProps {
  isOpen?: boolean;
  onClose?: () => void;
  initialTab?: SettingsTabId;
}

export function SettingsModal({ isOpen: controlledIsOpen, onClose: controlledOnClose, initialTab }: SettingsModalProps = {}) {
  const { isOpen, handleClose, globalTab, setGlobalTab, openManageProviders } = useSettingsModalTabs({
    controlledIsOpen,
    controlledOnClose,
    initialTab,
  });

  const [auth] = useAtom(authAtom);
  const isAdmin = Boolean(auth?.user?.is_admin);
  const isAuthenticated = Boolean(auth?.user);

  const [activeTab, setActiveTab] = useState<SettingsTabId>(initialTab ?? globalTab ?? 'workspace');

  useEffect(() => {
    if (initialTab) setActiveTab(initialTab);
    else if (globalTab) setActiveTab(globalTab);
  }, [initialTab, globalTab, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleClose]);

  const [wsConnected] = useAtom(wsConnectedAtom);
  const [funds] = useAtom(fundsAtom);
  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);
  const [tickerSource, setTickerSource] = useAtom(tickerSourceAtom);
  const [panelCount, setPanelCount] = useAtom(panelCountAtom);
  const [syncStatus] = useAtom(layoutSyncStatusAtom);
  const [scrapingConsent, setScrapingConsent] = useAtom(advancedScrapingConsentAtom);

  const { savedLayouts, handlePanelCountChange, handleDeleteLayout, handleRenameLayout } =
    useLayoutManager({ setPanelCount });

  const {
    watchlistCols,
    moversCols,
    watchlists,
    activeWatchlistId,
    handleWatchlistChange,
    handleMoversChange,
    handleDeleteWatchlist,
  } = useWatchlistSettings();

  const {
    configLoading,
    configError,
    notifConfig,
    appVersion,
    openAlgoUrlInput,
    setOpenAlgoUrlInput,
    openAlgoApiKeyInput,
    setOpenAlgoApiKeyInput,
    openAlgoKeyConfigured,
    setOpenAlgoKeyConfigured,
    aiHunterModel,
    setAiHunterModel,
    aiVerifierModel,
    setAiVerifierModel,
    systemConfigSaveStatus,
    aiAuthStatus,
    setAiAuthStatus,
    fetchSystemConfig,
    scheduleSystemConfigSave,
    handleNotifConfigChange,
  } = useSettingsConfig({ isOpen, isAuthenticated });

  const {
    consentSyncStatus,
    browserProvision,
    browserFetchBusy,
    handleBrowserRetry,
    handleUpdateConsent,
  } = useBrowserProvisioning({ scrapingConsent, setScrapingConsent });

  const {
    updaterStatus,
    updaterProgress,
    updateReady,
    verification,
    pendingInstall,
    handleCheckForUpdates,
    handleInstallUpdate,
  } = useDesktopUpdater();

  const {
    routeModelsQuery,
    routeModels,
    aiRoutesQuery,
    activeRoute,
    activeRouteId,
    oauthAccountCount,
    customEndpointCount,
    directKeyCount,
  } = useIntelligenceRoutes({ isOpen, activeTab, isAdmin });

  useEffect(() => {
    if (!isOpen || activeTab !== 'intelligence' || !isAdmin) return;
    let active = true;
    fetch('/api/py/ai/status')
      .then((r) => r.json())
      .then((d) => {
        if (active) setAiAuthStatus(d);
      })
      .catch(console.error);
    return () => {
      active = false;
    };
  }, [activeTab, isAdmin, isOpen, setAiAuthStatus]);

  if (!isOpen) return null;

  const tabPropsBundle = buildTabPropsBundle({
    panelCount,
    handlePanelCountChange,
    tickerSource,
    setTickerSource,
    watchlists,
    savedLayouts,
    syncStatus,
    isAuthenticated,
    handleDeleteLayout,
    handleRenameLayout,
    watchlistCols,
    handleWatchlistChange,
    moversCols,
    handleMoversChange,
    wsConnected,
    openAlgoAvailable,
    openAlgoUrlInput,
    setOpenAlgoUrlInput,
    scheduleSystemConfigSave,
    openAlgoApiKeyInput,
    setOpenAlgoApiKeyInput,
    setOpenAlgoKeyConfigured,
    openAlgoKeyConfigured,
    funds,
    isAdmin,
    scrapingConsent,
    handleUpdateConsent,
    consentSyncStatus,
    browserProvision,
    browserFetchBusy,
    handleBrowserRetry,
    aiAuthStatus,
    activeRoute,
    activeRouteId,
    isRoutesLoading: aiRoutesQuery.isLoading,
    oauthAccountCount,
    customEndpointCount,
    directKeyCount,
    openManageProviders,
    configError,
    fetchSystemConfig,
    aiHunterModel,
    setAiHunterModel,
    aiVerifierModel,
    setAiVerifierModel,
    routeModels,
    routeModelsQuery,
    configLoading,
    notifConfig,
    handleNotifConfigChange,
    activeWatchlistId,
    handleDeleteWatchlist,
    updaterStatus,
    updaterProgress,
    updateReady,
    verification,
    pendingInstall,
    handleCheckForUpdates,
    handleInstallUpdate,
    appVersion,
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200 select-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div className="relative w-full max-w-5xl bg-[#09090b] border border-[#27272a] rounded-lg shadow-2xl flex flex-col max-h-[90vh] h-[85vh] overflow-hidden">
        <SettingsHeader systemConfigSaveStatus={systemConfigSaveStatus} onClose={handleClose} />
        <SettingsTabBar
          activeTab={activeTab}
          onSelectTab={(tabId) => {
            setActiveTab(tabId);
            setGlobalTab(tabId);
          }}
        />
        <div className="flex-1 overflow-y-auto p-4 bg-[#09090b] select-text">
          <SettingsTabRenderer activeTab={activeTab} {...tabPropsBundle} />
        </div>
        <SettingsFooter onClose={handleClose} />
      </div>
    </div>
  );
}
