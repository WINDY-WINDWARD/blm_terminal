export async function fetchWidgetTours(): Promise<Record<string, number>> {
  const res = await fetch('/api/py/widget-tours', {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch widget tours: ${res.status} ${res.statusText}`);
  }
  const payload = (await res.json()) as { seen: Record<string, number> };
  return payload.seen ?? {};
}

export async function markWidgetTourSeen(command: string): Promise<void> {
  const res = await fetch('/api/py/widget-tours', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ command }),
  });
  if (!res.ok) {
    throw new Error(`Failed to mark widget tour seen: ${res.status} ${res.statusText}`);
  }
}
