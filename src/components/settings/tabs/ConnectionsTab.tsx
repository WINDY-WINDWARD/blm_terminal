'use client';

import React from 'react';
import type { FundsData } from '@/lib/openalgo';
import { BentoCard } from './BentoCard';

export interface ConnectionsTabProps {
  wsConnected: boolean;
  openAlgoAvailable: boolean;
  openAlgoUrlInput: string;
  onOpenAlgoUrlChange: (value: string) => void;
  openAlgoApiKeyInput: string;
  onOpenAlgoApiKeyChange: (value: string) => void;
  openAlgoKeyConfigured: boolean;
  funds: FundsData | null;
  isAdmin: boolean;
}

export function ConnectionsTab({
  wsConnected,
  openAlgoAvailable,
  openAlgoUrlInput,
  onOpenAlgoUrlChange,
  openAlgoApiKeyInput,
  onOpenAlgoApiKeyChange,
  openAlgoKeyConfigured,
  funds,
  isAdmin,
}: ConnectionsTabProps) {
  return (
    <>
      {/* Market Connection */}
      <BentoCard
        icon="⇄"
        title="Market Connection"
        blurb="Live socket health for market data, plus the broker bridge endpoint."
        className="col-span-1 md:col-span-2 lg:col-span-2"
      >
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                wsConnected ? 'bg-terminal-green' : 'bg-terminal-red'
              }`}
            />
            <span className={wsConnected ? 'text-terminal-green' : 'text-terminal-red'}>
              Market WS: {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
            </span>
          </div>
          {openAlgoAvailable && (
            <div className="text-white text-[10px]">
              OpenAlgo URL: {openAlgoUrlInput || 'Not configured'}
            </div>
          )}
        </div>
      </BentoCard>

      {/* Account Funds */}
      {openAlgoAvailable && funds && (
        <BentoCard
          icon="₹"
          title="Account Funds"
          blurb="Live broker balances pulled via OpenAlgo. ORDER and POS use these for sizing and margin display."
          className="col-span-1 md:col-span-2 lg:col-span-2"
        >
          <div className="flex flex-col gap-1">
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
              {[
                ['Available Cash', funds.availablecash],
                ['Collateral', funds.collateral],
                ['M2M Realized', funds.m2mrealized],
                ['M2M Unrealized', funds.m2munrealized],
                ['Utilised Debits', funds.utiliseddebits],
              ].map(([label, val]) => (
                <React.Fragment key={label}>
                  <span className="text-white">{label}:</span>
                  <span className="text-terminal-amber text-right">{val}</span>
                </React.Fragment>
              ))}
            </div>
          </div>
        </BentoCard>
      )}

      {isAdmin && (
        <BentoCard
          icon="⌁"
          title="OpenAlgo Configuration"
          blurb="Order-execution bridge. The URL points at your local OpenAlgo server; the key authenticates this terminal. Used by ORDER and POS."
          className="col-span-1 md:col-span-2 lg:col-span-2"
        >
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1.5 text-xs">
              <label className="flex flex-col gap-0.5">
                <span className="text-white/70 text-[10px]">OpenAlgo URL:</span>
                <input
                  type="text"
                  value={openAlgoUrlInput}
                  onChange={(e) => onOpenAlgoUrlChange(e.target.value)}
                  placeholder="http://127.0.0.1:5000"
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                />
                <span className="text-white/50 text-[10px]">Address of your local OpenAlgo server (order-execution bridge).</span>
              </label>
              <label className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-white/70 text-[10px]">OpenAlgo API Key:</span>
                  {openAlgoKeyConfigured && (
                    <span className="text-[10px] text-terminal-green font-mono">
                      ● Configured (Enter new key to replace)
                    </span>
                  )}
                </div>
                <input
                  type="password"
                  value={openAlgoApiKeyInput}
                  onChange={(e) => onOpenAlgoApiKeyChange(e.target.value)}
                  placeholder={
                    openAlgoKeyConfigured
                      ? '•••••••• (Configured — enter new key to replace)'
                      : 'Enter OpenAlgo API key'
                  }
                  className="bg-terminal-bg border border-terminal-border px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-terminal-amber"
                />
                <span className="text-white/50 text-[10px]">From your OpenAlgo server config — authenticates order placement.</span>
              </label>
            </div>
          </div>
        </BentoCard>
      )}
    </>
  );
}
