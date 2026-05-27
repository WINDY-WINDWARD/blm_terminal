import { NextResponse } from 'next/server';

/**
 * Returns the WebSocket URL for the Python backend market WS endpoint.
 * Reads PYTHON_BACKEND_URL (server-side only) and converts it to a ws:// URL.
 * The browser uses this URL to connect directly to the Python backend WS.
 */
export async function GET(): Promise<NextResponse> {
  const backendUrl = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

  // Convert http(s):// → ws(s)://
  const wsUrl = backendUrl
    .replace(/^https:\/\//, 'wss://')
    .replace(/^http:\/\//, 'ws://');

  return NextResponse.json({
    marketWsUrl: `${wsUrl}/ws/market`,
    newsWsUrl: `${wsUrl}/ws/news`,
  });
}
