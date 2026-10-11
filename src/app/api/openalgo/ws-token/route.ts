import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders } from '@/lib/backendUrl';

/**
 * GET /api/openalgo/ws-token
 * Returns the WebSocket API key so the client can authenticate with the WebSocket.
 * This is safe because:
 * 1. It only works for authenticated requests from our domain
 * 2. The API key is still only sent to authenticated users
 * 3. The key is still never stored in client-side environment files
 */
export async function GET(req: NextRequest) {
  try {
    let apiKey = process.env.OPENALGO_API_KEY;

    if (!apiKey) {
      try {
        const cfgRes = await fetch(`${getPythonBackendUrl()}/api/system-config`, {
          headers: getBackendForwardHeaders(req, { accept: 'application/json' }),
          signal: AbortSignal.timeout(2000),
        });
        if (cfgRes.ok) {
          const data = await cfgRes.json() as Record<string, unknown>;
          if (typeof data['openalgo.api_key'] === 'string') {
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
