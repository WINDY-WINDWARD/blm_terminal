import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getServerInternalHeaders } from '@/lib/backendUrl';

async function isAuthorizedRequest(req: NextRequest): Promise<boolean> {
  const launchToken = process.env.BLM_LOCAL_TOKEN;
  const requestToken = req.headers.get('x-blm-token');
  if (launchToken && requestToken === launchToken) {
    return true;
  }

  const authorization = req.headers.get('authorization');
  const cookie = req.headers.get('cookie');
  if (!authorization && !cookie) {
    return false;
  }

  const headers: Record<string, string> = {};
  if (authorization) headers.authorization = authorization;
  if (cookie) headers.cookie = cookie;
  try {
    const res = await fetch(`${getPythonBackendUrl()}/api/auth/me`, {
      headers,
      signal: AbortSignal.timeout(2000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * GET /api/openalgo/ws-token
 * Returns the WebSocket API key so the client can authenticate with the WebSocket.
 * Only responds to requests authenticated with the per-launch local token
 * (Electron injects x-blm-token) or a valid application session, so the raw key
 * is never disclosed to unauthenticated callers.
 */
export async function GET(req: NextRequest) {
  try {
    if (!(await isAuthorizedRequest(req))) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    let apiKey = process.env.OPENALGO_API_KEY;

    if (!apiKey) {
      try {
        const cfgRes = await fetch(`${getPythonBackendUrl()}/api/system-config/openalgo-credentials`, {
          headers: getServerInternalHeaders({ accept: 'application/json' }),
          signal: AbortSignal.timeout(2000),
        });
        if (cfgRes.ok) {
          const data = await cfgRes.json() as Record<string, unknown>;
          if (typeof data.api_key === 'string' && data.api_key) {
            apiKey = data.api_key;
          } else if (typeof data['openalgo.api_key'] === 'string' && data['openalgo.api_key']) {
            apiKey = data['openalgo.api_key'];
          }
        }
      } catch {
        // Ignore backend lookup error
      }
    }

    if (!apiKey) {
      return NextResponse.json({ error: 'API key not configured' }, { status: 500 });
    }

    // Return the API key so client can authenticate with WebSocket
    return NextResponse.json({ api_key: apiKey });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
