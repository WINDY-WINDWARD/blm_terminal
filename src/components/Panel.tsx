'use client';

import React, { useEffect, useState } from 'react';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import {
  focusedPanelAtom,
  notifPanelHighlightAtom,
  openAlgoAvailableAtom,
  selectedPanelsAtom,
  activeSymbolAtom,
  activeWatchlistIdAtom,
  moversCategoryAtom,
  activePanelsAtom,
} from '@/store/terminalStore';
import { MoversWidget } from './widgets/MoversWidget';
import { PosWidget } from './widgets/PosWidget';
import { OrderWidget } from './widgets/OrderWidget';
import { ChartWidget } from './widgets/ChartWidget';
import { WatchWidget } from './widgets/WatchWidget';
import { SettingsWidget } from './widgets/SettingsWidget';
import { FundamentalsWidget } from './widgets/FundamentalsWidget';
import { DealsWidget } from './widgets/DealsWidget';
import { LargedealsWidget } from './widgets/LargedealsWidget';
import { BreakoutsWidget } from './widgets/BreakoutsWidget';
import { NewsWidget } from './widgets/NewsWidget';
import { AnalysisWidget } from './widgets/AnalysisWidget';
import { NotifWidget } from './widgets/NotifWidget';
import { ScanWidget } from './widgets/ScanWidget';
import { ScreenerWidget } from './widgets/ScreenerWidget';
import { AnnouncementsWidget } from './widgets/AnnouncementsWidget';
import { DocsWidget } from './widgets/DocsWidget';
import { AiWidget } from './widgets/AiWidget';
import { PortfolioWidget } from './widgets/PortfolioWidget';
import { AdminWidget } from './widgets/AdminWidget';
import { AiPicksWidget } from './widgets/AiPicksWidget';
import { ErrorBoundary } from './ErrorBoundary';

interface PanelProps {
  id: string;
  title: string;
}

export function Panel({ id, title }: PanelProps) {
  const [focusedPanel, setFocusedPanel] = useAtom(focusedPanelAtom);
  const [selectedPanels, setSelectedPanels] = useAtom(selectedPanelsAtom);
  const [notifHighlight] = useAtom(notifPanelHighlightAtom);
  const isFocused = focusedPanel === id;
  const isSelected = selectedPanels.includes(id);
  const [isFlashing, setIsFlashing] = useState(false);

  useEffect(() => {
    if (title !== 'NOTIF' || notifHighlight === 0) return;
    const flashTimer = setTimeout(() => setIsFlashing(true), 0);
    const clearTimer = setTimeout(() => setIsFlashing(false), 2000);
    return () => {
      clearTimeout(flashTimer);
      clearTimeout(clearTimer);
      setIsFlashing(false);
    };
  }, [notifHighlight, title]);

  const handleClick = (e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      setSelectedPanels((prev) =>
        prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
      );
      // Keep the focused panel unchanged when Ctrl+clicking
      return;
    }
    // Normal click: clear selection and focus this panel
    setSelectedPanels([]);
    setFocusedPanel(id);
  };

  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);
  const activeSymbol = useAtomValue(activeSymbolAtom);
  const activeWatchlistId = useAtomValue(activeWatchlistIdAtom);
  const moversCategory = useAtomValue(moversCategoryAtom);
  const setActivePanels = useSetAtom(activePanelsAtom);

  const handlePopOut = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (title === 'EMPTY') return;
    const query = new URLSearchParams({
      symbol: activeSymbol || '',
      watchlistId: String(activeWatchlistId || 1),
      category: moversCategory || 'allSec',
      originPanelId: id,
    });
    const url = `/widget/${encodeURIComponent(title)}?${query.toString()}`;
    window.open(url, `blm_widget_${title}_${id}`, 'width=1000,height=700');
    // Instantly undock widget and free the slot for other widgets
    setActivePanels((prev) => ({ ...prev, [id]: 'EMPTY' }));
  };

  const renderWidget = () => {
    if (title === 'EMPTY') {
      return (
        <div className="h-full w-full flex flex-col items-center justify-center text-white/30 font-mono text-xs gap-1 border border-dashed border-terminal-border/30 m-0.5">
          <span className="text-terminal-amber/50 font-bold uppercase tracking-wider">[ EMPTY SLOT ]</span>
          <span className="text-[10px] text-white/40">Select this slot and type a command (e.g. CHART)</span>
        </div>
      );
    }

    if (!openAlgoAvailable && (title === 'ORDER' || title === 'POS')) {
      return (
        <div className="h-full w-full flex flex-col items-center justify-center text-terminal-amber/50 font-mono text-xs gap-2">
          <span className="text-terminal-amber/30 text-lg font-bold">--</span>
          <span>OpenAlgo not available</span>
          <span className="text-terminal-amber/30">Set OPENALGO_URL and OPENALGO_API_KEY</span>
        </div>
      );
    }

    switch (title) {
      case 'TOP':      return <MoversWidget />;
      case 'POS':      return <PosWidget />;
      case 'ORDER':    return <OrderWidget panelId={id} />;
      case 'CHART':    return <ChartWidget panelId={id} />;
      case 'WATCH':    return <WatchWidget />;
      case 'SETTINGS': return <SettingsWidget />;
      case 'FDM':      return <FundamentalsWidget />;
      case 'DEALS':    return <DealsWidget />;
      case 'LARGEDEALS': return <LargedealsWidget />;
      case 'BREAKOUTS': return <BreakoutsWidget />;
      case 'NEWS':     return <NewsWidget />;
      case 'ANALYSIS': return <AnalysisWidget />;
      case 'NOTIF':   return <NotifWidget />;
      case 'ANNC':    return <AnnouncementsWidget />;
      case 'SCAN':    return <ScanWidget />;
      case 'SCREENER': return <ScreenerWidget />;
      case 'DOCS':    return <DocsWidget />;
      case 'AI':      return <AiWidget />;
      case 'PORTFOLIO': return <PortfolioWidget />;
      case 'ADMIN':   return <AdminWidget />;
      case 'PICKS':   return <AiPicksWidget panelId={id} />;
      default:
        return (
          <div className="text-terminal-amber/50 text-xs font-mono h-full w-full flex items-center justify-center">
            [{title} WIDGET NOT FOUND]
          </div>
        );
    }
  };

  return (
    <div
      className={`bg-terminal-bg border-2 flex flex-col overflow-hidden cursor-default transition-colors duration-200 h-full w-full ${
        isSelected
          ? 'border-yellow-500'
          : isFocused
            ? 'border-blue-500'
            : 'border-transparent'
      }`}
      onClick={handleClick}
    >
      <div
        className={`h-6 px-2 flex items-center justify-between font-bold text-xs uppercase transition-colors duration-200 ${
          isFlashing
            ? 'bg-yellow-500/40 text-white'
            : isFocused
              ? 'bg-blue-900 text-white'
              : 'bg-terminal-gray text-terminal-amber'
        }`}
      >
        <span className="truncate">{title}</span>
        {title !== 'EMPTY' && (
          <button
            type="button"
            onClick={handlePopOut}
            title={`Pop out ${title} widget`}
            className="ml-2 px-1 text-[10px] tracking-wider text-terminal-amber/70 hover:text-white hover:bg-terminal-amber/20 rounded transition-colors"
          >
            [POP]
          </button>
        )}
      </div>
      <div className="flex-1 relative overflow-hidden">
        <ErrorBoundary>
          <div className="h-full w-full flex flex-col overflow-hidden">
            {renderWidget()}
          </div>
        </ErrorBoundary>
      </div>
    </div>
  );
}
