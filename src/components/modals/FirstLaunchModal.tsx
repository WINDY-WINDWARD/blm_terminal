'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useAtom } from 'jotai';
import { useQueryClient } from '@tanstack/react-query';
import {
  advancedScrapingConsentAtom,
  authAtom,
  onboardingCompletedAtom,
  tutorialStatusAtom,
} from '@/store/terminalStore';
import {
  checkAiStatus,
  checkBackendHealth,
  checkGeminiOAuthStatus,
  completeFirstBoot,
  fetchProviderModels,
  getFirstBootStatus,
  getSetupStatus,
  initiateGeminiOAuth,
  loginWithPassword,
  postScrapingConsent,
  saveSystemConfig,
  setupFirstAdmin,
  type AiStatus,
  type HealthResult,
  type ProviderModel,
} from '@/lib/onboarding';
import { AI_PROVIDERS, AI_PROVIDER_MAP } from '@/lib/aiProviders';
import { ENGINE_WARM_LIMIT, useWarmupMessage } from '@/components/EngineWarmup';
import { ModelCombobox } from '@/components/ModelCombobox';
import { AiProviderInstructions } from '@/components/AiProviderInstructions';

type StepId = 'welcome' | 'backend' | 'admin' | 'consent' | 'ai' | 'models' | 'done';

const STEPS: { id: StepId; label: string }[] = [
  { id: 'welcome', label: 'Welcome' },
  { id: 'backend', label: 'Backend' },
  { id: 'admin', label: 'Admin' },
  { id: 'consent', label: 'Privacy' },
  { id: 'ai', label: 'AI' },
  { id: 'models', label: 'Models' },
  { id: 'done', label: 'Done' },
];

function errText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message || fallback : fallback;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-terminal-muted mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls =
  'w-full bg-terminal-bg border border-terminal-border p-2 text-terminal-amber text-sm focus:outline-none focus:border-terminal-amber focus:ring-1 focus:ring-terminal-amber transition-colors';

