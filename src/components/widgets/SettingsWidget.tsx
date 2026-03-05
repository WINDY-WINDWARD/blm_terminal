'use client';

import React from 'react';
import { useAtom } from 'jotai';
import { wsConnectedAtom, fundsAtom } from '@/store/terminalStore';

export function SettingsWidget() {
  const [wsConnected] = useAtom(wsConnectedAtom);
  const [funds] = useAtom(fundsAtom);

  const EXCHANGES = ['NSE', 'BSE', 'NFO', 'MCX', 'BFO', 'CDS'];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto p-3 gap-4">
      <div className="text-terminal-amber font-bold text-sm border-b border-terminal-gray pb-1">
        SETTINGS
      </div>

      {/* Connection Status */}
      <div className="flex flex-col gap-1">
        <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
          Connection
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              wsConnected ? 'bg-terminal-green' : 'bg-terminal-red'
            }`}
          />
          <span className={wsConnected ? 'text-terminal-green' : 'text-terminal-red'}>
            WebSocket: {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
          </span>
        </div>
        <div className="text-terminal-gray text-[10px]">
          OpenAlgo URL: {process.env.NEXT_PUBLIC_OPENALGO_URL ?? 'http://localhost:5000'}
        </div>
        <div className="text-terminal-gray text-[10px]">
          WebSocket: {process.env.NEXT_PUBLIC_OPENALGO_WS_URL ?? 'ws://localhost:8765'}
        </div>
      </div>

      {/* Funds */}
      {funds && (
        <div className="flex flex-col gap-1">
          <div className="text-terminal-amber font-bold uppercase text-[10px] tracking-widest mb-1">
            Account Funds
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            {[
              ['Available Cash', funds.availablecash],
              ['Collateral', funds.collateral],
              ['M2M Realized', funds.m2mrealized],
              ['M2M Unrealized', funds.m2munrealized],
              ['Utilised Debits', funds.utiliseddebits],
            ].map(([label, val]) => (
              <React.Fragment key={label}>
                <span className="text-terminal-gray">{label}:</span>
                <span className="text-terminal-amber text-right">{val}</span>
              </React.Fragment>
            ))}
          </div>
        </div>
      )}

      {/* Tips */}
      <div className="flex flex-col gap-0.5 mt-auto">
        <div className="text-terminal-gray text-[10px] border-t border-terminal-gray pt-2">
          Commands: CHART · WATCH · ORDER · POS · TOP · SETTINGS
        </div>
        <div className="text-terminal-gray text-[10px]">
          Press / or Escape to focus command bar
        </div>
        <div className="text-terminal-gray text-[10px]">
          F1 = BUY · F2 = SELL (in ORDER widget)
        </div>
      </div>
    </div>
  );
}
