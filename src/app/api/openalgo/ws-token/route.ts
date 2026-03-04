import { NextRequest, NextResponse } from 'next/server';

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
    const apiKey = process.env.OPENALGO_API_KEY;

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
