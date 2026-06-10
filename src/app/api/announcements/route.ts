import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

export interface Announcement {
  title: string;
  link: string;
  description: string;
  subject: string;
  pubDate: string;
}

interface AnnouncementsResponse {
  items: Announcement[];
  lastBuild: string;
}

function parseRSS(xml: string): AnnouncementsResponse {
  const items: Announcement[] = [];

  const itemRegex = /<item>([\s\S]*?)<\/item>/g;
  let match;

  while ((match = itemRegex.exec(xml)) !== null) {
    const itemContent = match[1];

    const getTag = (tag: string): string => {
      const cdataRegex = new RegExp(`<${tag}><!\\[CDATA\\[([\\s\\S]*?)\\]\\]>`, 'i');
      const normalRegex = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, 'i');
      const cdataMatch = itemContent.match(cdataRegex);
      if (cdataMatch) return cdataMatch[1].trim();
      const normalMatch = itemContent.match(normalRegex);
      return normalMatch ? normalMatch[1].trim() : '';
    };

    const title = getTag('title');
    const link = getTag('link');
    const descriptionRaw = getTag('description');
    const pubDate = getTag('pubDate');

    if (!title || !pubDate) continue;

    let description = descriptionRaw;
    let subject = '';

    const pipeIndex = descriptionRaw.lastIndexOf('|SUBJECT:');
    if (pipeIndex !== -1) {
      subject = descriptionRaw.slice(pipeIndex + 9).trim();
      description = descriptionRaw.slice(0, pipeIndex).trim();
    }

    if (subject.toLowerCase() === 'declaration of nav') continue;

    items.push({
      title,
      link,
      description,
      subject,
      pubDate,
    });
  }

  const lastBuildMatch = xml.match(/<lastBuildDate>([\s\S]*?)<\/lastBuildDate>/i);
  const lastBuild = lastBuildMatch ? lastBuildMatch[1].trim() : '';

  return { items, lastBuild };
}

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/announcements`, {
      headers: {
        accept: 'application/rss+xml, application/xml, text/xml',
      },
    });

    if (!res.ok) {
      return NextResponse.json(
        { error: `Failed to fetch RSS: ${res.status}` },
        { status: res.status }
      );
    }

    const xml = await res.text();
    const data = parseRSS(xml);

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 's-maxage=300, stale-while-revalidate=60',
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
