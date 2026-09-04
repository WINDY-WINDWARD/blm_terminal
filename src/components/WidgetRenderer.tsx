'use client';

import React from 'react';
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

interface WidgetRendererProps {
  title: string;
  panelId: string;
}

export function WidgetRenderer({ title, panelId }: WidgetRendererProps) {
  switch (title) {
    case 'TOP':      return <MoversWidget />;
    case 'POS':      return <PosWidget />;
    case 'ORDER':    return <OrderWidget panelId={panelId} />;
    case 'CHART':    return <ChartWidget panelId={panelId} />;
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
    case 'PICKS':   return <AiPicksWidget panelId={panelId} />;
    default:
      return (
        <div className="text-terminal-amber/50 text-xs font-mono h-full w-full flex items-center justify-center">
          [{title} WIDGET NOT FOUND]
        </div>
      );
  }
}