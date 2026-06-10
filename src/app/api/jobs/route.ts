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

export async function GET(request: NextRequest) {
  const url = `${PYTHON_BACKEND_URL}/api/jobs${request.nextUrl.search}`;
  
  try {
    const upstream = await fetch(url, {
      method: 'GET',
      headers: forwardHeaders(request),
    });
    
    const data = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (error) {
    console.error('Error proxying to Python backend (GET /api/jobs):', error);
    return NextResponse.json({ error: 'Failed to fetch jobs' }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const url = `${PYTHON_BACKEND_URL}/api/jobs`;
  
  try {
    const body = await request.json();
    
    const upstream = await fetch(url, {
      method: 'POST',
      headers: { ...forwardHeaders(request), 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    
    const data = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (error) {
    console.error('Error proxying to Python backend (POST /api/jobs):', error);
    return NextResponse.json({ error: 'Failed to process request' }, { status: 500 });
  }
}
