import { NextResponse } from 'next/server';
import { logger } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function GET() {
  let url = process.env.OPENALGO_URL;
  let key = process.env.OPENALGO_API_KEY;

  if (!url || !key) {
    try {
      const pythonUrl = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';
      const cfgRes = await fetch(`${pythonUrl}/api/system-config`, {
        signal: AbortSignal.timeout(2000),
      });
      if (cfgRes.ok) {
        const data = await cfgRes.json() as Record<string, unknown>;
        if (!url && typeof data['openalgo.url'] === 'string') {
          url = data['openalgo.url'];
        }
        if (!key && typeof data['openalgo.api_key'] === 'string') {
          key = data['openalgo.api_key'];
        }
      }
    } catch {
      // Ignore backend lookup error
    }
  }

  if (!url || !key) {
    return NextResponse.json({ available: false, reason: 'OPENALGO_URL or OPENALGO_API_KEY not set' });
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const res = await fetch(`${url}/api/v1/funds`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apikey: key }),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      return NextResponse.json({ available: false, reason: `OpenAlgo API returned ${res.status}` });
    }

    const json = await res.json() as { status?: string };
    if (json.status !== 'success') {
      return NextResponse.json({ available: false, reason: `OpenAlgo API error: ${json.status}` });
    }

    return NextResponse.json({ available: true, reason: null });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'Unknown error';
    logger.warn('OpenAlgo health check failed', { error: msg });
    return NextResponse.json({ available: false, reason: msg });
  }
}
