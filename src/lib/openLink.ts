'use client';

/**
 * Link opening with the Electron link policy.
 *
 * - 'app' → in-app reader window (news/announcement default).
 * - 'external' → the user's own system browser (everything else,
 *   news Ctrl+Click / right-click).
 * Outside Electron (browser dev, tests) falls back to window.open.
 */
export type OpenLinkMode = 'app' | 'external';

export function openLink(url: string, mode: OpenLinkMode): void {
  if (!url) return;
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  const invoke = mode === 'app' ? api?.openInApp : api?.openExternal;
  if (invoke) {
    void invoke.call(api, url);
    return;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

/** Ctrl+Click / Cmd+Click on a news-style row → system browser. */
export function isExternalClick(event: { ctrlKey: boolean; metaKey: boolean }): boolean {
  return event.ctrlKey || event.metaKey;
}
