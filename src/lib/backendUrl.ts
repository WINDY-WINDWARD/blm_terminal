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
 * 1. Per-launch security token ('x-blm-token') from process.env.BLM_LOCAL_TOKEN or request
 * 2. Authorization header (Bearer tokens / auth)
 * 3. Cookie header (session / auth cookies)
 * 4. Any custom headers passed in via extra
 *
 * NOTE: Client-supplied 'x-blm-internal-token' or 'x-blm-server-token' headers are
 * strictly untrusted from incoming requests and never forwarded to backend callers.
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

    // In Electron desktop mode, webRequest.onBeforeSendHeaders injects x-blm-token
    const clientToken = request.headers.get('x-blm-token');
    if (clientToken && !headers.has('x-blm-token')) {
      headers.set('x-blm-token', clientToken);
    }
  }

  // Fallback to environment variable if request header didn't carry it
  if (!headers.has('x-blm-token') && process.env.BLM_LOCAL_TOKEN) {
    headers.set('x-blm-token', process.env.BLM_LOCAL_TOKEN);
  }

  // Strip any accidental internal tokens
  headers.delete('x-blm-internal-token');
  headers.delete('x-blm-server-token');

  return headers;
}

/**
 * Builds headers for server-to-server internal calls to Python endpoints.
 * Uses the server-only internal token (process.env.BLM_INTERNAL_TOKEN)
 * and optional local launch token (process.env.BLM_LOCAL_TOKEN).
 */
export function getServerInternalHeaders(extra?: Record<string, string>): Headers {
  const headers = new Headers();

  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined && v !== null) {
        headers.set(k, v);
      }
    }
  }

  const internalToken = process.env.BLM_INTERNAL_TOKEN;
  if (internalToken) {
    headers.set('x-blm-server-token', internalToken);
    headers.set('x-blm-internal-token', internalToken);
  }

  if (process.env.BLM_LOCAL_TOKEN) {
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
