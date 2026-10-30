'use client';

import React, { useEffect, useState } from 'react';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import {
  focusedPanelAtom,
  notifPanelHighlightAtom,
  openAlgoAvailableAtom,
  selectedPanelsAtom,
  activeSymbolAtom,
  activeExchangeAtom,
  activeWatchlistIdAtom,
  moversCategoryAtom,
  activePanelsAtom,
  chartSymbolOverridesAtom,
} from '@/store/terminalStore';
import { MoversWidget } from './widgets/MoversWidget';
import { PosWidget } from './widgets/PosWidget';
import { OrderWidget } from './widgets/OrderWidget';
import { CompanyWidget } from './widgets/CompanyWidget';
import { ChartWidget } from './widgets/ChartWidget';
import { WatchWidget } from './widgets/WatchWidget';
import { LargedealsWidget } from './widgets/LargedealsWidget';
import { BreakoutsWidget } from './widgets/BreakoutsWidget';
import { NewsWidget } from './widgets/NewsWidget';
import { AnalysisWidget } from './widgets/AnalysisWidget';
import { NotifWidget } from './widgets/NotifWidget';
import { ScanWidget } from './widgets/ScanWidget';
import { ScreenerWidget } from './widgets/ScreenerWidget';
import { AnnouncementsWidget } from './widgets/AnnouncementsWidget';
import { WidgetTourOverlay } from './widgetTour/WidgetTourOverlay';
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
  const activeExchange = useAtomValue(activeExchangeAtom);
  const activeWatchlistId = useAtomValue(activeWatchlistIdAtom);
  const moversCategory = useAtomValue(moversCategoryAtom);
  const setActivePanels = useSetAtom(activePanelsAtom);
  const [chartOverrides, setChartOverrides] = useAtom(chartSymbolOverridesAtom);
  const chartDetached = title === 'CHART' && chartOverrides[id] !== undefined;

  const handleChartLinkToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (title !== 'CHART') return;
    setChartOverrides((prev) => {
      const next = { ...prev };
      if (next[id] !== undefined) {
        // Re-link: drop the override, chart falls back to global.
        delete next[id];
      } else {
        // Detach at the current global symbol.
        next[id] = { symbol: activeSymbol, exchange: activeExchange };
      }
      return next;
    });
  };

  const handlePopOut = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (title === 'EMPTY') return;
    // Every pop-out gets a unique override key: two pop-outs from the same
    // slot must not share (and clobber) one entry.
    const popoutKey = `popout_${id}_${Date.now().toString(36)}`;
    if (title === 'CHART') {
      setChartOverrides((prev) => {
        const next = { ...prev };
        // Seed the popout's own key, then drop the home slot's entry.
        next[popoutKey] = prev[id] ?? { symbol: activeSymbol, exchange: activeExchange };
        delete next[id];
        return next;
      });
    }
    const query = new URLSearchParams({
      symbol: activeSymbol || '',
      watchlistId: String(activeWatchlistId || 1),
      category: moversCategory || 'allSec',
      originPanelId: id,
      popoutPanelId: popoutKey,
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

    if (!openAlgoAvailable && title === 'ORDER') {
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
          case 'COMPANY':    return <CompanyWidget />;
      case 'CHART':    return <ChartWidget panelId={id} />;
      case 'WATCH':    return <WatchWidget />;
      case 'LARGEDEALS': return <LargedealsWidget />;
      case 'BREAKOUTS': return <BreakoutsWidget />;
      case 'NEWS':     return <NewsWidget />;
      case 'ANALYSIS': return <AnalysisWidget />;
      case 'NOTIF':   return <NotifWidget />;
      case 'ANNC':    return <AnnouncementsWidget />;
      case 'SCAN':    return <NotifWidget defaultWatchlist="all" />;
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
      data-tour-panel={title}
      data-tour-panel-id={id}
      className={`relative bg-terminal-bg border-2 flex flex-col overflow-hidden cursor-default transition-colors duration-150 h-full w-full min-h-0 min-w-0 ${
        isSelected
          ? 'border-yellow-500'
          : isFocused
            ? 'border-blue-500'
            : 'border-transparent'
      }`}
      onClick={handleClick}
    >
      <div
        className={`h-6 px-2 flex items-center justify-between font-bold text-xs uppercase transition-colors duration-150 ${
          isFlashing
            ? 'bg-yellow-500/40 text-white'
            : isFocused
              ? 'bg-blue-900 text-white'
              : 'bg-terminal-gray text-terminal-amber'
        }`}
      >
        <span className="truncate">{title}</span>
        {title !== 'EMPTY' && (
          <span className="ml-2 flex items-center gap-1">
            {title === 'CHART' && (
              <button
                type="button"
                onClick={handleChartLinkToggle}
                title={chartDetached ? 'Detached — click to re-link to the global symbol' : 'Linked to global symbol — click to detach at the current symbol'}
                className={`px-1 text-[10px] tracking-wider rounded transition-colors ${
                  chartDetached
                    ? 'text-terminal-amber bg-terminal-amber/20 hover:text-white hover:bg-terminal-amber/40 font-bold'
                    : 'text-terminal-amber/70 hover:text-white hover:bg-terminal-amber/20'
                }`}
              >
                {chartDetached ? '[FREE]' : '[LINK]'}
              </button>
            )}
            <button
              type="button"
              onClick={handlePopOut}
              title={`Pop out ${title} widget`}
              className="px-1 text-[10px] tracking-wider text-terminal-amber/70 hover:text-white hover:bg-terminal-amber/20 rounded transition-colors"
            >
              [POP]
            </button>
          </span>
        )}
      </div>
      <div className="flex-1 relative overflow-hidden min-h-0 min-w-0">
        <ErrorBoundary>
          <div className="@container h-full w-full min-h-0 min-w-0 flex flex-col overflow-hidden">
            {renderWidget()}
          </div>
        </ErrorBoundary>
      </div>
      <WidgetTourOverlay panelId={id} />
    </div>
  );
}
