import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';

const DEFAULT_WATCHLIST_COLUMNS = ['ltp', 'chg', '1w', '1m', '3m', '6m', '1y'];
const DEFAULT_MOVERS_COLUMNS = ['close', 'chg', '1w', '1m', '3m', '6m', '1y'];

interface SettingsResponse {
  watchlistColumns: string[];
  moversColumns: string[];
}

async function getOrCreateSettings(): Promise<SettingsResponse> {
  let settings = await prisma.userSettings.findUnique({
    where: { id: 1 },
  });

  if (!settings) {
    settings = await prisma.userSettings.create({
      data: {
        id: 1,
        watchlistColumns: JSON.stringify(DEFAULT_WATCHLIST_COLUMNS),
        moversColumns: JSON.stringify(DEFAULT_MOVERS_COLUMNS),
      },
    });
  }

  return {
    watchlistColumns: JSON.parse(settings.watchlistColumns),
    moversColumns: JSON.parse(settings.moversColumns),
  };
}

export async function GET() {
  try {
    const settings = await getOrCreateSettings();
    return NextResponse.json(settings);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as {
      watchlistColumns?: string[];
      moversColumns?: string[];
    };

    const watchlistColumns = body.watchlistColumns ?? DEFAULT_WATCHLIST_COLUMNS;
    const moversColumns = body.moversColumns ?? DEFAULT_MOVERS_COLUMNS;

    const settings = await prisma.userSettings.upsert({
      where: { id: 1 },
      update: {
        watchlistColumns: JSON.stringify(watchlistColumns),
        moversColumns: JSON.stringify(moversColumns),
      },
      create: {
        id: 1,
        watchlistColumns: JSON.stringify(watchlistColumns),
        moversColumns: JSON.stringify(moversColumns),
      },
    });

    return NextResponse.json({
      watchlistColumns: JSON.parse(settings.watchlistColumns),
      moversColumns: JSON.parse(settings.moversColumns),
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
