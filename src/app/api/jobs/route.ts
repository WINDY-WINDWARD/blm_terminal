import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function GET(request: NextRequest) {
  const url = `${getPythonBackendUrl()}/api/jobs${request.nextUrl.search}`;
  
  try {
    const upstream = await fetch(url, {
      method: 'GET',
      headers: getBackendForwardHeaders(request, { accept: 'application/json' }),
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
  const url = `${getPythonBackendUrl()}/api/jobs`;
  
  try {
    const body = await request.json();
    
    const upstream = await fetch(url, {
      method: 'POST',
      headers: getBackendForwardHeaders(request, {
        accept: 'application/json',
        'content-type': 'application/json',
      }),
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
