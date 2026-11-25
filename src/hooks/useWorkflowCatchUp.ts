'use client';

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

let lastCatchUpTimestamp = 0;

/**
 * Periodically and on visibility recovery checks for missed workflow runs.
 * Skips invocation if the previous run was under 60s ago.
 * Invalidates ['ai', 'workflows'] query cache if any runs were enqueued.
 */
export function useWorkflowCatchUp(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (typeof document === 'undefined') return;

    const runCatchUp = async (): Promise<void> => {
      const now = Date.now();
      if (now - lastCatchUpTimestamp < 60_000) return;
      lastCatchUpTimestamp = now;

      try {
        const res = await fetch('/api/py/ai/workflows/catch-up', {
          method: 'POST',
        });
        if (!res.ok) return;
        const data = (await res.json()) as { processed?: number; enqueued?: number };
        if (data && typeof data.enqueued === 'number' && data.enqueued > 0) {
          void queryClient.invalidateQueries({ queryKey: ['ai', 'workflows'] });
        }
      } catch {
        // Silent recovery: background sync failures should not disrupt UI
      }
    };

    void runCatchUp();

    const handleVisibilityChange = (): void => {
      if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
        void runCatchUp();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [queryClient]);
}
