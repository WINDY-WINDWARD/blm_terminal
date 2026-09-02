'use client';

import React, { useEffect, use } from 'react';
import { useSearchParams } from 'next/navigation';
import { useSetAtom, useAtomValue } from 'jotai';
import {
  activeSymbolAtom,
  activeWatchlistIdAtom,
  moversCategoryAtom,
  openAlgoAvailableAtom,
} from '@/store/terminalStore';
import { MoversWidget } from '@/components/widgets/MoversWidget';
import { PosWidget } from '@/components/widgets/PosWidget';
import { OrderWidget } from '@/components/widgets/OrderWidget';
import { ChartWidget } from '@/components/widgets/ChartWidget';
import { WatchWidget } from '@/components/widgets/WatchWidget';
import { SettingsWidget } from '@/components/widgets/SettingsWidget';
import { FundamentalsWidget } from '@/components/widgets/FundamentalsWidget';
import { DealsWidget } from '@/components/widgets/DealsWidget';
import { LargedealsWidget } from '@/components/widgets/LargedealsWidget';
import { BreakoutsWidget } from '@/components/widgets/BreakoutsWidget';
import { NewsWidget } from '@/components/widgets/NewsWidget';
import { AnalysisWidget } from '@/components/widgets/AnalysisWidget';
import { NotifWidget } from '@/components/widgets/NotifWidget';
import { ScanWidget } from '@/components/widgets/ScanWidget';
import { ScreenerWidget } from '@/components/widgets/ScreenerWidget';
import { AnnouncementsWidget } from '@/components/widgets/AnnouncementsWidget';
import { DocsWidget } from '@/components/widgets/DocsWidget';
import { AiWidget } from '@/components/widgets/AiWidget';
import { PortfolioWidget } from '@/components/widgets/PortfolioWidget';
import { AdminWidget } from '@/components/widgets/AdminWidget';
import { AiPicksWidget } from '@/components/widgets/AiPicksWidget';
import { ErrorBoundary } from '@/components/ErrorBoundary';

interface PageProps {
  params: Promise<{ widgetType: string }>;
}

export default function WidgetPage({ params }: PageProps) {
  const resolvedParams = use(params);
  const widgetType = resolvedParams.widgetType.toUpperCase();
  const searchParams = useSearchParams();

  const setActiveSymbol = useSetAtom(activeSymbolAtom);
  const setActiveWatchlistId = useSetAtom(activeWatchlistIdAtom);
  const setMoversCategory = useSetAtom(moversCategoryAtom);
  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);

  useEffect(() => {
    // Rehydrate state serialized in URL query parameters
    const symbol = searchParams.get('symbol');
    if (symbol) {
      setActiveSymbol(symbol);
    }

    const watchlistId = searchParams.get('watchlistId');
    if (watchlistId) {
      const parsed = parseInt(watchlistId, 10);
      if (!isNaN(parsed)) {
        setActiveWatchlistId(parsed);
      }
    }

    const category = searchParams.get('category');
    if (category) {
      setMoversCategory(category);
    }
  }, [searchParams, setActiveSymbol, setActiveWatchlistId, setMoversCategory]);

  const renderWidget = () => {
    if (!openAlgoAvailable && (widgetType === 'ORDER' || widgetType === 'POS')) {
      return (
        <div className="h-full w-full flex flex-col items-center justify-center text-terminal-amber/50 font-mono text-xs gap-2">
          <span className="text-terminal-amber/30 text-lg font-bold">--</span>
          <span>OpenAlgo not available</span>
          <span className="text-terminal-amber/30">Set OPENALGO_URL and OPENALGO_API_KEY</span>
        </div>
      );
    }

    switch (widgetType) {
      case 'TOP':
        return <MoversWidget />;
      case 'POS':
        return <PosWidget />;
      case 'ORDER':
        return <OrderWidget panelId="popout-order" />;
      case 'CHART':
        return <ChartWidget panelId="popout-chart" />;
      case 'WATCH':
        return <WatchWidget />;
      case 'SETTINGS':
        return <SettingsWidget />;
      case 'FDM':
        return <FundamentalsWidget />;
      case 'DEALS':
        return <DealsWidget />;
      case 'LARGEDEALS':
        return <LargedealsWidget />;
      case 'BREAKOUTS':
        return <BreakoutsWidget />;
      case 'NEWS':
        return <NewsWidget />;
      case 'ANALYSIS':
        return <AnalysisWidget />;
      case 'NOTIF':
        return <NotifWidget />;
      case 'ANNC':
        return <AnnouncementsWidget />;
      case 'SCAN':
        return <ScanWidget />;
      case 'SCREENER':
        return <ScreenerWidget />;
      case 'DOCS':
        return <DocsWidget />;
      case 'AI':
        return <AiWidget />;
      case 'PORTFOLIO':
        return <PortfolioWidget />;
      case 'ADMIN':
        return <AdminWidget />;
      case 'PICKS':
        return <AiPicksWidget panelId="popout-picks" />;
      default:
        return (
          <div className="text-terminal-amber/50 text-xs font-mono h-full w-full flex items-center justify-center">
            [{widgetType} WIDGET NOT FOUND]
          </div>
        );
    }
  };

  return (
    <div className="w-full h-full flex flex-col overflow-hidden bg-terminal-bg border-none">
      <div className="h-6 px-2 flex items-center justify-between font-bold text-xs uppercase bg-terminal-gray text-terminal-amber border-b border-terminal-border select-none">
        <span>{widgetType}</span>
        <span className="text-[10px] text-terminal-amber/50">POP-OUT WINDOW</span>
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
