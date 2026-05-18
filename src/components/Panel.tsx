'use client';

import React, { useEffect, useState } from 'react';
import { useAtom } from 'jotai';
import { focusedPanelAtom, notifPanelHighlightAtom } from '@/store/terminalStore';
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
import { AnnouncementsWidget } from './widgets/AnnouncementsWidget';
import { ErrorBoundary } from './ErrorBoundary';

interface PanelProps {
  id: string;
  title: string;
}

export function Panel({ id, title }: PanelProps) {
  const [focusedPanel, setFocusedPanel] = useAtom(focusedPanelAtom);
  const [notifHighlight] = useAtom(notifPanelHighlightAtom);
  const isFocused = focusedPanel === id;
  const [isFlashing, setIsFlashing] = useState(false);

  useEffect(() => {
    if (title !== 'NOTIF' || notifHighlight === 0) return;
    setIsFlashing(true);
    const timer = setTimeout(() => setIsFlashing(false), 2000);
    return () => {
      clearTimeout(timer);
      setIsFlashing(false);
    };
  }, [notifHighlight, title]);

  const renderWidget = () => {
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
      className={`bg-terminal-bg border-2 flex flex-col overflow-hidden cursor-default transition-colors duration-200 ${
        isFocused ? 'border-blue-500' : 'border-transparent'
      }`}
      onClick={() => setFocusedPanel(id)}
    >
      <div
        className={`h-6 px-2 flex items-center font-bold text-xs uppercase transition-colors duration-200 ${
          isFlashing
            ? 'bg-yellow-500/40 text-white'
            : isFocused
              ? 'bg-blue-900 text-white'
              : 'bg-terminal-gray text-terminal-amber'
        }`}
      >
        <span className="truncate">{title}</span>
      </div>
      <div className="flex-1 relative overflow-hidden">
        <ErrorBoundary>
          {renderWidget()}
        </ErrorBoundary>
      </div>
    </div>
  );
}
