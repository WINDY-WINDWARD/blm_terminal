import type { NextRequest } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders } from '@/lib/backendUrl';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * SSE proxy for backend log streaming.
 * Pipes /api/jobs/logs/stream from the Python backend through to the browser.
 * Uses ReadableStream so the response body is not buffered.
 */
export async function GET(request: NextRequest) {
  const lines = request.nextUrl.searchParams.get('lines') ?? '200';
  const upstreamUrl = `${getPythonBackendUrl()}/api/jobs/logs/stream?lines=${lines}`;

  const headers = getBackendForwardHeaders(request, {
    accept: 'text/event-stream',
  });

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      headers,
      cache: 'no-store',
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
