import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders } from '@/lib/backendUrl';
import type { EventCalendarItem } from '../route';

export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    const res = await fetch(`${getPythonBackendUrl()}/api/event-calendar/past`, {
      headers: getBackendForwardHeaders(request, { accept: 'application/json' }),
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
