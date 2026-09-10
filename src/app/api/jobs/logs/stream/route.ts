import type { NextRequest } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * SSE proxy for backend log streaming.
 * Pipes /api/jobs/logs/stream from the Python backend through to the browser.
 * Uses ReadableStream so the response body is not buffered.
 */
export async function GET(request: NextRequest) {
  const lines = request.nextUrl.searchParams.get('lines') ?? '200';
  const upstreamUrl = `${PYTHON_BACKEND_URL}/api/jobs/logs/stream?lines=${lines}`;

  const headers: Record<string, string> = {
    accept: 'text/event-stream',
  };
  const cookie = request.headers.get('cookie');
  if (cookie) headers['cookie'] = cookie;
  const auth = request.headers.get('authorization');
  if (auth) headers['authorization'] = auth;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      headers,
      // @ts-expect-error – Node 18+ fetch supports duplex for streaming
      duplex: 'half',
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return new Response(`data: [error connecting to backend: ${message}]\n\n`, {
      status: 502,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  }

  if (!upstream.ok || !upstream.body) {
    return new Response(`data: [backend returned ${upstream.status}]\n\n`, {
      status: upstream.status,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  }

  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    },
  });
}
