'use client';

import React from 'react';
import { X, Settings as SettingsIcon } from 'lucide-react';
import type { SettingsTabId } from '@/store/terminalStore';

export const SETTINGS_TABS: { id: SettingsTabId; label: string }[] = [
  { id: 'workspace', label: 'WORKSPACE' },
  { id: 'connections', label: 'CONNECTIONS' },
  { id: 'intelligence', label: 'INTELLIGENCE' },
  { id: 'automation', label: 'AUTOMATION' },
  { id: 'system', label: 'SYSTEM' },
];

export function SettingsHeader({
  systemConfigSaveStatus,
  onClose,
}: {
  systemConfigSaveStatus: string | null;
  onClose: () => void;
}) {
  return (
    <div className="flex items-center justify-between px-5 py-3 border-b border-[#27272a] bg-[#121216] shrink-0">
      <div className="flex items-center gap-2.5">
        <div className="p-1.5 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
          <SettingsIcon className="w-4 h-4" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold tracking-wider text-white uppercase font-mono">
              TERMINAL SETTINGS
            </h2>
          </div>
          <p className="text-[11px] text-zinc-400 font-sans">
            Configure workspace layouts, broker connections, AI models, and market alerts.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {systemConfigSaveStatus ? (
          <span
            className={`text-[10px] animate-pulse ${
              systemConfigSaveStatus === 'Saved' ? 'text-terminal-green' : 'text-red-400'
            }`}
          >
            {systemConfigSaveStatus}
          </span>
        ) : (
          <span className="text-white/30 text-[10px] hidden sm:inline">Changes save automatically</span>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close settings"
          className="p-1.5 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
        >
          <X className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
}

export function SettingsTabBar({
  activeTab,
  onSelectTab,
}: {
  activeTab: SettingsTabId;
  onSelectTab: (tabId: SettingsTabId) => void;
}) {
  return (
    <div className="flex items-center border-b border-[#27272a] px-5 py-1 gap-1 shrink-0 bg-[#0c0c0f] flex-wrap">
      {SETTINGS_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onSelectTab(tab.id)}
          className={`px-3 py-1.5 text-xs font-mono transition-all duration-200 border rounded cursor-pointer ${
            activeTab === tab.id
              ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/10 font-bold'
              : 'border-transparent text-white/60 hover:text-white hover:bg-zinc-800/60'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function SettingsFooter({
  onClose,
}: {
  onClose: () => void;
}) {
  return (
    <div className="flex items-center justify-between px-5 py-2.5 border-t border-[#27272a] bg-[#0c0c0f] shrink-0 text-[11px] font-mono text-zinc-400">
      <div className="flex items-center gap-2">
        <span className="text-zinc-500">
          Press <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">ESC</kbd> to close
        </span>
        <span className="text-zinc-600">·</span>
        <span className="text-zinc-500">Changes apply immediately</span>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-white font-mono text-xs border border-zinc-700 transition-colors cursor-pointer"
      >
        [CLOSE]
      </button>
    </div>
  );
}
