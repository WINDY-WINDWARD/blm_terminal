'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { AlertTriangle, Loader2, RefreshCw, X } from 'lucide-react';
import { useResetVaultMutation } from '@/hooks/useAiRoutes';
import { useModalFocusTrap } from '@/hooks/useModalFocusTrap';

interface VaultResetModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function VaultResetModal({ isOpen, onClose }: VaultResetModalProps) {
  const resetVault = useResetVaultMutation();
  const [confirmText, setConfirmText] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleClose = useCallback(() => {
    if (resetVault.isPending) return;
    setConfirmText('');
    setErrorMsg(null);
    onClose();
  }, [resetVault.isPending, onClose]);

  // Always reset input and error when modal visibility changes to false
  useEffect(() => {
    if (!isOpen) {
      setConfirmText('');
      setErrorMsg(null);
    }
  }, [isOpen]);

  useModalFocusTrap({
    id: 'vault-reset-modal',
    isOpen,
    onClose: handleClose,
    containerRef: modalRef,
    initialFocusRef: inputRef,
  });

  if (!isOpen) return null;

  const handleReset = async () => {
    setErrorMsg(null);
    try {
      await resetVault.mutateAsync();
      setConfirmText('');
      setErrorMsg(null);
      onClose();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Vault reset failed');
    }
  };

  const isConfirmed = confirmText.trim().toUpperCase() === 'RESET';

  return (
    <div
      ref={modalRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="vault-reset-title"
      className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-150 select-none outline-none"
      onClick={(e) => {
        if (e.target === e.currentTarget && !resetVault.isPending) handleClose();
      }}
    >
      <div className="relative w-full max-w-lg bg-[#0c0c0f] border border-rose-900/60 rounded-lg shadow-2xl p-5 flex flex-col gap-4 text-zinc-200">
        <div className="flex items-center justify-between pb-3 border-b border-[#27272a]">
          <div className="flex items-center gap-2.5 text-rose-400">
            <AlertTriangle className="w-5 h-5 shrink-0" />
            <h3 id="vault-reset-title" className="text-sm font-mono font-bold tracking-wider uppercase">
              RESET PROVIDER VAULT
            </h3>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={resetVault.isPending}
            aria-label="Close reset modal"
            className="text-zinc-400 hover:text-white p-1 rounded hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-col gap-2.5 text-xs text-zinc-300 leading-relaxed font-sans">
          <p>
            This action performs an <span className="text-rose-400 font-semibold">isolated provider vault reset</span>.
            It will:
          </p>
          <ul className="list-disc pl-5 flex flex-col gap-1 text-zinc-400 font-mono text-[11px]">
            <li>Clear all encrypted OAuth tokens and custom endpoint keys in the OS keyring vault.</li>
            <li>Delete all custom endpoint routes and account records.</li>
            <li>Re-seed clean OAuth provider route configurations.</li>
            <li>Stop the local proxy supervisor.</li>
          </ul>

          <div className="p-3 bg-emerald-950/40 border border-emerald-800/50 rounded text-emerald-200 text-[11px] font-mono">
            <span className="font-bold text-emerald-400 block mb-0.5">DIRECT PROVIDERS REMAIN USABLE</span>
            All direct API-key providers (Google AI Studio, Groq, NVIDIA NIM, OpenAI, etc.) and your primary terminal
            database remain completely untouched and functional.
          </div>

          {errorMsg && (
            <div className="p-2.5 bg-rose-950/50 border border-rose-800 text-rose-300 text-xs font-mono rounded">
              {errorMsg}
            </div>
          )}

          <div className="flex flex-col gap-1.5 mt-2">
            <label htmlFor="confirm-reset-input" className="text-[11px] font-mono text-zinc-400">
              Type <span className="text-rose-400 font-bold">RESET</span> to confirm:
            </label>
            <input
              ref={inputRef}
              id="confirm-reset-input"
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="RESET"
              disabled={resetVault.isPending}
              className="bg-[#09090b] border border-zinc-700 px-3 py-1.5 rounded font-mono text-xs text-white focus:outline-none focus:border-rose-500"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-[#27272a]">
          <button
            type="button"
            onClick={handleClose}
            disabled={resetVault.isPending}
            className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-xs border border-zinc-700 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleReset}
            data-testid="confirm-vault-reset-btn"
            disabled={!isConfirmed || resetVault.isPending}
            className="px-4 py-1.5 rounded bg-rose-700 hover:bg-rose-600 disabled:opacity-40 disabled:hover:bg-rose-700 text-white font-mono text-xs font-bold transition-colors flex items-center gap-1.5 cursor-pointer"
          >
            {resetVault.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Resetting Vault...
              </>
            ) : (
              <>
                <RefreshCw className="w-3.5 h-3.5" />
                Reset Provider Vault
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
