// Single-use WebSocket tickets: the upgrade request carries ?ticket= because
// browsers cannot set custom headers on WebSocket handshakes. The ticket is
// minted same-origin (token-injected by Electron), valid 10s, single-use.
export async function withTicket(url: string): Promise<string> {
  try {
    const r = await fetch('/api/ws-ticket', { cache: 'no-store' });
    if (!r.ok) return url;
    const j: unknown = await r.json();
    const ticket =
      typeof j === 'object' && j !== null && 'ticket' in j
        ? (j as { ticket: unknown }).ticket
        : null;
    if (typeof ticket !== 'string' || ticket.length === 0) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}ticket=${encodeURIComponent(ticket)}`;
  } catch {
    return url;
  }
}
