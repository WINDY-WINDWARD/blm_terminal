/**
 * Universal catch-all proxy route: /api/py/[...path]
 *
 * Forwards GET and POST requests to the Python FastAPI backend, preserving
 * the path and query string. The backend URL is kept server-side only via
 * the PYTHON_BACKEND_URL environment variable.
 *
 * Example:
 *   GET  /api/py/circulars?dept=TRADING
 *   →    http://localhost:8000/api/circulars?dept=TRADING
 *
 *   GET  /api/py/earnings?symbol=RELIANCE&exchange=NSE
 *   →    http://localhost:8000/api/earnings?symbol=RELIANCE&exchange=NSE
 */

import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL ?? 'http://localhost:8000'

function buildUpstreamUrl(params: { path: string[] }, request: NextRequest): string {
  const apiPath = params.path.join('/')
  const search = request.nextUrl.search // preserves ?foo=bar&baz=qux
  return `${PYTHON_BACKEND_URL}/api/${apiPath}${search}`
}

async function proxyRequest(
  request: NextRequest,
  params: { path: string[] },
): Promise<NextResponse> {
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

    const data = await upstream.json()
    return NextResponse.json(data, { status: upstream.status })
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
): Promise<NextResponse> {
  return proxyRequest(request, await params)
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  return proxyRequest(request, await params)
}
