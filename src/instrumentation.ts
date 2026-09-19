// Next.js server instrumentation: runs once when the server boots (node runtime).
// Attaches the per-launch token to every server-side fetch aimed at the local
// Python backend, so individual route handlers don't each need token plumbing.
//
// Scope is deliberately narrow: loopback hosts only, /api/* paths only, and
// never overwrites an explicitly-set header. Browser fetches are untouched
// (this file never runs client-side); the Electron header injection covers
// those. See docs/licensing.md (per-launch token).
export async function register(): Promise<void> {
  if (typeof window !== 'undefined') return;
  const g = globalThis as unknown as { fetch: typeof fetch };
  const origFetch = g.fetch.bind(g);
  g.fetch = ((input: unknown, init?: RequestInit) => {
    try {
      const url = new URL(
        typeof input === 'string' ? input : input instanceof URL ? input.href : (input as Request).url,
      );
      const loopback = url.hostname === '127.0.0.1' || url.hostname === 'localhost';
      if (loopback && url.pathname.startsWith('/api/')) {
        const token = process.env.BLM_LOCAL_TOKEN;
        const headers = new Headers(init?.headers);
        if (token && !headers.has('x-blm-token')) {
          headers.set('x-blm-token', token);
          return origFetch(input as never, { ...init, headers });
        }
      }
    } catch {
      // Malformed URL etc.: fall through to the original fetch untouched.
    }
    return origFetch(input as never, init as never);
  }) as typeof fetch;
}
