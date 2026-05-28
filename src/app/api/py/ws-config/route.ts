import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

/**
 * Returns the WebSocket URL for the Python backend WS endpoints.
 *
 * Derives the WS base URL from the incoming request's origin (the browser's
 * actual domain/IP) rather than PYTHON_BACKEND_URL, because in a deployed
 * scenario the backend is always co-located behind the same reverse proxy.
 *
 * The browser uses this URL to connect directly to the Python backend WS.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  // Derive from the request origin the browser used to load the page.
  // https://mydomain.com  →  wss://mydomain.com
  // http://localhost:3000  →  ws://localhost:3000
  const origin = request.nextUrl.origin;
  const wsBase = origin
    .replace(/^https:\/\//, 'wss://')
    .replace(/^http:\/\//, 'ws://');

  return NextResponse.json({
    marketWsUrl: `${wsBase}/ws/market`,
    newsWsUrl: `${wsBase}/ws/news`,
  });
}
