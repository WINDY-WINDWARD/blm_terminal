'use client';

import React, { useState } from 'react';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom, companySymbolOverridesAtom } from '@/store/terminalStore';
import { FundamentalsTab } from './CompanyTabs/FundamentalsTab';
import { DealsTab } from './CompanyTabs/DealsTab';
import { CompanyNewsTab } from './CompanyTabs/CompanyNewsTab';
import { AlertsTab } from './CompanyTabs/AlertsTab';
import { CorporateTab } from './CompanyTabs/CorporateTab';

export function CompanyWidget({ panelId, symbolOverride }: { panelId?: string; symbolOverride?: string } = {}) {
  const globalSymbol = useAtomValue(activeSymbolAtom);
  const companyOverrides = useAtomValue(companySymbolOverridesAtom);
  const symbol = (panelId && companyOverrides[panelId]?.symbol) || symbolOverride || globalSymbol;
  const [activeTab, setActiveTab] = useState<'fundamentals' | 'deals' | 'news' | 'alerts' | 'corporate'>('fundamentals');

  if (!symbol) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center bg-[#0a0a0a] border border-terminal-gray/20">
        <span className="text-white/40 text-sm font-mono animate-pulse">SELECT A SYMBOL</span>
      </div>
    );
  }

  const tabs = [
    { id: 'fundamentals', label: 'FUNDAMENTALS' },
    { id: 'deals', label: 'DEALS' },
    { id: 'news', label: 'NEWS' },
    { id: 'alerts', label: 'ALERTS' },
    { id: 'corporate', label: 'CORPORATE' },
  ] as const;

  return (
    <div className="h-full w-full flex flex-col bg-[#0a0a0a] overflow-hidden">
      {/* Tab Bar */}
      <div className="flex border-b border-terminal-gray/30 p-1 gap-1 shrink-0 bg-[#111]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-xs font-mono transition-all duration-300 ease-out border ${
              activeTab === tab.id
                ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/10'
                : 'border-transparent text-white/60 hover:text-white hover:bg-terminal-gray/20'
            }`}
          >
            {tab.label}
          </button>
        ))}
        <div className="ml-auto flex items-center px-2">
          <span className="text-terminal-amber font-mono text-sm font-bold tracking-wider">{symbol}</span>
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto relative bg-[#0a0a0a]">
        <div key={activeTab} className="absolute inset-0 animate-in fade-in duration-300">
          {activeTab === 'fundamentals' && <FundamentalsTab symbol={symbol} />}
          {activeTab === 'deals' && <DealsTab symbol={symbol} />}
          {activeTab === 'news' && <CompanyNewsTab symbol={symbol} />}
          {activeTab === 'alerts' && <AlertsTab symbol={symbol} />}
          {activeTab === 'corporate' && <CorporateTab symbol={symbol} />}
        </div>
      </div>
    </div>
  );
}
