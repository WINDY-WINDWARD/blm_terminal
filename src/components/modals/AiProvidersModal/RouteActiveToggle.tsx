'use client';

import React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface RouteActiveToggleProps {
  enabled: boolean;
  isDefault: boolean;
  configured?: boolean;
  isPending?: boolean;
  testId?: string;
  onToggle: () => void;
  onMakeDefault?: () => void;
}

export function RouteActiveToggle({
  enabled,
  isDefault,
  configured = true,
  isPending = false,
  testId,
  onToggle,
  onMakeDefault,
}: RouteActiveToggleProps) {
  if (!configured) {
    return (
      <span
        data-testid={testId}
        title="Add an account or API key to activate this provider"
        className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-500 font-mono text-[10px] font-bold tracking-wider select-none"
      >
        NO ACCOUNTS
      </span>
    );
  }

  return (
    <div data-testid={testId} className="flex items-center gap-1.5 shrink-0">
      <button
        type="button"
        onClick={onToggle}
        disabled={isPending}
        aria-label={enabled ? 'Deactivate provider' : 'Activate provider'}
        title={enabled ? 'Click to deactivate' : 'Click to activate'}
        className={cn(
          'px-2 py-0.5 rounded font-mono text-[10px] font-bold border transition-colors flex items-center gap-1 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed',
          enabled
            ? 'bg-emerald-950/60 border-emerald-800/80 text-emerald-400 hover:bg-emerald-900/60 hover:border-emerald-700'
            : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-600',
        )}
      >
        {isPending && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
        {enabled ? 'ACTIVE' : 'INACTIVE'}
      </button>

      {enabled && isDefault && (
        <span
          data-testid="default-chip"
          className="px-1.5 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300 font-mono text-[9px] font-bold uppercase tracking-wider select-none"
        >
          DEFAULT
        </span>
      )}

      {enabled && !isDefault && onMakeDefault && (
        <button
          type="button"
          onClick={onMakeDefault}
          disabled={isPending}
          aria-label="Set as default provider"
          className="text-[10px] font-mono text-zinc-400 hover:text-terminal-amber underline decoration-dotted transition-colors cursor-pointer bg-transparent border-none p-0 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Set as default
        </button>
      )}
    </div>
  );
}
