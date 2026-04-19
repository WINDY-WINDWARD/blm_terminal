import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

export interface EventCalendarItem {
  symbol: string;
  company: string;
  purpose: string;
  description: string;
  date: string;         // "20-Apr-2026"
  source: 'main' | 'sme';
  attachment: string | null;
}

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/event-calendar`, {
      headers: { accept: 'application/json' },
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
      return NextResponse.json({ error: detail }, { status: 502 });
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
