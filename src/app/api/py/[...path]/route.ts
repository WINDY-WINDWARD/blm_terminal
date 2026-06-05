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

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455'

function buildUpstreamUrl(params: { path: string[] }, request: NextRequest): string {
  const apiPath = params.path.join('/')
  const search = request.nextUrl.search // preserves ?foo=bar&baz=qux
  return `${PYTHON_BACKEND_URL}/api/${apiPath}${search}`
}

async function proxyRequest(
  request: NextRequest,
  params: { path: string[] },
): Promise<Response> {
  const upstreamUrl = buildUpstreamUrl(params, request)

  // Forward only safe, non-host headers
  const forwardHeaders = new Headers()
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (
      lower === 'content-type' ||
      lower === 'accept' ||
      lower === 'accept-language'
    ) {
      forwardHeaders.set(key, value)
    }
  })

  try {
    const body =
      request.method !== 'GET' && request.method !== 'HEAD'
        ? await request.text()
        : undefined

    const upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers: forwardHeaders,
      body,
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

    const rawBody = await upstream.text()

    if (!upstream.ok) {
      // Gracefully handle non-JSON error responses (e.g. HTML 500 pages)
      try {
        const data = JSON.parse(rawBody)
        return NextResponse.json(data, { status: upstream.status })
      } catch {
        // Not valid JSON — wrap raw body in an error object so callers always
        // receive a predictable shape { error: string }.
        return NextResponse.json(
          { error: rawBody.slice(0, 500) },
          { status: upstream.status },
        )
      }
    }

    try {
      const data = JSON.parse(rawBody)
      return NextResponse.json(data, { status: upstream.status })
    } catch {
      // Fallback for 200 OK responses that are not JSON — forward as plain text
      return new Response(rawBody, { status: upstream.status })
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'

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