export function FirstLaunchModal() {
  const [completed, setCompleted] = useAtom(onboardingCompletedAtom);
  const [, setTutorialStatus] = useAtom(tutorialStatusAtom);
  const [auth, setAuth] = useAtom(authAtom);
  const [consent, setConsent] = useAtom(advancedScrapingConsentAtom);
  const queryClient = useQueryClient();

  const [mounted, setMounted] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);

  // backend step
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [healthChecking, setHealthChecking] = useState(false);
  const [healthAttempts, setHealthAttempts] = useState(0);

  // admin step
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [setupError, setSetupError] = useState('');
  const [adminUser, setAdminUser] = useState('admin');
  const [adminPass, setAdminPass] = useState('');
  const [adminPass2, setAdminPass2] = useState('');
  const [adminBusy, setAdminBusy] = useState(false);

  // consent step
  const [consentChoice, setConsentChoice] = useState<boolean | null>(null);
  const [consentBusy, setConsentBusy] = useState(false);
  const [consentError, setConsentError] = useState('');

  // ai step
  const [aiProvider, setAiProvider] = useState('aistudio');
  const [aiKey, setAiKey] = useState('');
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState('');
  const geminiPollRef = useRef<NodeJS.Timeout | null>(null);
  const keyDebounceRef = useRef<NodeJS.Timeout | null>(null);
  // Guards async continuations (debounced saves, OAuth polling) against
  // setting state after the modal unmounts.
  const isMountedRef = useRef(true);
  // background worker (AI picks) model selection
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [hunterModel, setHunterModel] = useState('');
  const [verifierModel, setVerifierModel] = useState('');

  useEffect(() => {
    setMounted(true);
    // Config-table check: onboarding may have completed in a previous
    // install/session whose localStorage is gone (ephemeral ports, reinstall).
    // Backend is source of truth; local atom is the fast-path cache.
    getFirstBootStatus()
      .then((s) => {
        if (isMountedRef.current && s.onboardingCompleted) setCompleted(true);
      })
      .catch(() => {});
    return () => {
      isMountedRef.current = false;
      if (geminiPollRef.current) {
        clearInterval(geminiPollRef.current);
        geminiPollRef.current = null;
      }
      if (keyDebounceRef.current) {
        clearTimeout(keyDebounceRef.current);
        keyDebounceRef.current = null;
      }
    };
  }, []);

  const step = STEPS[stepIdx].id;

  // Still in the warm-up window (no result yet, or failing for less than
  // ENGINE_WARM_LIMIT probes) — show lively loading copy instead of an error.
  const warming =
    step === 'backend' &&
    (!health || (!health.ok && healthAttempts < ENGINE_WARM_LIMIT));
  const warmupMsg = useWarmupMessage(mounted && !completed && warming);

  const recordHealth = (st: HealthResult) => {
    setHealth(st);
    if (st.ok) {
      setHealthAttempts(0);
    } else {
      setHealthAttempts((n) => n + 1);
    }
  };

  // Lazily probe when entering gated steps
  useEffect(() => {
    if (!mounted || completed) return;
    if (step === 'backend' && health === null && !healthChecking) {
      setHealthChecking(true);
      checkBackendHealth()
        .then(recordHealth)
        .finally(() => setHealthChecking(false));
    }
    if (step === 'admin' && needsSetup === null && !auth) {
      getSetupStatus()
        .then((s) => setNeedsSetup(s.needsSetup))
        .catch((err: unknown) => setSetupError(errText(err, 'Could not reach the backend.')));
    }
    if (step === 'ai' && aiStatus === null) {
      checkAiStatus()
        .then(setAiStatus)
        .catch(() => setAiStatus(null));
    }
    // Entering the models step: pull the provider's live catalog (once the
    // provider is set up) so the hunter/verifier pickers have options.
    if (step === 'models' && providerModels.length === 0 && !modelsLoading) {
      void (async () => {
        try {
          const st = aiStatus ?? (await checkAiStatus());
          if (!isMountedRef.current) return;
          if (st) setAiStatus(st);
          if (st?.isConfigured && aiProvider !== 'codex') {
            const key = aiProvider === 'gemini' ? '' : aiKey;
            await loadProviderModels(aiProvider, key);
          }
        } catch {
          // loadProviderModels already clears the list on failure.
        }
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, mounted, completed]);

  // Auto-retry the engine probe while it keeps failing. The packaged
  // backend can take 30-90s to boot on first launch, and the one-shot
  // probe above never refires on its own (health stays non-null), which
  // used to leave users permanently stuck on the error state.
  // NOTE: this hook must stay above the early return below — a hook after
  // a conditional return crashes React (#310, more hooks than last render).
  useEffect(() => {
    if (!mounted || completed || step !== 'backend') return;
    if (!health || health.ok || healthChecking) return;
    const t = setTimeout(() => {
      setHealthChecking(true);
      setHealth(null);
      checkBackendHealth()
        .then(recordHealth)
        .finally(() => setHealthChecking(false));
    }, 5000);
    return () => clearTimeout(t);
  });

  if (!mounted || completed) return null;

  const runBackendCheck = () => {
    setHealthChecking(true);
    setHealth(null);
    checkBackendHealth()
      .then(recordHealth)
      .finally(() => setHealthChecking(false));
  };

  const applyAuth = (next: { user: { id: number; username: string; is_admin: boolean } }) => {
    setAuth(next);
    queryClient.invalidateQueries();
  };

  const handleCreateAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    setSetupError('');
    if (adminPass.length < 8) {
      setSetupError('Password must be at least 8 characters.');
      return;
    }
    if (adminPass !== adminPass2) {
      setSetupError('Passwords do not match.');
      return;
    }
    setAdminBusy(true);
    try {
      applyAuth(await setupFirstAdmin(adminUser.trim() || 'admin', adminPass));
    } catch (err: unknown) {
      const msg = errText(err, 'Setup failed');
      setSetupError(msg);
      if (msg.includes('already completed')) setNeedsSetup(false);
    } finally {
      setAdminBusy(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setSetupError('');
    setAdminBusy(true);
    try {
      applyAuth(await loginWithPassword(adminUser, adminPass));
    } catch (err: unknown) {
      setSetupError(errText(err, 'Login failed'));
    } finally {
      setAdminBusy(false);
    }
  };

  const handleConsent = async (value: boolean) => {
    setConsentChoice(value);
    setConsentError('');
    setConsentBusy(true);
    try {
      await postScrapingConsent(value);
      setConsent(value);
      if (value) {
        // When user agrees, immediately advance to next step without asking to continue
        setStepIdx((i) => Math.min(i + 1, STEPS.length - 1));
      }
    } catch (err: unknown) {
      setConsentError(errText(err, 'Could not save consent'));
    } finally {
      setConsentBusy(false);
    }
  };

  // Maps a provider id to its system_config API-key slot (null = no key needed).
  // Labels/placeholders come from the shared aiProviders meta (same as Settings).
  const providerKeySlot = (p: string): string | null =>
    AI_PROVIDER_MAP[p]?.credentialDbKey ?? null;

  const providerKeyLabel = (p: string): string =>
    AI_PROVIDER_MAP[p]?.credentialLabel?.toUpperCase() ?? 'API KEY';

  const providerKeyPlaceholder = (p: string): string =>
    AI_PROVIDER_MAP[p]?.placeholder ?? 'sk-…';

  // Load the provider's model catalog for the hunter/verifier pickers.
  const loadProviderModels = async (provider: string, key: string) => {
    setModelsLoading(true);
    try {
      const models = await fetchProviderModels(provider, key);
      if (isMountedRef.current) setProviderModels(models);
    } catch {
      if (isMountedRef.current) setProviderModels([]);
    } finally {
      if (isMountedRef.current) setModelsLoading(false);
    }
  };

  const handleWorkerModelChange = async (slot: 'ai.hunter_model' | 'ai.verifier_model', value: string) => {
    if (slot === 'ai.hunter_model') setHunterModel(value);
    else setVerifierModel(value);
    try {
      await saveSystemConfig(slot, value);
    } catch (err: unknown) {
      if (isMountedRef.current) setAiMsg(errText(err, 'Could not save worker model'));
    }
  };

  const handleProviderChange = (newProvider: string) => {
    if (geminiPollRef.current) {
      clearInterval(geminiPollRef.current);
      geminiPollRef.current = null;
    }
    setAiProvider(newProvider);
    setAiMsg('');
    setAiBusy(false);
    setAiKey('');
    setProviderModels([]);
    setHunterModel('');
    setVerifierModel('');
    if (newProvider === 'codex') {
      // Codex connects via browser sign-in in Settings — there is no key
      // field on this screen, so persist the choice immediately or it is lost.
      setAiBusy(true);
      saveSystemConfig('ai.provider', 'codex')
        .then(() => checkAiStatus())
        .then((st) => {
          if (!isMountedRef.current) return;
          setAiStatus(st);
          setAiMsg('Codex selected — connect it in Settings → AI after setup.');
        })
        .catch((err: unknown) => { if (isMountedRef.current) setAiMsg(errText(err, 'Could not save provider')); })
        .finally(() => { if (isMountedRef.current) setAiBusy(false); });
    }
  };

  const handleGeminiLogin = async () => {
    setAiMsg('');
    setAiBusy(true);
    if (geminiPollRef.current) {
      clearInterval(geminiPollRef.current);
      geminiPollRef.current = null;
    }
    try {
      const authUrl = await initiateGeminiOAuth();
      window.open(authUrl, '_blank');
      setAiMsg('Awaiting Google OAuth... Complete sign-in in your browser window.');
      geminiPollRef.current = setInterval(async () => {
        if (!isMountedRef.current) {
          if (geminiPollRef.current) {
            clearInterval(geminiPollRef.current);
            geminiPollRef.current = null;
          }
          return;
        }
        try {
          const status = await checkGeminiOAuthStatus();
          if (status.configured && status.hasRefreshToken) {
            if (geminiPollRef.current) {
              clearInterval(geminiPollRef.current);
              geminiPollRef.current = null;
            }
            await saveSystemConfig('ai.provider', 'gemini');
            const st = await checkAiStatus();
            if (!isMountedRef.current) return;
            setAiStatus(st);
            setAiMsg('Gemini connected successfully!');
            setAiBusy(false);
            if (st.isConfigured) void loadProviderModels('gemini', '');
          }
        } catch {
          // Keep polling
        }
      }, 2500);
    } catch (err: unknown) {
      if (!isMountedRef.current) return;
      setAiBusy(false);
      setAiMsg(errText(err, 'Failed to initiate Google OAuth'));
    }
  };

  const handleKeyChange = (val: string) => {
    setAiKey(val);
    setAiMsg('');
    if (keyDebounceRef.current) clearTimeout(keyDebounceRef.current);
    const trimmed = val.trim();
    if (!trimmed) {
      setAiStatus({ provider: aiProvider, isConfigured: false });
      return;
    }
    setAiBusy(true);
    keyDebounceRef.current = setTimeout(async () => {
      try {
        await saveSystemConfig('ai.provider', aiProvider);
        const slot = providerKeySlot(aiProvider);
        if (slot) await saveSystemConfig(slot, trimmed);
        const st = await checkAiStatus();
        if (!isMountedRef.current) return;
        setAiStatus(st);
        setAiMsg(st.isConfigured ? 'Connected successfully.' : '');
        if (st.isConfigured) void loadProviderModels(aiProvider, trimmed);
        else setProviderModels([]);
      } catch (err: unknown) {
        if (isMountedRef.current) setAiMsg(errText(err, 'Could not save AI key'));
      } finally {
        if (isMountedRef.current) setAiBusy(false);
      }
    }, 400);
  };

  const finish = () => {
    setTutorialStatus('active');
    setCompleted(true);
    // Persist to the backend config table (survives origin changes); the
    // local atom write above keeps the UI instant. Best-effort only.
    completeFirstBoot().catch(() => {});
  };

  const canContinue =
    step === 'welcome' ||
    (step === 'backend' && health?.ok === true) ||
    (step === 'admin' && auth !== null) ||
    (step === 'consent' && consent !== null && !consentBusy) ||
    step === 'ai' ||
    step === 'models' ||
    step === 'done';

  const next = () => setStepIdx((i) => Math.min(i + 1, STEPS.length - 1));
  const back = () => setStepIdx((i) => Math.max(i - 1, 0));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded border border-[#2d3139] bg-[#121418] p-6 text-[#e1e4ea] shadow-2xl font-mono max-h-[90vh] overflow-y-auto">
        <div className="text-center mb-4">
          <h2 className="text-xl text-terminal-amber font-bold tracking-wider">BLM TERMINAL</h2>
          <p className="text-xs text-terminal-muted mt-1">FIRST-TIME SETUP · STEP {stepIdx + 1} OF {STEPS.length}</p>
        </div>

        <div className="flex items-center gap-1.5 mb-6" data-tour="setup-progress">
          {STEPS.map((s, i) => (
            <div
              key={s.id}
              title={s.label}
              className={`h-1.5 flex-1 rounded ${i <= stepIdx ? 'bg-terminal-amber' : 'bg-terminal-border'}`}
            />
          ))}
        </div>

        {step === 'welcome' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">Welcome to BLM Terminal.</p>
            <p className="text-xs text-terminal-muted leading-relaxed">
              Welcome to the future of financial intelligence. In a few quick steps,
              we'll activate your real-time analytics engine.
            </p>
          </div>
        )}

        {step === 'backend' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">Checking engine status</p>
            <p className="text-xs text-terminal-muted leading-relaxed">
              Connecting to the local analytics and data processing engine.
            </p>
            {health?.ok ? (
              <div className="p-2 text-xs border bg-green-900/40 border-green-600 text-green-200">
                Engine active
              </div>
            ) : warming ? (
              <div className="rounded bg-[#1a1d23] border border-[#2d3139] p-3 flex items-center gap-3">
                <span className="h-6 w-6 shrink-0 rounded-full border-2 border-[#2d3139] border-t-terminal-amber animate-spin" />
                <div>
                  <p key={warmupMsg} className="text-xs text-terminal-amber animate-pulse leading-relaxed">
                    {warmupMsg}
                  </p>
                  <p className="text-[11px] text-terminal-muted mt-1 leading-relaxed">
                    First boot can take up to ~90 seconds. Retrying automatically…
                  </p>
                </div>
              </div>
            ) : (
              <>
                {health && (
                  <div className="p-2 text-xs border bg-red-900/50 border-red-500 text-red-200">
                    {health.message}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={runBackendCheck}
                    disabled={healthChecking}
                    className="rounded px-4 py-2 text-xs font-medium text-[#9ca3af] hover:text-white bg-[#1a1d23] hover:bg-[#252830] transition border border-[#2d3139] disabled:opacity-50"
                  >
                    {healthChecking ? 'Checking…' : 'Retry check'}
                  </button>
                  <span className="text-[11px] text-terminal-muted">Retrying automatically every 5s…</span>
                </div>
              </>
            )}
          </div>
        )}

        {step === 'admin' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">
              {needsSetup === false ? 'Log in' : 'Create your administrator account'}
            </p>
            {needsSetup === null && !setupError && (
              <p className="text-xs text-terminal-amber animate-pulse">CHECKING…</p>
            )}
            {setupError && (
              <div className="p-2 bg-red-900/50 border border-red-500 text-red-200 text-xs">{setupError}</div>
            )}
            {auth ? (
              <div className="p-2 bg-green-900/40 border border-green-600 text-green-200 text-xs">
                Signed in as {auth.user.username} (admin). You can continue.
              </div>
            ) : (
              needsSetup !== null && (
                <form onSubmit={needsSetup ? handleCreateAdmin : handleLogin} className="space-y-3">
                  {needsSetup && (
                    <p className="text-xs text-terminal-muted leading-relaxed">
                      First boot: no accounts exist yet. Create the admin account that will own
                      OpenAlgo, AI, and scan settings.
                    </p>
                  )}
                  <Field label="USERNAME">
                    <input
                      type="text"
                      value={adminUser}
                      onChange={(e) => setAdminUser(e.target.value)}
                      className={inputCls}
                      required
                      minLength={3}
                      maxLength={64}
                      autoFocus
                    />
                  </Field>
                  <Field label="PASSWORD (MIN 8 CHARACTERS)">
                    <input
                      type="password"
                      value={adminPass}
                      onChange={(e) => setAdminPass(e.target.value)}
                      className={inputCls}
                      required
                      minLength={needsSetup ? 8 : 1}
                    />
                  </Field>
                  {needsSetup && (
                    <Field label="CONFIRM PASSWORD">
                      <input
                        type="password"
                        value={adminPass2}
                        onChange={(e) => setAdminPass2(e.target.value)}
                        className={inputCls}
                        required
                        minLength={8}
                      />
                    </Field>
                  )}
                  <button
                    type="submit"
                    disabled={adminBusy}
                    className="w-full bg-terminal-amber text-terminal-bg font-bold py-2 px-4 hover:bg-yellow-500 disabled:opacity-50 transition-colors text-sm"
                  >
                    {adminBusy ? 'WORKING…' : needsSetup ? 'CREATE ADMIN & CONTINUE' : 'LOGIN'}
                  </button>
                </form>
              )
            )}
          </div>
        )}

        {step === 'consent' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">Data extraction & privacy</p>
            <div className="rounded bg-[#1a1d23] p-3 text-xs leading-relaxed text-[#d1d5db] border border-[#2d3139] select-text">
              This software contains generic web automation capabilities. By enabling Advanced
              Extraction, you authorize the software to navigate target websites on your behalf.
              You warrant that you have the legal right to access this data and assume all legal
              liability for its extraction.
            </div>
            {consentError && (
              <div className="p-2 bg-red-900/50 border border-red-500 text-red-200 text-xs">{consentError}</div>
            )}
            {consent !== null && !consentError && (
              <div className="p-2 bg-green-900/40 border border-green-600 text-green-200 text-xs">
                Choice saved: {consent ? 'Advanced Extraction enabled.' : 'Safe Mode (extraction disabled).'}
              </div>
            )}
            <div className="flex gap-2.5 pt-1">
              <button
                type="button"
                onClick={() => void handleConsent(false)}
                disabled={consentBusy}
                className="px-3.5 py-2.5 text-xs font-medium border border-terminal-border text-terminal-muted hover:text-white bg-[#1a1d23] hover:bg-[#252830] transition rounded disabled:opacity-50"
              >
                Decline (Safe Mode)
              </button>
              <button
                type="button"
                onClick={() => void handleConsent(true)}
                disabled={consentBusy}
                className="flex-1 px-4 py-2.5 text-xs font-bold bg-terminal-amber text-terminal-bg hover:bg-yellow-400 border border-terminal-amber rounded shadow-[0_0_15px_rgba(245,158,11,0.35)] hover:shadow-[0_0_20px_rgba(245,158,11,0.5)] transition-all disabled:opacity-50 flex items-center justify-center gap-1.5 uppercase tracking-wider"
              >
                {consentBusy ? 'Enabling…' : '★ I Agree, Enable'}
              </button>
            </div>
          </div>
        )}

        {step === 'ai' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">AI assistant (optional)</p>
            <div className="rounded bg-[#1a1d23] p-3 text-xs leading-relaxed text-[#d1d5db] border border-[#2d3139]">
              Please note: the best results come from a paid subscription provider
              or a pay-as-you-go API provider. Free models work well too, depending
              on the provider and model — if you want a free option, grab a free
              key from Google AI Studio.
            </div>
            {aiStatus && (
              <div
                className={`p-2 text-xs border ${aiStatus.isConfigured ? 'bg-green-900/40 border-green-600 text-green-200' : 'bg-[#1a1d23] border-terminal-border text-terminal-muted'}`}
              >
                Status: {aiStatus.isConfigured ? 'connected' : 'not configured'}
              </div>
            )}
            <Field label="PROVIDER">
              <select
                value={aiProvider}
                onChange={(e) => handleProviderChange(e.target.value)}
                className={`${inputCls} [&>option]:bg-terminal-bg`}
              >
                {AI_PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </Field>
            {aiProvider === 'gemini' ? (
              <div className="space-y-2 pt-1">
                <p className="text-xs text-terminal-muted leading-relaxed">
                  Use your existing Google subscription via the Google Antigravity proxy —
                  no API key needed. Sign in with your Google account below.
                </p>
                <button
                  type="button"
                  onClick={() => void handleGeminiLogin()}
                  disabled={aiBusy}
                  className="w-full bg-terminal-amber text-terminal-bg font-bold py-2 px-4 hover:bg-yellow-500 disabled:opacity-50 transition-colors text-sm uppercase flex items-center justify-center gap-2 shadow-[0_0_10px_rgba(245,158,11,0.2)]"
                >
                  {aiBusy ? 'Awaiting sign in…' : 'Login with Google (Gemini)'}
                </button>
              </div>
            ) : aiProvider === 'codex' ? (
              <div className="rounded bg-[#1a1d23] border border-terminal-border p-3 text-xs leading-relaxed text-terminal-muted">
                Codex uses your ChatGPT Plus/Pro subscription via a browser sign-in.
                Finish setup here, then connect it in the Settings widget (AI → Codex → Sign in with ChatGPT).
              </div>
            ) : (
              <div className="space-y-2">
                <Field label={providerKeyLabel(aiProvider)}>
                  <input
                    type="password"
                    value={aiKey}
                    onChange={(e) => handleKeyChange(e.target.value)}
                    className={inputCls}
                    placeholder={providerKeyPlaceholder(aiProvider)}
                    autoComplete="off"
                  />
                </Field>
              </div>
            )}
            <AiProviderInstructions providerId={aiProvider} />
            {aiMsg && (
              <div
                className={`p-2 border text-xs ${
                  aiMsg.includes('success') || aiMsg.includes('connected') || aiMsg.includes('configured')
                    ? 'bg-green-900/40 border-green-600 text-green-200'
                    : 'bg-[#1a1d23] border-terminal-border text-terminal-muted'
                }`}
              >
                {aiMsg}
              </div>
            )}
          </div>
        )}

        {step === 'models' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">Background worker models (AI picks)</p>
            {!aiStatus?.isConfigured || aiProvider === 'codex' ? (
              <div className="rounded bg-[#1a1d23] p-3 text-xs leading-relaxed text-terminal-muted border border-[#2d3139]">
                No provider connected yet — hunter and verifier will use the
                provider defaults. You can set these later in the Settings widget.
              </div>
            ) : modelsLoading && providerModels.length === 0 ? (
              <div className="rounded bg-[#1a1d23] p-3 text-xs leading-relaxed text-terminal-amber border border-[#2d3139] animate-pulse">
                Loading models for {AI_PROVIDER_MAP[aiProvider]?.label ?? aiProvider}…
              </div>
            ) : providerModels.length === 0 ? (
              <div className="rounded bg-[#1a1d23] p-3 text-xs leading-relaxed text-terminal-muted border border-[#2d3139]">
                No models could be loaded — hunter and verifier will use the
                provider defaults. You can set these later in the Settings widget.
              </div>
            ) : (
              <div className="space-y-3">
                <Field label="HUNTER MODEL">
                  <ModelCombobox
                    value={hunterModel}
                    options={providerModels}
                    onChange={(id) => void handleWorkerModelChange('ai.hunter_model', id)}
                    placeholder="Select…"
                    emptyText="No models match your search."
                  />
                </Field>
                <p className="-mt-1 text-[11px] text-terminal-muted leading-relaxed">
                  Hunter scans the market for opportunities — pick a smarter, more capable model.
                </p>
                <Field label="VERIFIER MODEL">
                  <ModelCombobox
                    value={verifierModel}
                    options={providerModels}
                    onChange={(id) => void handleWorkerModelChange('ai.verifier_model', id)}
                    placeholder="Select…"
                    emptyText="No models match your search."
                  />
                </Field>
                <p className="-mt-1 text-[11px] text-terminal-muted leading-relaxed">
                  Verifier double-checks the hunter&apos;s picks — a faster, less capable model is fine.
                </p>
              </div>
            )}
          </div>
        )}

        {step === 'done' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">Setup complete</p>
            <ul className="text-xs text-terminal-muted space-y-1.5 leading-relaxed">
              <li>Backend: {health?.ok ? 'connected' : 'not verified'}.</li>
              <li>Signed in as {auth?.user.username ?? '—'}.</li>
              <li>Extraction: {consent === true ? 'enabled' : consent === false ? 'Safe Mode' : '—'}.</li>
              <li>AI: {aiStatus?.isConfigured ? `connected (${aiStatus.provider})` : 'skipped — add a key or connect later in Settings'}.</li>
              <li>Worker models: hunter {hunterModel || 'not set'}, verifier {verifierModel || 'not set'}.</li>
              <li>Trading (OpenAlgo): add later in the Settings widget.</li>
            </ul>
            <p className="text-xs text-terminal-muted">
              Next: a short guided tour of the terminal. You can replay it anytime with the TOUR command or from DOCS.
            </p>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 pt-4 mt-6 border-t border-[#2d3139]/60">
          {stepIdx > 0 ? (
            <button
              type="button"
              onClick={back}
              className="rounded px-4 py-2 text-xs font-medium text-[#9ca3af] hover:text-white bg-[#1a1d23] hover:bg-[#252830] transition border border-[#2d3139]"
            >
              Back
            </button>
          ) : (
            <div />
          )}
          {stepIdx < STEPS.length - 1 ? (
            <div className="flex items-center gap-2">
              {step === 'ai' && (
                <button
                  type="button"
                  onClick={next}
                  className="rounded px-4 py-2 text-xs font-medium text-[#9ca3af] hover:text-white transition"
                >
                  Set up later
                </button>
              )}
              <button
                type="button"
                onClick={next}
                disabled={!canContinue}
                className="rounded px-4 py-2 text-xs font-semibold text-white bg-[#2563eb] hover:bg-[#1d4ed8] transition shadow-sm disabled:opacity-40"
              >
                Continue
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={finish}
              className="rounded px-4 py-2 text-xs font-semibold text-white bg-[#2563eb] hover:bg-[#1d4ed8] transition shadow-sm"
            >
              Finish & start tour
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
