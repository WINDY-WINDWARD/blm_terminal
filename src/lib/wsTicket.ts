// Single-use WebSocket tickets: the upgrade request carries ?ticket= because
// WebSocket connection helper — returns URL unchanged (no ticket gating in OSS build).
export async function withTicket(url: string): Promise<string> {
  return url;
}
