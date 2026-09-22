import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { getFirstBootStatus } from '@/lib/onboarding';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('getFirstBootStatus', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns reachable+true on an explicit 2xx completed answer', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, { onboarding_completed: true }));
    await expect(getFirstBootStatus()).resolves.toEqual({ reachable: true, onboardingCompleted: true });
  });

  it('returns reachable+false on an explicit 2xx incomplete answer', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, { onboarding_completed: false }));
    await expect(getFirstBootStatus()).resolves.toEqual({ reachable: true, onboardingCompleted: false });
  });

  it('returns unknown on 502 (backend cold) — never reachable+incomplete', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(502, { error: 'Python backend unavailable' }));
    await expect(getFirstBootStatus()).resolves.toEqual({ reachable: false, onboardingCompleted: false });
  });

  it('returns unknown on 401/404/500 — never reachable+incomplete', async () => {
    for (const status of [401, 404, 500]) {
      vi.mocked(fetch).mockResolvedValue(jsonResponse(status, { error: 'x' }));
      await expect(getFirstBootStatus()).resolves.toEqual({ reachable: false, onboardingCompleted: false });
    }
  });

  it('returns unknown when the body lacks an explicit true', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, { unexpected: 1 }));
    // Answered, but not completed: reachable (backend is up), not completed.
    await expect(getFirstBootStatus()).resolves.toEqual({ reachable: true, onboardingCompleted: false });
  });

  it('returns unknown on network failure', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('refused'));
    await expect(getFirstBootStatus()).resolves.toEqual({ reachable: false, onboardingCompleted: false });
  });
});
