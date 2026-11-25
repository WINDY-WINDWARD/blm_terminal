'use client';

import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, X } from 'lucide-react';
import { useModalFocusTrap } from '@/hooks/useModalFocusTrap';
import type { ProviderRiskInfo } from '@/types/aiRoutes';

interface ProviderRiskModalProps {
  isOpen: boolean;
  providerLabel: string;
  risk: ProviderRiskInfo | null;
  isPending: boolean;
  error: string | null;
  onAccept: () => void;
  onClose: () => void;
}

export function ProviderRiskModal({
  isOpen,
  providerLabel,
  risk,
  isPending,
  error,
  onAccept,
  onClose,
}: ProviderRiskModalProps) {
  const [accepted, setAccepted] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      setAccepted(false);
    }
  }, [isOpen]);

  useModalFocusTrap({
    id: 'provider-risk-modal',
    isOpen,
    onClose,
    containerRef: modalRef,
  });

  if (!isOpen || !risk) return null;

  return (
    <div
      ref={modalRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="provider-risk-title"
      data-testid="provider-risk-modal"
      className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-150 select-none outline-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-lg bg-[#0c0c0f] border border-rose-900/70 rounded-lg shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-rose-900/50 bg-rose-950/20">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="p-1.5 rounded bg-rose-950/60 border border-rose-800 text-rose-400 shrink-0">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h3
                id="provider-risk-title"
                className="text-sm font-mono font-bold tracking-wider uppercase text-rose-300"
              >
                {risk.title || 'DO NOT USE - HIGH RISK OF ACCOUNT BAN'}
              </h3>
              <p className="text-[11px] font-mono text-zinc-400 truncate">{providerLabel}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close risk warning"
            className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 flex flex-col gap-3 text-xs text-zinc-300 font-sans">
          <p className="leading-relaxed">{risk.message}</p>

          <ul className="flex flex-col gap-1.5 p-3 rounded bg-rose-950/20 border border-rose-900/40 text-rose-200 font-mono text-[11px] leading-relaxed">
            <li>• The provider can suspend or permanently ban the account.</li>
            <li>• A ban can also block other services tied to that account.</li>
            <li>• BLM Terminal cannot recover a banned account.</li>
            <li>• This route is disabled by default and stays disabled until you accept.</li>
          </ul>

          <label
            htmlFor="provider-risk-checkbox"
            className="flex items-start gap-2 p-3 rounded bg-zinc-900 border border-zinc-700 cursor-pointer hover:border-zinc-600"
          >
            <input
              id="provider-risk-checkbox"
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
              disabled={isPending}
              className="mt-0.5 w-4 h-4 shrink-0 accent-rose-500"
            />
            <span className="text-[11px] leading-relaxed text-zinc-200 font-mono">
              I understand the risk. I accept full responsibility. Enable {providerLabel} anyway.
            </span>
          </label>

          {error && (
            <div
              data-testid="provider-risk-error"
              className="p-2 rounded bg-rose-950/40 border border-rose-800 text-rose-200 font-mono text-[11px]"
            >
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[#27272a] bg-[#09090b]">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            data-testid="provider-risk-cancel"
            className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 text-zinc-200 font-mono text-[11px] font-bold border border-zinc-700 transition-colors cursor-pointer"
          >
            CANCEL
          </button>
          <button
            type="button"
            onClick={onAccept}
            disabled={!accepted || isPending}
            data-testid="provider-risk-accept"
            className="px-3 py-1.5 rounded bg-rose-700 hover:bg-rose-600 disabled:opacity-40 disabled:cursor-not-allowed text-white font-mono text-[11px] font-bold border border-rose-600 transition-colors flex items-center gap-1.5 cursor-pointer"
          >
            {isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <AlertTriangle className="w-3.5 h-3.5" />}
            {isPending ? 'RECORDING...' : 'I ACCEPT THE RISK'}
          </button>
        </div>
      </div>
    </div>
  );
}
