'use client';

import React from 'react';
import { BentoCard } from './BentoCard';
import {
  NOTIF_CONFIG_KEYS,
  NOTIF_CONFIG_LABELS,
  type NotifConfigKey,
  type NotifConfigState,
} from './types';
import { NOTIF_CONFIG_HELP } from './BentoCard';

function ThresholdInputs({
  values,
  onChange,
  disabled,
}: {
  values: NotifConfigState;
  onChange: (key: NotifConfigKey, value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {NOTIF_CONFIG_KEYS.map((key) => (
        <label key={key} className="flex flex-col gap-1">
          <span className="text-terminal-amber text-[10px] uppercase tracking-widest">
            {NOTIF_CONFIG_LABELS[key]}
          </span>
          <input
            type="number"
            step="any"
            value={values[key]}
            disabled={disabled}
            onChange={(e) => onChange(key, e.target.value)}
            className="bg-black border border-terminal-gray text-white text-xs px-2 py-1 outline-none focus:border-terminal-amber disabled:opacity-60"
          />
          <span className="text-white/40 text-[9px] leading-snug">
            {NOTIF_CONFIG_HELP[key]}
          </span>
        </label>
      ))}
    </div>
  );
}

export interface AutomationTabProps {
  isAdmin: boolean;
  configLoading: boolean;
  configError: string | null;
  notifConfig: NotifConfigState;
  onNotifConfigChange: (key: NotifConfigKey, value: string) => void;
  onRetryConfig: () => void;
}

export function AutomationTab({
  isAdmin,
  configLoading,
  configError,
  notifConfig,
  onNotifConfigChange,
  onRetryConfig,
}: AutomationTabProps) {
  return (
    <>
      {isAdmin ? (
        <BentoCard
          icon="⚙"
          title="Global Scan Settings"
          blurb="Thresholds that trigger scanner alerts and notifications. Each field auto-saves and applies to future scans. Admin only."
          className="col-span-1 md:col-span-2 lg:col-span-4"
        >
          <div className="flex flex-col gap-1">
            {configLoading ? (
              <div className="text-white">Loading...</div>
            ) : (
              <>
                {configError && (
                  <div
                    role="alert"
                    className="flex items-center justify-between text-xs text-red-400 bg-red-950/40 border border-red-800/50 px-2.5 py-1.5 rounded mb-2"
                  >
                    <span>{configError}</span>
                    <button
                      type="button"
                      onClick={onRetryConfig}
                      className="text-terminal-amber underline hover:text-terminal-amber/80 cursor-pointer text-[11px] font-mono"
                    >
                      Retry
                    </button>
                  </div>
                )}
                <ThresholdInputs
                  values={notifConfig}
                  onChange={onNotifConfigChange}
                  disabled={configLoading}
                />
              </>
            )}
          </div>
        </BentoCard>
      ) : (
        <BentoCard
          icon="⚙"
          title="Global Scan Settings"
          className="col-span-1 md:col-span-2 lg:col-span-4"
        >
          <span className="text-white/50 text-[10px]">Admin access required to configure global scan thresholds.</span>
        </BentoCard>
      )}
    </>
  );
}
