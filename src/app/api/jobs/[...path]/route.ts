import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';

function forwardHeaders(req: NextRequest): Record<string, string> {
  const headers: Record<string, string> = { accept: 'application/json' };
  const cookie = req.headers.get('cookie');
  if (cookie) headers['cookie'] = cookie;
  const auth = req.headers.get('authorization');
  if (auth) headers['authorization'] = auth;
  return headers;
}

function forwardSetCookie(upstream: Response, res: NextResponse): void {
  const setCookie = upstream.headers.get('set-cookie');
  if (setCookie) res.headers.set('set-cookie', setCookie);
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const pathPart = path?.length ? `/${path.join('/')}` : '';
  const url = `${PYTHON_BACKEND_URL}/api/jobs${pathPart}${request.nextUrl.search}`;

  try {
    const upstream = await fetch(url, { headers: forwardHeaders(request) });
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
  const url = `${PYTHON_BACKEND_URL}/api/jobs${pathPart}`;

  try {
    const body = await request.json().catch(() => ({}));
    const upstream = await fetch(url, {
      method: 'POST',
      headers: { ...forwardHeaders(request), 'content-type': 'application/json' },
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
