import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const pathPart = path?.length ? `/${path.join('/')}` : '';
  const url = `${PYTHON_BACKEND_URL}/api/jobs${pathPart}${request.nextUrl.search}`;

  try {
    const response = await fetch(url);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
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
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({ error: 'Invalid response' }));
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
