'use client';

import React, { use, useState, useEffect, useRef } from 'react';
import { WidgetRenderer } from '@/components/WidgetRenderer';
import { useSearchParams } from 'next/navigation';
import { useSetAtom } from 'jotai';
import { activeSymbolAtom, activeWatchlistIdAtom, moversCategoryAtom } from '@/store/terminalStore';

export default function PopoutWidgetPage({ params }: { params: Promise<{ widgetType: string }> }) {
  const unwrappedParams = use(params);
  const searchParams = useSearchParams();
  
  const setSymbol = useSetAtom(activeSymbolAtom);
  const setWatchlistId = useSetAtom(activeWatchlistIdAtom);
  const setMoversCategory = useSetAtom(moversCategoryAtom);

  const [isRestoring, setIsRestoring] = useState(false);
  const pendingReqIdRef = useRef<string | null>(null);

  const originPanelId = searchParams.get('originPanelId') || 'panel-1';
  const widgetTitle = decodeURIComponent(unwrappedParams.widgetType).toUpperCase();
  const uniqueId = `popout_${widgetTitle}`;

  // Rehydrate Jotai state from URL on mount
  useEffect(() => {
    const symbol = searchParams.get('symbol');
    const watchlistId = searchParams.get('watchlistId');
    const category = searchParams.get('category');

    if (symbol) setSymbol(symbol);
    if (watchlistId) setWatchlistId(Number(watchlistId));
    if (category) setMoversCategory(category);
  }, [searchParams, setSymbol, setWatchlistId, setMoversCategory]);

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
    const reqId = `${originPanelId}:${widgetTitle}:${Date.now()}:${Math.random().toString(36).substring(2, 7)}`;
    pendingReqIdRef.current = reqId;
    window.localStorage.setItem('__REQUEST_RESTORE', reqId);
  };

  return (
    <div className="h-screen w-screen bg-terminal-bg text-terminal-amber font-mono overflow-hidden flex flex-col select-none">
      {/* Draggable Titlebar with Native Window Controls area offset */}
      <div 
        className="h-8 bg-[#121212] border-b border-terminal-border flex items-center justify-between px-3 pr-36 shrink-0 select-none"
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
        <WidgetRenderer title={widgetTitle} panelId={uniqueId} />
      </div>
    </div>
  );
}