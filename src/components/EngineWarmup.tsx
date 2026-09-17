'use client';

import { useEffect, useState } from 'react';

/**
 * Shared engine warm-up copy + rotation hook.
 *
 * Used by the FirstLaunchModal backend step and the AuthGuard connecting
 * gate so both surfaces show the same lively loading messages while the
 * packaged Python backend boots (30-90s cold start).
 */

/** How many failed probes (~5s apart) before we stop showing warm-up copy. */
export const ENGINE_WARM_LIMIT = 12;

export const ENGINE_WARMUP_MESSAGES = [
  'Warming up the data engine…',
  'Cold start in process — getting things ready…',
  'Getting that data warmed up…',
  'Spinning up market data pipelines…',
  'Loading NSE snapshots and indicators…',
  'Syncing background workers…',
  'Almost there — running final checks…',
];

/** Cycles through ENGINE_WARMUP_MESSAGES while `active` is true. */
export function useWarmupMessage(active: boolean, intervalMs = 2800): string {
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(
      () => setIdx((i) => (i + 1) % ENGINE_WARMUP_MESSAGES.length),
      intervalMs,
    );
    return () => clearInterval(t);
  }, [active, intervalMs]);
  return ENGINE_WARMUP_MESSAGES[idx];
}
