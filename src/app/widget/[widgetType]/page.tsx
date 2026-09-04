'use client';

import React, { use } from 'react';
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

  // Rehydrate Jotai state from URL on mount
  React.useEffect(() => {
    const symbol = searchParams.get('symbol');
    const watchlistId = searchParams.get('watchlistId');
    const category = searchParams.get('category');

    if (symbol) setSymbol(symbol);
    if (watchlistId) setWatchlistId(Number(watchlistId));
    if (category) setMoversCategory(category);
  }, [searchParams, setSymbol, setWatchlistId, setMoversCategory]);

  const widgetTitle = decodeURIComponent(unwrappedParams.widgetType).toUpperCase();
  const uniqueId = `popout_${widgetTitle}`;

  return (
    <div className="h-screen w-screen bg-terminal-bg text-terminal-amber font-mono overflow-hidden flex flex-col">
      <WidgetRenderer title={widgetTitle} panelId={uniqueId} />
    </div>
  );
}