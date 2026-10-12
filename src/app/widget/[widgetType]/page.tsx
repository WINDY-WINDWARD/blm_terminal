'use client';

import React, { use, useState, useEffect, useRef } from 'react';
import { WidgetRenderer } from '@/components/WidgetRenderer';
import { useSearchParams } from 'next/navigation';
import { useSetAtom, useAtomValue } from 'jotai';
import { activeSymbolAtom, activeWatchlistIdAtom, moversCategoryAtom, chartSymbolOverridesAtom, companySymbolOverridesAtom } from '@/store/terminalStore';
import { useIsMac } from '@/lib/usePlatform';
import { cn } from '@/lib/utils';

export default function PopoutWidgetPage({ params }: { params: Promise<{ widgetType: string }> }) {
  const unwrappedParams = use(params);
  const searchParams = useSearchParams();
  
  const setSymbol = useSetAtom(activeSymbolAtom);
  const setWatchlistId = useSetAtom(activeWatchlistIdAtom);
  const setMoversCategory = useSetAtom(moversCategoryAtom);
  const overrides = useAtomValue(chartSymbolOverridesAtom);
  const companyOverrides = useAtomValue(companySymbolOverridesAtom);

  const [isRestoring, setIsRestoring] = useState(false);
  const pendingReqIdRef = useRef<string | null>(null);
  const isMac = useIsMac();

  const originPanelId = searchParams.get('originPanelId') || 'panel-1';
  const widgetTitle = decodeURIComponent(unwrappedParams.widgetType).toUpperCase();
  // Per-panel state (e.g. chart symbol overrides) lives under this key.
  // A popout opened from the grid carries popoutPanelId (seeded copy of the
  // home panel's state); a directly-opened URL gets a unique throwaway key
  // so it can never hijack a home panel's state.
  const [fallbackPanelId] = useState(
    () => `popout_direct_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
  );
  const panelId = searchParams.get('popoutPanelId') || searchParams.get('originPanelId') || fallbackPanelId;

  // Rehydrate Jotai state from URL on mount. The global symbol is only
  // set when this popout has no chart override of its own — otherwise a
  // stale bookmark/reload would clobber the grid's newer global symbol.
  useEffect(() => {
    const symbol = searchParams.get('symbol');
    const watchlistId = searchParams.get('watchlistId');
    const category = searchParams.get('category');

    const popoutPanelId = searchParams.get('popoutPanelId');
    const isIndependentChart = widgetTitle === 'CHART' && (Boolean(popoutPanelId) || overrides[panelId] !== undefined);
    const isIndependentCompany = widgetTitle === 'COMPANY' && (Boolean(popoutPanelId) || companyOverrides[panelId] !== undefined);
    if (symbol && !isIndependentChart && !isIndependentCompany) setSymbol(symbol);
    if (watchlistId) setWatchlistId(Number(watchlistId));
    if (category) setMoversCategory(category);
  }, [searchParams, setSymbol, setWatchlistId, setMoversCategory, widgetTitle, overrides, companyOverrides, panelId]);

  // Listen for handshake response from main window
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (!pendingReqIdRef.current) return;

      if (e.key === '__RESTORE_ACCEPTED' && e.newValue === pendingReqIdRef.current) {
        pendingReqIdRef.current = null;
        window.close();
      } else if (e.key === '__RESTORE_REJECTED' && e.newValue === pendingReqIdRef.current) {
        pendingReqIdRef.current = null;
        setIsRestoring(false);
        alert(
          'The main terminal grid is currently full. To dock this widget, you can either pop out another widget to make room, or you can safely close this window now and re-open the widget in a specific slot later using terminal commands.'
        );
      }
    };

    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const handleSendBack = () => {
    setIsRestoring(true);
    // v2 format carries the popout's own override key so the grid can move
    // the detached symbol home: origin:popoutKey:title:ts:rand.
    const reqId = `${originPanelId}:${panelId}:${widgetTitle}:${Date.now()}:${Math.random().toString(36).substring(2, 7)}`;
    pendingReqIdRef.current = reqId;
    window.localStorage.setItem('__REQUEST_RESTORE', reqId);
  };

  return (
    <div className="h-screen w-screen bg-terminal-bg text-terminal-amber font-mono overflow-hidden flex flex-col select-none">
      {/* Draggable Titlebar with Native Window Controls area offset */}
      <div 
        className={cn(
          "h-8 bg-[#121212] border-b border-terminal-border flex items-center justify-between shrink-0 select-none",
          isMac ? "pl-20 pr-3" : "pl-3 pr-36"
        )}
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider text-terminal-amber uppercase">
            {widgetTitle} <span className="text-white/40 text-[10px] font-normal">[DETACHED]</span>
          </span>
        </div>
        <div className="flex items-center gap-1" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
          <button
            type="button"
            onClick={handleSendBack}
            disabled={isRestoring}
            title="Dock back to main terminal grid"
            className="px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase bg-terminal-amber/20 hover:bg-terminal-amber hover:text-black border border-terminal-amber text-terminal-amber rounded transition-colors disabled:opacity-50"
          >
            {isRestoring ? 'Docking...' : '[SEND BACK]'}
          </button>
        </div>
      </div>

      {/* Widget Content */}
      <div className="flex-1 min-h-0 relative overflow-hidden select-text">
        {/* originPanelId keeps per-panel state (e.g. chart symbol overrides)
            shared between the home panel and its popout. */}
        <WidgetRenderer title={widgetTitle} panelId={panelId} symbolOverride={searchParams.get('symbol') || undefined} />
      </div>
    </div>
  );
}