'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  Loader2,
  RefreshCw,
  X,
  ShieldCheck,
} from 'lucide-react';
import { aiRoutesClient } from '@/lib/aiRoutesClient';
import { useInvalidateAiCaches } from '@/hooks/useAiRoutes';
import { useModalFocusTrap } from '@/hooks/useModalFocusTrap';
import { openLink } from '@/lib/openLink';
import type { OAuthPollResponse, OAuthStartResponse } from '@/types/aiRoutes';

interface OAuthSessionDialogProps {
  isOpen: boolean;
  provider: string;
  providerLabel: string;
  flow: 'browser' | 'device';
  replaceAccountId?: string | null;
  replaceAccountIdentity?: string | null;
  onClose: () => void;
  onSuccess?: (result: { accountId?: string; notice?: string | null }) => void;
}

export function OAuthSessionDialog({
  isOpen,
  provider,
  providerLabel,
  flow,
  replaceAccountId,
  replaceAccountIdentity,
  onClose,
  onSuccess,
}: OAuthSessionDialogProps) {
  const invalidateCaches = useInvalidateAiCaches();

  const [session, setSession] = useState<OAuthStartResponse | null>(null);
  const [pollStatus, setPollStatus] = useState<
    'initializing' | 'pending' | 'reconciling' | 'completed' | 'expired' | 'cancelled' | 'failed'
  >('initializing');
  const [pollResult, setPollResult] = useState<OAuthPollResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [remainingSecs, setRemainingSecs] = useState<number>(0);
  const [isCancelling, setIsCancelling] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);
  const [urlCopied, setUrlCopied] = useState(false);

  const modalRef = useRef<HTMLDivElement>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionRef = useRef<OAuthStartResponse | null>(null);
  sessionRef.current = session;

  const cleanupTimers = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
  }, []);

  // Initialize OAuth session
  const initSession = useCallback(async () => {
    cleanupTimers();
    setPollStatus('initializing');
    setErrorMsg(null);
    setPollResult(null);

    try {
      const startRes = await aiRoutesClient.startOAuth({
        provider,
        flow,
        replace_account_id: replaceAccountId || undefined,
      });
      setSession(startRes);
      setRemainingSecs(startRes.expires_in || 900);
      setPollStatus('pending');
    } catch (err) {
      setPollStatus('failed');
      setErrorMsg(err instanceof Error ? err.message : 'Failed to initiate OAuth flow');
    }
  }, [provider, flow, replaceAccountId, cleanupTimers]);

  useEffect(() => {
    if (isOpen) {
      initSession();
    } else {
      cleanupTimers();
      setSession(null);
      setPollStatus('initializing');
    }
    return () => cleanupTimers();
  }, [isOpen, initSession, cleanupTimers]);

  // Polling effect
  useEffect(() => {
    if (pollStatus !== 'pending' && pollStatus !== 'reconciling') {
      return;
    }
    const stateToken = session?.state;
    if (!stateToken) return;

    const intervalMs = Math.max(50, (session?.interval || 3) * 1000);

    const checkPoll = async () => {
      try {
        const res = await aiRoutesClient.pollOAuth(stateToken);
        if (res.status === 'completed') {
          cleanupTimers();
          setPollStatus('completed');
          setPollResult(res);
          invalidateCaches();
          onSuccess?.({ accountId: res.account_id, notice: res.notice });
        } else if (res.status === 'expired') {
          cleanupTimers();
          setPollStatus('expired');
        } else if (res.status === 'cancelled') {
          cleanupTimers();
          setPollStatus('cancelled');
        } else if (res.status === 'failed') {
          cleanupTimers();
          setPollStatus('failed');
          setErrorMsg(res.error || 'Authorization failed');
        } else if (res.status === 'reconciling') {
          setPollStatus('reconciling');
        }
      } catch (err) {
        if (err instanceof Error && err.message.includes('not found')) {
          cleanupTimers();
          setPollStatus('failed');
          setErrorMsg(err.message);
        }
      }
    };

    void checkPoll();
    pollTimerRef.current = setInterval(checkPoll, intervalMs);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [session, pollStatus, cleanupTimers, invalidateCaches, onSuccess]);

  // Countdown timer
  useEffect(() => {
    if (pollStatus !== 'pending' && pollStatus !== 'reconciling') return;

    countdownTimerRef.current = setInterval(() => {
      setRemainingSecs((prev) => {
        if (prev <= 1) {
          cleanupTimers();
          setPollStatus('expired');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
    };
  }, [pollStatus, cleanupTimers]);

  const handleCancel = useCallback(async () => {
    if (!sessionRef.current?.state) {
      onClose();
      return;
    }
    setIsCancelling(true);
    cleanupTimers();
    try {
      await aiRoutesClient.cancelOAuth(sessionRef.current.state);
      setPollStatus('cancelled');
    } catch {
      setPollStatus('cancelled');
    } finally {
      setIsCancelling(false);
    }
  }, [cleanupTimers, onClose]);

  const handleDismiss = useCallback(() => {
    if (sessionRef.current?.state && (pollStatus === 'pending' || pollStatus === 'reconciling')) {
      cleanupTimers();
      void aiRoutesClient.cancelOAuth(sessionRef.current.state).catch(() => {});
    }
    onClose();
  }, [pollStatus, cleanupTimers, onClose]);

  // Modal focus trap & scoped Escape handling
  useModalFocusTrap({
    id: 'oauth-session-dialog',
    isOpen,
    onClose: handleDismiss,
    containerRef: modalRef,
  });

  const handleCopyCode = () => {
    if (session?.user_code && typeof navigator !== 'undefined') {
      navigator.clipboard.writeText(session.user_code);
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 2000);
    }
  };

  const handleCopyUrl = () => {
    if (session?.auth_url && typeof navigator !== 'undefined') {
      navigator.clipboard.writeText(session.auth_url);
      setUrlCopied(true);
      setTimeout(() => setUrlCopied(false), 2000);
    }
  };

  if (!isOpen) return null;

  const formatCountdown = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const isReauth = Boolean(replaceAccountId);

  return (
    <div
      ref={modalRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="oauth-dialog-title"
      className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-150 select-none outline-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleDismiss();
      }}
    >
      <div className="relative w-full max-w-lg bg-[#0c0c0f] border border-[#27272a] rounded-lg shadow-2xl p-5 flex flex-col gap-4 text-zinc-200">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-[#27272a]">
          <div className="flex items-center gap-2">
            <span className="p-1 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber font-mono font-bold text-xs">
              OAUTH
            </span>
            <h3 id="oauth-dialog-title" className="text-sm font-mono font-bold tracking-wider uppercase text-white">
              {isReauth ? `Reauthenticate ${providerLabel}` : `Connect ${providerLabel}`}
            </h3>
          </div>
          <button
            type="button"
            onClick={handleDismiss}
            aria-label="Close OAuth dialog"
            className="text-zinc-400 hover:text-white p-1 rounded hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Reauth context warning */}
        {isReauth && replaceAccountIdentity && (
          <div className="text-[11px] font-mono p-2 rounded bg-zinc-900 border border-zinc-800 text-zinc-300">
            Reauthenticating account: <span className="text-terminal-amber font-bold">{replaceAccountIdentity}</span>
          </div>
        )}

        {/* Dialog Body by State */}
        <div className="flex flex-col gap-3 py-1 font-sans text-xs">
          {pollStatus === 'initializing' && (
            <div className="flex flex-col items-center justify-center py-8 gap-3 text-zinc-400">
              <Loader2 className="w-6 h-6 animate-spin text-terminal-amber" />
              <span className="font-mono text-xs">Initiating {flow} authorization session...</span>
            </div>
          )}

          {(pollStatus === 'pending' || pollStatus === 'reconciling') && (
            <>
              {flow === 'browser' ? (
                <div className="flex flex-col gap-3">
                  <p className="text-zinc-300 leading-relaxed">
                    Complete authorization in your system browser window. Your session will automatically verify and
                    connect once approved.
                  </p>

                  <div className="p-3 bg-zinc-900/80 border border-zinc-800 rounded flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-mono text-zinc-400">Authorization URL:</span>
                      <button
                        type="button"
                        onClick={handleCopyUrl}
                        className="text-[11px] font-mono text-terminal-amber hover:underline flex items-center gap-1 cursor-pointer"
                      >
                        {urlCopied ? (
                          <>
                            <Check className="w-3 h-3 text-terminal-green" /> Copied!
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3" /> Copy URL
                          </>
                        )}
                      </button>
                    </div>
                    {session?.auth_url && (
                      <button
                        type="button"
                        onClick={() => openLink(session.auth_url!, 'external')}
                        className="w-full py-2 px-3 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono font-bold text-xs flex items-center justify-center gap-2 transition-colors cursor-pointer"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        OPEN BROWSER TO LOGIN
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                /* Device Code Flow */
                <div className="flex flex-col gap-3">
                  <p className="text-zinc-300 leading-relaxed">
                    Follow these steps on your other device or browser to authorize:
                  </p>

                  {session?.user_code && (
                    <div className="p-4 bg-zinc-900 border border-zinc-700 rounded flex flex-col items-center gap-2">
                      <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                        Enter This One-Time Code:
                      </span>
                      <div className="text-2xl font-mono font-black tracking-widest text-terminal-amber py-1 px-4 rounded bg-black/60 border border-terminal-amber/40">
                        {session.user_code}
                      </div>
                      <button
                        type="button"
                        onClick={handleCopyCode}
                        className="mt-1 text-xs font-mono text-terminal-amber hover:underline flex items-center gap-1.5 cursor-pointer"
                      >
                        {codeCopied ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-terminal-green" /> Code Copied!
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" /> Copy Code
                          </>
                        )}
                      </button>
                    </div>
                  )}

                  {session?.verification_uri && (
                    <button
                      type="button"
                      onClick={() => openLink(session.verification_uri!, 'external')}
                      className="w-full py-2 px-3 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono font-bold text-xs flex items-center justify-center gap-2 transition-colors cursor-pointer"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      OPEN VERIFICATION PAGE
                    </button>
                  )}
                </div>
              )}

              {/* Waiting status indicator & countdown */}
              <div className="flex items-center justify-between p-2.5 bg-[#09090b] border border-zinc-800 rounded font-mono text-[11px] text-zinc-400">
                <div className="flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-terminal-amber" />
                  <span>{pollStatus === 'reconciling' ? 'Reconciling account...' : 'Waiting for approval...'}</span>
                </div>
                <div className="text-zinc-400">
                  Expires in: <span className="text-terminal-amber font-bold">{formatCountdown(remainingSecs)}</span>
                </div>
              </div>
            </>
          )}

          {pollStatus === 'completed' && (
            <div className="flex flex-col gap-3 py-2">
              <div className="flex items-center gap-3 p-3 bg-emerald-950/40 border border-emerald-800/60 rounded text-emerald-200">
                <ShieldCheck className="w-6 h-6 text-emerald-400 shrink-0" />
                <div className="flex flex-col">
                  <span className="font-mono font-bold text-xs uppercase tracking-wider text-emerald-400">
                    Account Connected Successfully
                  </span>
                  <span className="text-[11px] text-zinc-300 font-mono mt-0.5">
                    Identity: {pollResult?.masked_identity || 'Authenticated'}
                  </span>
                </div>
              </div>

              {/* REAUTH MISMATCH NOTICE */}
              {pollResult?.notice && (
                <div
                  data-testid="reauth-mismatch-notice"
                  className="p-3 bg-amber-950/60 border border-amber-500/50 rounded flex items-start gap-2.5 text-amber-200 leading-relaxed"
                >
                  <AlertTriangle className="w-5 h-5 text-terminal-amber shrink-0 mt-0.5" />
                  <div className="flex flex-col gap-0.5">
                    <span className="font-mono font-bold text-xs uppercase tracking-wider text-terminal-amber">
                      Identity Reconciliation Notice
                    </span>
                    <span className="text-xs text-zinc-300">{pollResult.notice}</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {pollStatus === 'expired' && (
            <div className="p-3 bg-zinc-900 border border-zinc-800 rounded flex flex-col gap-2 text-zinc-300">
              <div className="flex items-center gap-2 text-terminal-amber font-mono font-bold text-xs uppercase">
                <AlertTriangle className="w-4 h-4" />
                Session Expired
              </div>
              <p className="text-xs text-zinc-400">
                The authorization window has timed out. Please initiate a new session to authenticate.
              </p>
            </div>
          )}

          {pollStatus === 'cancelled' && (
            <div className="p-3 bg-zinc-900 border border-zinc-800 rounded flex flex-col gap-1 text-zinc-300 font-mono text-xs">
              <span className="text-zinc-400">OAuth session was cancelled.</span>
            </div>
          )}

          {pollStatus === 'failed' && (
            <div className="p-3 bg-rose-950/40 border border-rose-800/60 rounded flex flex-col gap-1.5 text-rose-200">
              <div className="flex items-center gap-2 text-rose-400 font-mono font-bold text-xs uppercase">
                <AlertTriangle className="w-4 h-4" />
                Authorization Failed
              </div>
              <p className="text-xs font-mono text-zinc-300">{errorMsg || 'An unexpected error occurred.'}</p>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between pt-3 border-t border-[#27272a]">
          {pollStatus === 'pending' || pollStatus === 'reconciling' ? (
            <>
              <div className="text-[10px] font-mono text-zinc-500">Zero secrets stored on renderer</div>
              <button
                type="button"
                onClick={handleCancel}
                disabled={isCancelling}
                className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-xs border border-zinc-700 transition-colors cursor-pointer"
              >
                {isCancelling ? 'Cancelling...' : 'Cancel Authorization'}
              </button>
            </>
          ) : (
            <>
              {(pollStatus === 'expired' || pollStatus === 'failed' || pollStatus === 'cancelled') && (
                <button
                  type="button"
                  onClick={initSession}
                  className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-white font-mono text-xs border border-zinc-700 transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Try Again
                </button>
              )}
              <div className="flex-1" />
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-1.5 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono font-bold text-xs transition-colors cursor-pointer"
              >
                Done
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
