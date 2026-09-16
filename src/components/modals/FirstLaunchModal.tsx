'use client';

import React, { useEffect, useState } from 'react';
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
  getSetupStatus,
  loginWithPassword,
  postScrapingConsent,
  saveSystemConfig,
  setupFirstAdmin,
  type AiStatus,
  type HealthResult,
} from '@/lib/onboarding';

type StepId = 'welcome' | 'backend' | 'admin' | 'consent' | 'ai' | 'done';

const STEPS: { id: StepId; label: string }[] = [
  { id: 'welcome', label: 'Welcome' },
  { id: 'backend', label: 'Backend' },
  { id: 'admin', label: 'Admin' },
  { id: 'consent', label: 'Privacy' },
  { id: 'ai', label: 'AI' },
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
  const [dismissed, setDismissed] = useState(false);

  // backend step
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [healthChecking, setHealthChecking] = useState(false);

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
  const [aiProvider, setAiProvider] = useState('zen');
  const [aiKey, setAiKey] = useState('');
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState('');

  useEffect(() => {
    setMounted(true);
  }, []);

  const step = STEPS[stepIdx].id;

  // Lazily probe when entering gated steps
  useEffect(() => {
    if (!mounted || completed || dismissed) return;
    if (step === 'backend' && health === null && !healthChecking) {
      setHealthChecking(true);
      checkBackendHealth()
        .then(setHealth)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, mounted, completed, dismissed]);

  if (!mounted || completed || dismissed) return null;

  const runBackendCheck = () => {
    setHealthChecking(true);
    setHealth(null);
    checkBackendHealth()
      .then(setHealth)
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
    } catch (err: unknown) {
      setConsentError(errText(err, 'Could not save consent'));
    } finally {
      setConsentBusy(false);
    }
  };

  const handleSaveAiKey = async () => {
    setAiMsg('');
    if (!aiKey.trim()) {
      setAiMsg('Paste an API key first, or skip this step.');
      return;
    }
    setAiBusy(true);
    try {
      await saveSystemConfig('ai.provider', aiProvider);
      await saveSystemConfig(`ai.${aiProvider}_api_key`, aiKey.trim());
      const st = await checkAiStatus();
      setAiStatus(st);
      setAiMsg(st.isConfigured ? 'AI configured successfully.' : 'Key saved but backend reports unconfigured.');
    } catch (err: unknown) {
      setAiMsg(errText(err, 'Could not save AI key'));
    } finally {
      setAiBusy(false);
    }
  };

  const finish = () => {
    setTutorialStatus('active');
    setCompleted(true);
  };

  const canContinue =
    step === 'welcome' ||
    (step === 'backend' && health?.ok === true) ||
    (step === 'admin' && auth !== null) ||
    (step === 'consent' && consent !== null && !consentBusy) ||
    step === 'ai' ||
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
              This short setup connects the app backend, creates your administrator account,
              records your data-extraction choice, and optionally enables the AI assistant.
              Takes about a minute. Trading connections (OpenAlgo) can be added later in Settings.
            </p>
          </div>
        )}

        {step === 'backend' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">Connect to the backend</p>
            <p className="text-xs text-terminal-muted leading-relaxed">
              The terminal needs its Python backend (blm-backend / uvicorn on port 4455).
            </p>
            {healthChecking && <p className="text-xs text-terminal-amber animate-pulse">CHECKING…</p>}
            {health && (
              <div
                className={`p-2 text-xs border ${health.ok ? 'bg-green-900/40 border-green-600 text-green-200' : 'bg-red-900/50 border-red-500 text-red-200'}`}
              >
                {health.message}
              </div>
            )}
            <button
              type="button"
              onClick={runBackendCheck}
              disabled={healthChecking}
              className="px-3 py-1.5 text-xs border border-terminal-border bg-terminal-bg hover:border-terminal-amber disabled:opacity-50 transition-colors"
            >
              {healthChecking ? 'CHECKING…' : 'RETRY CHECK'}
            </button>
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
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void handleConsent(false)}
                disabled={consentBusy}
                className={`flex-1 px-3 py-2 text-xs font-medium border transition disabled:opacity-50 ${
                  consentChoice === false
                    ? 'border-terminal-amber text-terminal-amber'
                    : 'border-terminal-border text-terminal-muted hover:text-white'
                }`}
              >
                Decline (Safe Mode)
              </button>
              <button
                type="button"
                onClick={() => void handleConsent(true)}
                disabled={consentBusy}
                className={`flex-1 px-3 py-2 text-xs font-medium border transition disabled:opacity-50 ${
                  consentChoice === true
                    ? 'border-terminal-amber text-terminal-amber'
                    : 'border-terminal-border text-terminal-muted hover:text-white'
                }`}
              >
                I Agree, Enable
              </button>
            </div>
          </div>
        )}

        {step === 'ai' && (
          <div className="space-y-3 text-sm">
            <p className="text-base text-white font-semibold">AI assistant (optional)</p>
            <div className="rounded bg-[#1a1d23] p-3 text-xs leading-relaxed text-[#d1d5db] border border-[#2d3139]">
              Tip: OpenCode has a generous free tier — sign up at{' '}
              <a
                href="https://opencode.ai/auth"
                target="_blank"
                rel="noreferrer"
                className="text-terminal-amber underline hover:text-yellow-400"
              >
                opencode.ai/auth
              </a>
              , copy your API key, and paste it below. No billing required to get started.
            </div>
            {aiStatus && (
              <div
                className={`p-2 text-xs border ${aiStatus.isConfigured ? 'bg-green-900/40 border-green-600 text-green-200' : 'bg-[#1a1d23] border-terminal-border text-terminal-muted'}`}
              >
                Status: provider={aiStatus.provider} · {aiStatus.isConfigured ? 'configured' : 'not configured'}
              </div>
            )}
            <Field label="PROVIDER">
              <select
                value={aiProvider}
                onChange={(e) => setAiProvider(e.target.value)}
                className={`${inputCls} [&>option]:bg-terminal-bg`}
              >
                <option value="zen">OpenCode Zen (recommended)</option>
                <option value="go">Go</option>
                <option value="gemini">Gemini (OAuth via Settings)</option>
              </select>
            </Field>
            {aiProvider !== 'gemini' ? (
              <Field label={`${aiProvider === 'go' ? 'GO' : 'ZEN'} API KEY`}>
                <input
                  type="password"
                  value={aiKey}
                  onChange={(e) => setAiKey(e.target.value)}
                  className={inputCls}
                  placeholder="sk-…"
                  autoComplete="off"
                />
              </Field>
            ) : (
              <p className="text-xs text-terminal-muted">
                Gemini uses OAuth — connect it later in the Settings widget.
              </p>
            )}
            {aiMsg && (
              <div className="p-2 bg-[#1a1d23] border border-terminal-border text-xs text-terminal-muted">
                {aiMsg}
              </div>
            )}
            {aiProvider !== 'gemini' && (
              <button
                type="button"
                onClick={() => void handleSaveAiKey()}
                disabled={aiBusy}
                className="w-full bg-terminal-amber text-terminal-bg font-bold py-2 px-4 hover:bg-yellow-500 disabled:opacity-50 transition-colors text-sm"
              >
                {aiBusy ? 'SAVING…' : 'SAVE AI KEY'}
              </button>
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
              <li>AI: {aiStatus?.isConfigured ? `configured (${aiStatus.provider})` : 'skipped — add a key later in Settings'}.</li>
              <li>Trading (OpenAlgo): add later in the Settings widget.</li>
            </ul>
            <p className="text-xs text-terminal-muted">
              Next: a short guided tour of the terminal. You can replay it anytime with the TOUR command or from DOCS.
            </p>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 pt-4 mt-6 border-t border-[#2d3139]/60">
          <button
            type="button"
            onClick={back}
            disabled={stepIdx === 0}
            className="rounded px-4 py-2 text-xs font-medium text-[#9ca3af] hover:text-white bg-[#1a1d23] hover:bg-[#252830] transition border border-[#2d3139] disabled:opacity-40"
          >
            Back
          </button>
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

        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="mt-3 w-full text-center text-[11px] text-terminal-muted hover:text-white transition"
        >
          Remind me later
        </button>
      </div>
    </div>
  );
}
