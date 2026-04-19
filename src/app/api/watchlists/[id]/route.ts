import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

// DELETE /api/watchlists/:id — delete watchlist
export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const watchlistId = parseInt(id, 10);

    if (isNaN(watchlistId)) {
      return NextResponse.json({ error: 'Invalid watchlist id' }, { status: 400 });
    }

    const res = await fetch(`${BACKEND_URL}/api/watchlists/${watchlistId}`, {
      method: 'DELETE',
      headers: { accept: 'application/json' },
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
