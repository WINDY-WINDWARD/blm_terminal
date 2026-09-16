import type { AuthState } from '@/store/terminalStore';

function errMessage(err: unknown, fallback: string): string {
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

async function fetchJson(input: string, init?: RequestInit, timeoutMs = 8000) {
  const res = await fetch(input, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  return { res, data };
}

// ─── Backend health ─────────────────────────────────────────────────────────

export interface HealthResult {
  ok: boolean;
  message: string;
}

/** The Python backend is up if the (authenticated or not) system-config probe
 *  does not fail with a gateway/network error. 401 simply means "backend is
 *  alive, login required". */
export async function checkBackendHealth(): Promise<HealthResult> {
  try {
    const { res } = await fetchJson('/api/py/system-config', undefined, 5000);
    if (res.status === 502 || res.status === 503 || res.status === 504) {
      return { ok: false, message: `Backend unreachable (HTTP ${res.status}). Start blm-backend / uvicorn on :4455.` };
    }
    return { ok: true, message: `Backend reachable (HTTP ${res.status}).` };
  } catch (err: unknown) {
    return { ok: false, message: errMessage(err, 'Backend unreachable. Start blm-backend / uvicorn on :4455.') };
  }
}

// ─── First-boot setup status ────────────────────────────────────────────────

export async function getSetupStatus(): Promise<{ needsSetup: boolean }> {
  const { res, data } = await fetchJson('/api/py/auth/setup-status');
  if (!res.ok) throw new Error(`Setup status check failed (HTTP ${res.status})`);
  const needsSetup = (data as { needs_setup?: unknown })?.needs_setup === true;
  return { needsSetup };
}

// ─── Admin bootstrap / login ────────────────────────────────────────────────

export async function setupFirstAdmin(username: string, password: string): Promise<AuthState> {
  const { res, data } = await fetchJson('/api/py/auth/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (res.status === 403) throw new Error('Setup already completed on this backend. Please log in instead.');
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Setup failed (HTTP ${res.status})`);
  }
  void data;
  return refreshAuthState();
}

export async function loginWithPassword(username: string, password: string): Promise<AuthState> {
  const form = new URLSearchParams();
  form.append('username', username);
  form.append('password', password);
  const { res } = await fetchJson('/api/py/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  });
  if (res.status === 401) throw new Error('Invalid username or password');
  if (!res.ok) throw new Error('Authentication service unavailable. Please try again.');
  return refreshAuthState();
}

export async function refreshAuthState(): Promise<AuthState> {
  const { res, data } = await fetchJson('/api/py/auth/me', undefined, 5000);
  if (!res.ok) throw new Error('Could not load user profile after login.');
  const user = data as AuthState['user'];
  return { user };
}

// ─── Consent / system config ────────────────────────────────────────────────

export async function postScrapingConsent(consent: boolean): Promise<void> {
  const { res, data } = await fetchJson('/api/py/system_config/consent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consent }),
  });
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Could not save consent (HTTP ${res.status})`);
  }
}

export async function saveSystemConfig(key: string, value: string): Promise<void> {
  const { res, data } = await fetchJson(`/api/py/system-config/${encodeURIComponent(key)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Could not save ${key} (HTTP ${res.status})`);
  }
}

export interface AiStatus {
  provider: string;
  isConfigured: boolean;
}

export async function checkAiStatus(): Promise<AiStatus> {
  const { res, data } = await fetchJson('/api/py/ai/status', undefined, 5000);
  if (!res.ok) throw new Error(`AI status check failed (HTTP ${res.status})`);
  const d = data as { provider?: unknown; is_configured?: unknown };
  return {
    provider: typeof d.provider === 'string' ? d.provider : 'zen',
    isConfigured: d.is_configured === true,
  };
}
