import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/notifications/${id}?watchlist_id=${watchlistId}`,
      { method: 'DELETE' },
    );
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
