'use client';

import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BentoCard } from './BentoCard';

export interface CliproxyCoreStatus {
  installed_version: string | null;
  running_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  staged_version: string | null;
  pending_version: string | null;
  last_check_at: string | null;
  last_error: string | null;
  quarantined: string[];
  auto_update: boolean;
  core_root: string;
  binary_path: string | null;
  supervisor_state: string;
}

export function CliproxyCoreCard() {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: status,
    isLoading,
    isError,
    error,
  } = useQuery<CliproxyCoreStatus, Error>({
    queryKey: ['cliproxy', 'status'],
    queryFn: async () => {
      const res = await fetch('/api/py/cliproxy/status');
      if (!res.ok) {
        let detail = `Failed to fetch status (HTTP ${res.status})`;
        try {
          const errData = (await res.json()) as { detail?: string };
          if (errData && typeof errData.detail === 'string') {
            detail = errData.detail;
          }
        } catch {
          // ignore parse errors and use fallback detail
        }
        throw new Error(detail);
      }
      return (await res.json()) as CliproxyCoreStatus;
    },
  });

  const checkMutation = useMutation({
    mutationFn: async () => {
      setActionError(null);
      const res = await fetch('/api/py/cliproxy/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ download: true }),
      });
      if (!res.ok) {
        let detail = `Check failed (HTTP ${res.status})`;
        try {
          const errData = (await res.json()) as { detail?: string };
          if (errData && typeof errData.detail === 'string') {
            detail = errData.detail;
          }
        } catch {
          // ignore parse errors
        }
        throw new Error(detail);
      }
      return res.json();
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cliproxy', 'status'] });
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Check failed';
      setActionError(message);
    },
  });

  const activateMutation = useMutation({
    mutationFn: async () => {
      setActionError(null);
      const res = await fetch('/api/py/cliproxy/activate', {
        method: 'POST',
      });
      if (!res.ok) {
        let detail = `Activation failed (HTTP ${res.status})`;
        try {
          const errData = (await res.json()) as { detail?: string };
          if (errData && typeof errData.detail === 'string') {
            detail = errData.detail;
          }
        } catch {
          // ignore parse errors
        }
        throw new Error(detail);
      }
      return res.json();
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cliproxy', 'status'] });
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Activation failed';
      setActionError(message);
    },
  });

  const rollbackMutation = useMutation({
    mutationFn: async () => {
      setActionError(null);
      const res = await fetch('/api/py/cliproxy/rollback', {
        method: 'POST',
      });
      if (!res.ok) {
        let detail = `Rollback failed (HTTP ${res.status})`;
        try {
          const errData = (await res.json()) as { detail?: string };
          if (errData && typeof errData.detail === 'string') {
            detail = errData.detail;
          }
        } catch {
          // ignore parse errors
        }
        throw new Error(detail);
      }
      return res.json();
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cliproxy', 'status'] });
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Rollback failed';
      setActionError(message);
    },
  });

  const handleToggleAutoUpdate = (checked: boolean) => {
    queryClient.setQueryData<CliproxyCoreStatus | undefined>(['cliproxy', 'status'], (prev) =>
      prev ? { ...prev, auto_update: checked } : prev,
    );

    fetch('/api/py/system-config/cliproxy.auto_update', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: checked ? 'true' : 'false' }),
    })
      .then((res) => {
        if (!res.ok) {
          // ignore failure silently
          return;
        }
        void queryClient.invalidateQueries({ queryKey: ['cliproxy', 'status'] });
      })
      .catch(() => {
        // ignore failure silently
      });
  };

  const isAnyActionPending =
    checkMutation.isPending || activateMutation.isPending || rollbackMutation.isPending;

  return (
    <BentoCard
      icon="⚙"
      title="CLIProxyAPI core"
      blurb="Manage the standalone CLIProxyAPI binary core, inspect versions, check upstream releases, and activate or roll back updates."
      badge={
        <span
          className={`text-[10px] px-1.5 py-0.5 font-mono ${
            status?.installed_version
              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
              : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
          }`}
        >
          {status?.installed_version ? `v${status.installed_version}` : 'Not Installed'}
        </span>
      }
      className="col-span-1 md:col-span-2 lg:col-span-4"
    >
      <div className="flex flex-col gap-2.5 font-mono text-xs">
        {isLoading && <div className="text-zinc-400 text-[11px]">Loading CLIProxyAPI core status…</div>}

        {isError && (
          <div role="alert" className="text-red-400 text-[11px]">
            {error?.message ?? 'Failed to load CLIProxyAPI core status'}
          </div>
        )}

        {status && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-[11px]">
              <div>
                <span className="text-white/50">Installed version: </span>
                <span className="text-white">
                  {status.installed_version ?? 'not installed'}
                </span>
              </div>

              {status.running_version && status.running_version !== status.installed_version && (
                <div>
                  <span className="text-white/50">Running version: </span>
                  <span className="text-terminal-amber">{status.running_version}</span>
                </div>
              )}

              <div>
                <span className="text-white/50">Latest known version: </span>
                <span className="text-white">{status.latest_version ?? 'unknown'}</span>
              </div>

              <div>
                <span className="text-white/50">Last check: </span>
                <span className="text-white">
                  {status.last_check_at ? new Date(status.last_check_at).toLocaleString() : 'never'}
                </span>
              </div>
            </div>

            {status.staged_version && (
              <div className="text-[11px] text-terminal-amber bg-amber-950/30 border border-amber-800/40 px-2 py-1 rounded">
                Version {status.staged_version} is staged and activates on the next app start.
              </div>
            )}

            {status.last_error && (
              <div role="alert" className="text-[11px] text-red-400 bg-red-950/30 border border-red-800/40 px-2 py-1 rounded">
                Last error: {status.last_error}
              </div>
            )}

            {actionError && (
              <div role="alert" className="text-[11px] text-red-400 bg-red-950/30 border border-red-800/40 px-2 py-1 rounded">
                {actionError}
              </div>
            )}

            <div className="pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  aria-label="Automatic updates for CLIProxyAPI core"
                  checked={Boolean(status.auto_update)}
                  onChange={(e) => handleToggleAutoUpdate(e.target.checked)}
                  className="accent-terminal-amber cursor-pointer"
                />
                <span className="text-white/80 text-[11px]">Automatic updates</span>
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button"
                aria-label="Check for updates"
                onClick={() => checkMutation.mutate()}
                disabled={isAnyActionPending}
                className="px-2.5 py-1 text-[11px] font-mono rounded border border-blue-500 bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition shadow-sm"
              >
                {checkMutation.isPending ? 'Checking…' : 'Check for updates'}
              </button>

              {status.staged_version && (
                <button
                  type="button"
                  aria-label="Activate now"
                  onClick={() => activateMutation.mutate()}
                  disabled={isAnyActionPending}
                  className="px-2.5 py-1 text-[11px] font-mono rounded border border-terminal-amber/60 bg-terminal-amber/15 text-terminal-amber hover:bg-terminal-amber/25 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition"
                >
                  {activateMutation.isPending ? 'Activating…' : 'Activate now'}
                </button>
              )}

              <button
                type="button"
                aria-label="Roll back"
                onClick={() => rollbackMutation.mutate()}
                disabled={isAnyActionPending}
                className="px-2.5 py-1 text-[11px] font-mono rounded border border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition"
              >
                {rollbackMutation.isPending ? 'Rolling back…' : 'Roll back'}
              </button>
            </div>
          </>
        )}
      </div>
    </BentoCard>
  );
}
