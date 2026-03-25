import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';

export async function GET(request: NextRequest) {
  const url = `${PYTHON_BACKEND_URL}/api/jobs${request.nextUrl.search}`;
  
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error proxying to Python backend (GET /api/jobs):', error);
    return NextResponse.json({ error: 'Failed to fetch jobs' }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const url = `${PYTHON_BACKEND_URL}/api/jobs`;
  
  try {
    const body = await request.json();
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error proxying to Python backend (POST /api/jobs):', error);
    return NextResponse.json({ error: 'Failed to process request' }, { status: 500 });
  }
}
