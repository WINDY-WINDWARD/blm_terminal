/**
 * Universal catch-all proxy route: /api/py/[...path]
 *
 * Forwards GET and POST requests to the Python FastAPI backend, preserving
 * the path and query string. The backend URL is kept server-side only via
 * the PYTHON_BACKEND_URL environment variable.
 *
 * Example:
 *   GET  /api/py/circulars?dept=TRADING
 *   →    http://localhost:4455/api/circulars?dept=TRADING
 *
 *   GET  /api/py/earnings?symbol=RELIANCE&exchange=NSE
 *   →    http://localhost:4455/api/earnings?symbol=RELIANCE&exchange=NSE
 */

import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'
import { getPythonBackendUrl } from '@/lib/backendUrl'

export const dynamic = 'force-dynamic'

function buildUpstreamUrl(params: { path: string[] }, request: NextRequest): string {
  const apiPath = params.path.join('/')
  const search = request.nextUrl.search // preserves ?foo=bar&baz=qux
  return `${getPythonBackendUrl()}/api/${apiPath}${search}`
}

async function proxyRequest(
  request: NextRequest,
  params: { path: string[] },
): Promise<Response> {
  const upstreamUrl = buildUpstreamUrl(params, request)

  // Forward headers needed by the backend.
  // Authorization is required for authenticated endpoints (/auth/me, etc.).
  const forwardHeaders = new Headers()
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (
      lower === 'content-type' ||
      lower === 'accept' ||
      lower === 'accept-language' ||
      lower === 'authorization' ||
      lower === 'cookie'
    ) {
      forwardHeaders.set(key, value)
    }
  })
  // Per-launch token (Step 5): server.js injects x-blm-internal-token at the
  // edge before passing the request to Next.js. Never trust a client-supplied
  // value here — delete it first, then set the server-side one (if any).
  forwardHeaders.delete('x-blm-token')
  const localToken = request.headers.get('x-blm-internal-token')
  if (localToken) {
    forwardHeaders.set('x-blm-token', localToken)
  }

  try {
    const body =
      request.method !== 'GET' && request.method !== 'HEAD'
        ? await request.text()
        : undefined

    const isSse = request.headers.get('accept')?.includes('text/event-stream')
    
    // Give streams 10 mins; give standard requests 60s to allow for cold-start web harvesting / rate-limited endpoints
    const timeoutMs = isSse ? 600000 : 60000

    const upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers: forwardHeaders,
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(timeoutMs),
    })

    const contentType = upstream.headers.get('content-type') ?? ''

    if (contentType.includes('text/event-stream')) {
      // Forward SSE body directly, but strip hop-by-hop headers that must
      // not be forwarded to the end client (transfer-encoding, connection, etc.)
      const HOP_BY_HOP = new Set([
        'transfer-encoding',
        'connection',
        'keep-alive',
        'proxy-authenticate',
        'proxy-authorization',
        'te',
        'trailers',
        'upgrade',
      ])
      const sseHeaders = new Headers()
      upstream.headers.forEach((value, key) => {
        if (!HOP_BY_HOP.has(key.toLowerCase())) {
          sseHeaders.set(key, value)
        }
      })
      return new Response(upstream.body, {
        status: upstream.status,
        headers: sseHeaders,
      })
    }

    // Extract Set-Cookie from upstream response so the browser actually
    // receives it (critical for login cookie to work through the proxy).
    const upstreamSetCookie = upstream.headers.get('set-cookie')

    const rawBody = await upstream.text()

    if (!upstream.ok) {
      // Gracefully handle non-JSON error responses (e.g. HTML 500 pages)
      try {
        const data = JSON.parse(rawBody)
        const res = NextResponse.json(data, { status: upstream.status })
        if (upstreamSetCookie) res.headers.set('set-cookie', upstreamSetCookie)
        return res
      } catch {
        // Not valid JSON — wrap raw body in an error object so callers always
        // receive a predictable shape { error: string }.
        const res = NextResponse.json(
          { error: rawBody.slice(0, 500) },
          { status: upstream.status },
        )
        if (upstreamSetCookie) res.headers.set('set-cookie', upstreamSetCookie)
        return res
      }
    }

    if (contentType.includes('application/json')) {
      const resHeaders = new Headers()
      resHeaders.set('content-type', contentType)
      if (upstreamSetCookie) resHeaders.set('set-cookie', upstreamSetCookie)
      return new Response(rawBody, { status: upstream.status, headers: resHeaders })
    }

    // Fallback for 200 OK responses that are not JSON — forward as plain text
    const res = new Response(rawBody, { status: upstream.status })
    if (upstreamSetCookie) res.headers.set('set-cookie', upstreamSetCookie)
    return res
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'

    if (
      message.includes('Timeout') ||
      message.includes('timeout') ||
      message.includes('abort') ||
      message.includes('AbortError')
    ) {
      return NextResponse.json(
        { error: 'Python backend request timed out' },
        { status: 504 },
      )
    }

    if (
      message.includes('ECONNREFUSED') ||
      message.includes('fetch failed') ||
      message.includes('Failed to fetch')
    ) {
      return NextResponse.json(
        { error: 'Python backend unavailable' },
        { status: 502 },
      )
    }

    return NextResponse.json({ error: message }, { status: 500 })
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, await params)
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, await params)
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, await params)
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  return proxyRequest(request, await params)
}
