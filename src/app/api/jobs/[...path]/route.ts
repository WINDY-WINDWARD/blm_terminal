import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const pathPart = path?.length ? `/${path.join('/')}` : '';
  const url = `${getPythonBackendUrl()}/api/jobs${pathPart}${request.nextUrl.search}`;

  try {
    const upstream = await fetch(url, {
      headers: getBackendForwardHeaders(request, { accept: 'application/json' }),
    });
    const data = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const pathPart = path?.length ? `/${path.join('/')}` : '';
  const url = `${getPythonBackendUrl()}/api/jobs${pathPart}`;

  try {
    const body = await request.json().catch(() => ({}));
    const upstream = await fetch(url, {
      method: 'POST',
      headers: getBackendForwardHeaders(request, {
        accept: 'application/json',
        'content-type': 'application/json',
      }),
      body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
    });
    const data = await upstream.json().catch(() => ({ error: 'Invalid response' }));
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
