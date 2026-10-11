import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

/**
 * Helper to get the active Python backend URL.
 * Evaluated at request time so dynamic port assignments (e.g. in Electron) are respected.
 */
export function getPythonBackendUrl(): string {
  return process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';
}

/**
 * Builds request headers for outgoing fetches from Next.js to the Python backend.
 * Automatically forwards:
 * 1. Per-launch security token ('x-blm-token') from x-blm-internal-token or process.env.BLM_LOCAL_TOKEN
 * 2. Authorization header (Bearer tokens / auth)
 * 3. Cookie header (session / auth cookies)
 * 4. Any custom headers passed in via extra
 */
export function getBackendForwardHeaders(
  request?: Request | NextRequest | null,
  extra?: Record<string, string>,
): Headers {
  const headers = new Headers();

  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined && v !== null) {
        headers.set(k, v);
      }
    }
  }

  if (request) {
    const auth = request.headers.get('authorization');
    if (auth && !headers.has('authorization')) {
      headers.set('authorization', auth);
    }

    const cookie = request.headers.get('cookie');
    if (cookie && !headers.has('cookie')) {
      headers.set('cookie', cookie);
    }

    const internalToken = request.headers.get('x-blm-internal-token');
    if (internalToken) {
      headers.set('x-blm-token', internalToken);
    }
  }

  // Fallback to environment variable if request header didn't carry it
  if (!headers.has('x-blm-token') && process.env.BLM_LOCAL_TOKEN) {
    headers.set('x-blm-token', process.env.BLM_LOCAL_TOKEN);
  }

  return headers;
}

/**
 * Forwards Set-Cookie from upstream response to downstream NextResponse if present.
 */
export function forwardSetCookie(upstream: Response, res: NextResponse): void {
  const setCookie = upstream.headers.get('set-cookie');
  if (setCookie) {
    res.headers.set('set-cookie', setCookie);
  }
}
