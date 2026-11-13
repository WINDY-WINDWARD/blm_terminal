'use client';

import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
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
  rollback_available: boolean;
  supervisor_state: string;
}

type StatusTone = 'ok' | 'busy' | 'warn' | 'idle';

const TONE_CLASS: Record<StatusTone, string> = {
  ok: 'bg-emerald-950 text-emerald-400 border-emerald-800',
  busy: 'bg-sky-950 text-sky-400 border-sky-800',
  warn: 'bg-amber-950 text-amber-400 border-amber-800',
  idle: 'bg-zinc-800 text-zinc-400 border-zinc-700',
};

// One compact status chip replaces the duplicated version text. The body owns
// the version number, so the header only answers "is there work to do?".
function statusChip(status: CliproxyCoreStatus | undefined): { label: string; tone: StatusTone } {
  if (!status) return { label: 'CHECKING', tone: 'idle' };
  if (status.staged_version) return { label: 'STAGED', tone: 'warn' };
  if (status.update_available) return { label: 'UPDATE AVAILABLE', tone: 'busy' };
  if (!status.installed_version) return { label: 'NOT INSTALLED', tone: 'idle' };
  return { label: 'UP TO DATE', tone: 'ok' };
}

function formatChecked(value: string | null): string {
  if (!value) return 'never checked';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'never checked';
  return `checked ${date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })}`;
}

async function readError(response: Response, fallback: string): Promise<never> {
  let detail = fallback;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body && typeof body.detail === 'string') detail = body.detail;
  } catch {
    // keep the fallback message
  }
  throw new Error(detail);
}

function parseStatus(response: Response): Promise<CliproxyCoreStatus> {
  if (!response.ok) return readError(response, `Failed to load the core status (HTTP ${response.status})`);
  return response.json() as Promise<CliproxyCoreStatus>;
}

const ACTION_BUTTON =
  'px-2.5 py-1 text-[10px] font-mono font-bold rounded border transition-colors active:scale-[0.96] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer';
const PRIMARY_BUTTON = `${ACTION_BUTTON} bg-terminal-amber/10 hover:bg-terminal-amber/20 text-terminal-amber border-terminal-amber/40`;
const SOLID_BUTTON = `${ACTION_BUTTON} bg-terminal-amber hover:bg-amber-400 text-black border-terminal-amber`;
const QUIET_BUTTON = `${ACTION_BUTTON} bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white border-zinc-600`;

