import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders } from '@/lib/backendUrl';

export const runtime = 'nodejs';

export interface EventCalendarItem {
  symbol: string;
  company: string;
  purpose: string;
  description: string;
  date: string;         // "20-Apr-2026"
  source: 'main' | 'sme';
  attachment: string | null;
}

export async function GET(request: NextRequest) {
  try {
    const res = await fetch(`${getPythonBackendUrl()}/api/event-calendar`, {
      headers: getBackendForwardHeaders(request, { accept: 'application/json' }),
      // Next.js fetch cache: revalidate every 15 minutes
      next: { revalidate: 900 },
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = (await res.json()) as { detail?: string };
        if (body.detail) detail = body.detail;
      } catch {
        // ignore parse error
      }
      return NextResponse.json({ error: detail }, { status: res.status });
    }

    const data = (await res.json()) as EventCalendarItem[];

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 's-maxage=900, stale-while-revalidate=60',
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
