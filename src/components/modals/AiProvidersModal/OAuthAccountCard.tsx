'use client';

import React, { useState, useEffect, useId } from 'react';
import {
  AlertTriangle,
  Check,
  Clock,
  KeyRound,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-react';
import {
  usePatchAccountMutation,
  useRefreshAccountMutation,
  useResetCooldownMutation,
  useRemoveAccountMutation,
  useTestAccountMutation,
} from '@/hooks/useAiRoutes';
import type { CredentialSummary } from '@/types/aiRoutes';

interface OAuthAccountCardProps {
  account: CredentialSummary;
  providerLabel: string;
  onReauth: (accountId: string, identity: string) => void;
}

function clampRoutingValue(value: number | null | undefined): number {
  if (!Number.isFinite(value)) return 1;
  return Math.max(1, Math.min(100, Math.floor(value ?? 1)));
}

export function OAuthAccountCard({ account, providerLabel, onReauth }: OAuthAccountCardProps) {
  const patchAccount = usePatchAccountMutation();
  const refreshAccount = useRefreshAccountMutation();
  const testAccount = useTestAccountMutation();
  const resetCooldown = useResetCooldownMutation();
  const removeAccount = useRemoveAccountMutation();

  const [priorityVal, setPriorityVal] = useState<number>(() => clampRoutingValue(account.priority));
  const [weightVal, setWeightVal] = useState<number>(() => clampRoutingValue(account.weight));
  const [testResult, setTestResult] = useState<{ status: string; latency_ms?: number; error?: string } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<boolean>(false);
  const routingHelpId = useId();

  // Sync state when props update from background refetch
  useEffect(() => {
    setPriorityVal(clampRoutingValue(account.priority));
  }, [account.priority]);

  useEffect(() => {
    setWeightVal(clampRoutingValue(account.weight));
  }, [account.weight]);

  const isCooldown = Boolean(account.cooldown) || account.status === 'cooldown';
  const isError = account.status === 'error' || Boolean(account.last_redacted_error);
  const isDisabled = !account.enabled;

  const handlePriorityChange = (newVal: number) => {
    if (!Number.isFinite(newVal)) {
      setPriorityVal(clampRoutingValue(account.priority));
      return;
    }
    const val = clampRoutingValue(newVal);
    setPriorityVal(val);
    patchAccount.mutate({ accountId: account.id, patch: { priority: val } });
  };

  const handleWeightChange = (newVal: number) => {
    if (!Number.isFinite(newVal)) {
      setWeightVal(clampRoutingValue(account.weight));
      return;
    }
    const val = clampRoutingValue(newVal);
    setWeightVal(val);
    patchAccount.mutate({ accountId: account.id, patch: { weight: val } });
  };

  const handlePriorityKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.currentTarget.blur();
      handlePriorityChange(priorityVal);
    }
  };

  const handleWeightKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.currentTarget.blur();
      handleWeightChange(weightVal);
    }
  };

  const handleToggleEnabled = () => {
    patchAccount.mutate({ accountId: account.id, patch: { enabled: !account.enabled } });
  };

  const handleTest = async () => {
    setTestResult(null);
    try {
      const res = await testAccount.mutateAsync(account.id);
      setTestResult(res);
      setTimeout(() => setTestResult(null), 5000);
    } catch (err) {
      setTestResult({
        status: 'error',
        error: err instanceof Error ? err.message : 'Test failed',
      });
      setTimeout(() => setTestResult(null), 5000);
    }
  };

  const handleRefresh = () => {
    refreshAccount.mutate(account.id);
  };

  const handleResetCooldown = () => {
    resetCooldown.mutate(account.id);
  };

  const handleRemove = () => {
    removeAccount.mutate(account.id);
    setConfirmRemove(false);
  };

  // Format cooldown expiration
  const renderCooldownInfo = () => {
    if (!account.cooldown) return null;
    const cdDate = new Date(account.cooldown);
    const now = new Date();
    const diffMs = cdDate.getTime() - now.getTime();
    if (diffMs <= 0) return 'Cooldown expired';
    const mins = Math.ceil(diffMs / 60000);
    return `Cooldown: ~${mins}m remaining`;
  };

  return (
    <div
      data-testid={`account-card-${account.id}`}
      className={`p-3 bg-[#0c0c0f] border rounded-md transition-colors flex flex-col gap-2.5 ${
        isDisabled
          ? 'border-zinc-800 opacity-70'
          : isError
          ? 'border-rose-900/60 bg-rose-950/10'
          : isCooldown
          ? 'border-amber-900/60 bg-amber-950/10'
          : 'border-[#27272a] hover:border-zinc-700'
      }`}
    >
      {/* Header: Identity + Status Badges */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <KeyRound className="w-4 h-4 text-terminal-amber shrink-0" />
          <div className="flex flex-col min-w-0">
            <span
              className="text-xs font-mono font-bold text-white truncate"
              data-testid="account-masked-identity"
              title={account.masked_identity}
            >
              {account.masked_identity}
            </span>
            <span className="text-[10px] font-mono text-zinc-500 truncate">ID: {account.id.slice(0, 8)}...</span>
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {/* Status Badge */}
          {isDisabled ? (
            <span
              data-testid="status-disabled"
              className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[10px] font-bold"
            >
              ○ DISABLED
            </span>
          ) : isCooldown ? (
            <span
              data-testid="status-cooldown"
              className="px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/80 text-amber-300 font-mono text-[10px] font-bold flex items-center gap-1"
            >
              <Clock className="w-3 h-3 text-terminal-amber" />
              COOLDOWN
            </span>
          ) : isError ? (
            <span
              data-testid="status-error"
              className="px-2 py-0.5 rounded bg-rose-950/60 border border-rose-800 text-rose-300 font-mono text-[10px] font-bold flex items-center gap-1"
            >
              <AlertTriangle className="w-3 h-3 text-rose-400" />
              ERROR
            </span>
          ) : (
            <span
              data-testid="status-active"
              className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/80 text-emerald-400 font-mono text-[10px] font-bold"
            >
              ● ACTIVE
            </span>
          )}

          {/* Enable/Disable Switch */}
          <button
            type="button"
            onClick={handleToggleEnabled}
            disabled={patchAccount.isPending}
            aria-label={account.enabled ? 'Disable account' : 'Enable account'}
            title={account.enabled ? 'Disable account' : 'Enable account'}
            className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold border transition-colors cursor-pointer ${
              account.enabled
                ? 'bg-emerald-900/30 border-emerald-700/60 text-emerald-300 hover:bg-emerald-800/40'
                : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-white'
            }`}
          >
            {account.enabled ? 'ENABLED' : 'PAUSED'}
          </button>
        </div>
      </div>

      {/* Cooldown or Error Banner */}
      {isCooldown && (
        <div className="flex items-center justify-between p-2 rounded bg-amber-950/30 border border-amber-900/40 text-[11px] font-mono text-amber-200">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-terminal-amber shrink-0" />
            <span>{renderCooldownInfo() || 'Account is currently on rate-limit cooldown.'}</span>
          </div>
          <button
            type="button"
            onClick={handleResetCooldown}
            data-testid="reset-cooldown-btn"
            disabled={resetCooldown.isPending}
            className="px-2 py-0.5 rounded bg-amber-900/60 hover:bg-amber-800/80 text-terminal-amber font-mono text-[10px] font-bold border border-amber-700 transition-colors cursor-pointer"
          >
            {resetCooldown.isPending ? 'Resetting...' : 'Reset Cooldown'}
          </button>
        </div>
      )}

      {isError && account.last_redacted_error && (
        <div className="p-2 rounded bg-rose-950/30 border border-rose-900/40 text-[11px] font-mono text-rose-300 leading-snug">
          <span className="font-bold text-rose-400 block mb-0.5">Last Redacted Error:</span>
          {account.last_redacted_error}
        </div>
      )}

      {/* Test Result Indicator */}
      {testResult && (
        <div
          data-testid="test-result-indicator"
          className={`p-2 rounded text-[11px] font-mono flex items-center justify-between ${
            testResult.status === 'ok'
              ? 'bg-emerald-950/50 border border-emerald-800 text-emerald-300'
              : 'bg-rose-950/50 border border-rose-800 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-1.5">
            {testResult.status === 'ok' ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
                <span>Account verified ({testResult.latency_ms ?? 0}ms)</span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                <span>{testResult.error || 'Verification failed'}</span>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() => setTestResult(null)}
            className="text-zinc-400 hover:text-white"
            aria-label="Dismiss test result"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Routing Controls & Action Buttons */}
      <div className="flex items-center justify-between gap-3 pt-2 border-t border-[#27272a]/80 flex-wrap">
        {/* Guided Priority & Weight */}
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 font-mono text-[11px] text-zinc-400">
            <span>Priority:</span>
            <input
              type="number"
              step="1"
              min="1"
              max="100"
              value={Number.isFinite(priorityVal) ? priorityVal : ''}
              onChange={(e) => {
                const value = e.currentTarget.valueAsNumber;
                setPriorityVal(Number.isFinite(value) ? clampRoutingValue(value) : Number.NaN);
              }}
              onBlur={() => handlePriorityChange(priorityVal)}
              onKeyDown={handlePriorityKeyDown}
              disabled={patchAccount.isPending}
              aria-label="Account Priority"
              aria-describedby={routingHelpId}
              title="Lower numbers are tried first."
              className="w-14 px-1.5 py-0.5 rounded bg-[#09090b] border border-zinc-700 text-white font-mono text-xs focus:border-terminal-amber outline-none"
            />
          </label>

          <label className="flex items-center gap-1.5 font-mono text-[11px] text-zinc-400">
            <span>Weight:</span>
            <input
              type="number"
              step="1"
              min="1"
              max="100"
              value={Number.isFinite(weightVal) ? weightVal : ''}
              onChange={(e) => {
                const value = e.currentTarget.valueAsNumber;
                setWeightVal(Number.isFinite(value) ? clampRoutingValue(value) : Number.NaN);
              }}
              onBlur={() => handleWeightChange(weightVal)}
              onKeyDown={handleWeightKeyDown}
              disabled={patchAccount.isPending}
              aria-label="Account Weight"
              aria-describedby={routingHelpId}
              title="Share of requests among accounts with equal priority."
              className="w-14 px-1.5 py-0.5 rounded bg-[#09090b] border border-zinc-700 text-white font-mono text-xs focus:border-terminal-amber outline-none"
            />
          </label>
        </div>
        <p id={routingHelpId} className="w-full text-[10px] leading-relaxed text-zinc-500">
          Priority - lower numbers are tried first. Weight - share of requests among accounts with equal priority.
        </p>

        {/* Action Buttons */}
        <div className="flex items-center gap-1.5 shrink-0 flex-wrap">
          {/* Test */}
          <button
            type="button"
            onClick={handleTest}
            disabled={testAccount.isPending || !account.enabled}
            title="Test account availability"
            className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-200 font-mono text-[10px] font-bold border border-zinc-700 transition-colors flex items-center gap-1 cursor-pointer"
          >
            {testAccount.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
            TEST
          </button>

          {/* Refresh */}
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshAccount.isPending}
            title="Refresh credential status"
            className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-200 font-mono text-[10px] font-bold border border-zinc-700 transition-colors flex items-center gap-1 cursor-pointer"
          >
            {refreshAccount.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3" />
            )}
            REFRESH
          </button>

          {/* Reauth */}
          <button
            type="button"
            onClick={() => onReauth(account.id, account.masked_identity)}
            title="Reauthenticate this account"
            className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-terminal-amber font-mono text-[10px] font-bold border border-terminal-amber/30 transition-colors flex items-center gap-1 cursor-pointer"
          >
            <RotateCcw className="w-3 h-3" />
            REAUTH
          </button>

          {/* Remove / Confirm Remove */}
          {confirmRemove ? (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleRemove}
                disabled={removeAccount.isPending}
                className="px-2 py-1 rounded bg-rose-800 hover:bg-rose-700 text-white font-mono text-[10px] font-bold transition-colors cursor-pointer"
              >
                {removeAccount.isPending ? 'Removing...' : 'CONFIRM'}
              </button>
              <button
                type="button"
                onClick={() => setConfirmRemove(false)}
                className="px-1.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 font-mono text-[10px] cursor-pointer"
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmRemove(true)}
              title="Remove account"
              aria-label="Remove account"
              className="p-1 rounded text-zinc-400 hover:text-rose-400 hover:bg-rose-950/40 transition-colors cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