export function CliproxyCoreCard({ isAdmin = false }: { isAdmin?: boolean } = {}) {
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: status, isLoading, isError, error } = useQuery<CliproxyCoreStatus, Error>({
    queryKey: ['cliproxy', 'status'],
    queryFn: async () => parseStatus(await fetch('/api/py/cliproxy/status')),
  });

  const invalidateStatus = () => {
    void queryClient.invalidateQueries({ queryKey: ['cliproxy', 'status'] });
  };

  const checkMutation = useMutation({
    mutationFn: async () => {
      setActionError(null);
      const res = await fetch('/api/py/cliproxy/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ download: true }),
      });
      if (!res.ok) await readError(res, `Check failed (HTTP ${res.status})`);
      return res.json();
    },
    onSuccess: invalidateStatus,
    onError: (err: unknown) => setActionError(err instanceof Error ? err.message : 'Check failed'),
  });

  const activateMutation = useMutation({
    mutationFn: async () => {
      setActionError(null);
      const res = await fetch('/api/py/cliproxy/activate', { method: 'POST' });
      if (!res.ok) await readError(res, `Activation failed (HTTP ${res.status})`);
      return res.json();
    },
    onSuccess: invalidateStatus,
    onError: (err: unknown) => setActionError(err instanceof Error ? err.message : 'Activation failed'),
  });

  const rollbackMutation = useMutation({
    mutationFn: async () => {
      setActionError(null);
      const res = await fetch('/api/py/cliproxy/rollback', { method: 'POST' });
      if (!res.ok) await readError(res, `Rollback failed (HTTP ${res.status})`);
      return res.json();
    },
    onSuccess: invalidateStatus,
    onError: (err: unknown) => setActionError(err instanceof Error ? err.message : 'Rollback failed'),
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
      .then(async (res) => {
        if (!res.ok) await readError(res, `Could not save the automatic update setting (HTTP ${res.status})`);
        invalidateStatus();
      })
      .catch((err: unknown) => {
        setActionError(err instanceof Error ? err.message : 'Could not save the automatic update setting');
      });
  };

  const pending = checkMutation.isPending || activateMutation.isPending || rollbackMutation.isPending;
  const chip = statusChip(status);
  const message = actionError ?? status?.last_error ?? null;
  const versionDiffers =
    status?.running_version != null &&
    status?.installed_version != null &&
    status.running_version !== status.installed_version;
  const latestIsNewer =
    status?.latest_version != null &&
    status?.installed_version != null &&
    status.latest_version !== status.installed_version;

  return (
    <BentoCard
      icon="⚙"
      title="CLIProxyAPI core"
      blurb="The local model proxy. It updates itself from upstream, independently of the app."
      badge={
        <span className={`text-[10px] px-1.5 py-0.5 font-mono border ${TONE_CLASS[chip.tone]}`}>
          {chip.label}
        </span>
      }
      className="col-span-1 md:col-span-2 lg:col-span-2"
    >
      <div className="flex flex-col gap-2 font-mono">
        {isLoading && <span className="text-[10px] text-zinc-400">Loading core status…</span>}

        {isError && (
          <span role="alert" className="text-[10px] text-red-400">
            {error?.message ?? 'Failed to load the core status'}
          </span>
        )}

        {status && (
          <>
            <div className="flex flex-col gap-0.5">
              <div className="flex items-baseline gap-2">
                <span className="text-sm text-white tabular-nums">
                  {status.installed_version ? `v${status.installed_version}` : 'Not installed'}
                </span>
                {versionDiffers && (
                  <span className="text-[10px] text-terminal-amber tabular-nums">
                    running v{status.running_version}
                  </span>
                )}
                {latestIsNewer && (
                  <span className="text-[10px] text-white/50 tabular-nums">
                    latest v{status.latest_version}
                  </span>
                )}
              </div>
              <span className="text-[10px] text-white/40">{formatChecked(status.last_check_at)}</span>
            </div>

            {status.staged_version && (
              <div className="flex items-center justify-between gap-2 rounded border border-amber-800/50 bg-amber-950/30 px-2 py-1">
                <span className="text-[10px] text-amber-300">
                  v{status.staged_version} is ready. It activates at the next launch.
                </span>
              </div>
            )}

            {message && (
              <span
                role="alert"
                className="rounded border border-red-800/50 bg-red-950/30 px-2 py-1 text-[10px] text-red-400"
              >
                {message}
              </span>
            )}

            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => checkMutation.mutate()}
                disabled={pending}
                className={PRIMARY_BUTTON}
              >
                {checkMutation.isPending ? 'Checking…' : 'Check for updates'}
              </button>

              {status.staged_version && (
                <button
                  type="button"
                  onClick={() => activateMutation.mutate()}
                  disabled={pending}
                  className={SOLID_BUTTON}
                >
                  {activateMutation.isPending ? 'Activating…' : 'Activate now'}
                </button>
              )}

              {status.rollback_available && (
                <button
                  type="button"
                  onClick={() => rollbackMutation.mutate()}
                  disabled={pending}
                  className={QUIET_BUTTON}
                >
                  {rollbackMutation.isPending ? 'Rolling back…' : 'Roll back'}
                </button>
              )}
            </div>

            {isAdmin && (
              <label className="flex w-fit items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  aria-label="Automatic updates for the CLIProxyAPI core"
                  checked={Boolean(status.auto_update)}
                  onChange={(event) => handleToggleAutoUpdate(event.target.checked)}
                  className="h-3 w-3 accent-terminal-amber cursor-pointer"
                />
                <span className="text-[10px] text-white/60">Automatic updates</span>
              </label>
            )}
          </>
        )}
      </div>

      {status?.core_root && (
        <div
          className="mt-2 border-t border-white/5 pt-1.5 font-mono text-[9px] text-white/30 truncate"
          title={status.core_root}
        >
          {status.core_root}
        </div>
      )}
    </BentoCard>
  );
}
