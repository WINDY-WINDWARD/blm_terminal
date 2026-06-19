/**
 * Shared NSE rate limiter — port of backend/app/services/nse_rate_limiter.py.
 *
 * Provides:
 *   - Global NSE concurrency limit (default 2)
 *   - Per-endpoint courtesy delay to avoid flooding NSE
 *   - Request coalescing: in-flight requests are shared, not duplicated
 *   - Circuit breaker with CLOSED → OPEN → HALF_OPEN → CLOSED recovery
 *   - Automatic retry of transient network errors
 *
 * Per-process state. Not shared across workers/replicas.
 */

export class NSEServiceUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NSEServiceUnavailableError';
  }
}

const NSE_CONCURRENCY: number = Number(process.env.NSE_CONCURRENCY ?? '2');
const NSE_COURTESY_DELAY_SECONDS: number = Number(process.env.NSE_COURTESY_DELAY ?? '1.5');
const CIRCUIT_FAIL_MAX: number = Number(process.env.NSE_CIRCUIT_FAIL_MAX ?? '5');
const CIRCUIT_RESET_TIMEOUT: number = Number(process.env.NSE_CIRCUIT_RESET_TIMEOUT ?? '60.0');
const NSE_MAX_RETRIES: number = Number(process.env.NSE_MAX_RETRIES ?? '2');
const NSE_RETRY_BACKOFF: number = Number(process.env.NSE_RETRY_BACKOFF ?? '1.0');

function isRetriable(err: unknown): boolean {
  // Transient network errors only
  if (err instanceof TypeError) return true; // fetch network failures
  if (err instanceof Error && err.name === 'AbortError') return true; // timeouts
  if (err instanceof Error && err.name === 'TimeoutError') return true;
  return false;
}

class Semaphore {
  private available: number;
  private waiters: Array<() => void> = [];

  constructor(permits: number) {
    this.available = permits;
  }

  async acquire(): Promise<void> {
    if (this.available > 0) {
      this.available -= 1;
      return;
    }
    return new Promise<void>((resolve) => {
      this.waiters.push(resolve);
    });
  }

  release(): void {
    const next = this.waiters.shift();
    if (next) {
      next();
    } else {
      this.available += 1;
    }
  }
}

const nseSemaphore = new Semaphore(NSE_CONCURRENCY);

const endpointLocks: Map<string, Promise<void>> = new Map();
const lastRequestAt: Map<string, number> = new Map();

const inflight: Map<string, Promise<unknown>> = new Map();

const CONSECUTIVE_FAILURES: Map<string, number> = new Map();
const CIRCUIT_OPEN: Map<string, boolean> = new Map();
const CIRCUIT_OPENED_AT: Map<string, number> = new Map();
const CIRCUIT_HALF_OPEN: Map<string, boolean> = new Map();

function getOrCreateSerialPromise(key: string): Promise<void> {
  const existing = endpointLocks.get(key);
  if (existing) return existing.then(() => getOrCreateSerialPromise(key));
  const p = Promise.resolve();
  endpointLocks.set(key, p);
  p.finally(() => {
    if (endpointLocks.get(key) === p) endpointLocks.delete(key);
  });
  return p;
}

function checkCircuit(endpointName: string): void {
  if (!CIRCUIT_OPEN.get(endpointName)) return;

  if (CIRCUIT_HALF_OPEN.get(endpointName)) return;

  const openedAt = CIRCUIT_OPENED_AT.get(endpointName) ?? 0;
  const elapsed = (Date.now() - openedAt) / 1000;
  if (elapsed >= CIRCUIT_RESET_TIMEOUT) {
    CIRCUIT_HALF_OPEN.set(endpointName, true);
    return;
  }

  throw new NSEServiceUnavailableError(
    `Circuit breaker is OPEN for '${endpointName}' (opened ${elapsed.toFixed(0)}s ago, reset after ${CIRCUIT_RESET_TIMEOUT.toFixed(0)}s). Will retry automatically.`,
  );
}

function recordSuccess(endpointName: string): void {
  CONSECUTIVE_FAILURES.set(endpointName, 0);
  CIRCUIT_OPEN.set(endpointName, false);
  CIRCUIT_HALF_OPEN.set(endpointName, false);
}

function recordFailure(endpointName: string): void {
  const prev = (CONSECUTIVE_FAILURES.get(endpointName) ?? 0) + 1;
  CONSECUTIVE_FAILURES.set(endpointName, prev);
  if (prev >= CIRCUIT_FAIL_MAX) {
    const wasHalfOpen = CIRCUIT_HALF_OPEN.get(endpointName) ?? false;
    const wasAlreadyOpen = CIRCUIT_OPEN.get(endpointName) ?? false;
    CIRCUIT_OPEN.set(endpointName, true);
    CIRCUIT_HALF_OPEN.set(endpointName, false);
    if (!wasAlreadyOpen || wasHalfOpen) {
      CIRCUIT_OPENED_AT.set(endpointName, Date.now());
    }
  }
}

export interface ThrottleOptions {
  retries?: number;
  backoff?: number;
  /**
   * Key used to coalesce concurrent identical in-flight requests.
   *
   * MUST uniquely identify the work being performed (e.g. include the
   * symbol/params). Using only the `endpointName` will cause distinct
   * requests — such as fetching different symbols against the same
   * endpoint — to share a single underlying call, which returns the same
   * data to every caller. The circuit-breaker, courtesy-delay, and
   * serial-promise queue continue to key off `endpointName` because
   * those are per-endpoint concerns, not per-request.
   */
  coalesceKey: string;
}

/**
 * Execute an NSE API call with global concurrency limiting, per-endpoint
 * courtesy delay, request coalescing, and circuit breaker protection.
 */
export async function throttledNseCall<T>(
  endpointName: string,
  fn: () => Promise<T>,
  opts: ThrottleOptions,
): Promise<T> {
  checkCircuit(endpointName);

  const existing = inflight.get(opts.coalesceKey);
  if (existing) {
    return existing as Promise<T>;
  }

  const promise = (async () => {
    await nseSemaphore.acquire();
    try {
      const serial = getOrCreateSerialPromise(endpointName);
      await serial;

      const last = lastRequestAt.get(endpointName) ?? 0;
      const elapsedSec = (Date.now() - last) / 1000;
      const wait = NSE_COURTESY_DELAY_SECONDS - elapsedSec;
      if (wait > 0) {
        await new Promise<void>((r) => setTimeout(r, wait * 1000));
      }

      const maxRetries = opts.retries ?? NSE_MAX_RETRIES;
      const backoff = opts.backoff ?? NSE_RETRY_BACKOFF;
      let lastExc: unknown;
      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          const result = await fn();
          recordSuccess(endpointName);
          return result;
        } catch (exc) {
          lastExc = exc;
          if (attempt < maxRetries && isRetriable(exc)) {
            const sleepMs = backoff * Math.pow(2, attempt) * 1000;
            await new Promise<void>((r) => setTimeout(r, sleepMs));
            continue;
          }
          break;
        } finally {
          lastRequestAt.set(endpointName, Date.now());
        }
      }

      recordFailure(endpointName);
      throw lastExc;
    } finally {
      nseSemaphore.release();
    }
  })();

  inflight.set(opts.coalesceKey, promise);
  // The inflight-entry cleanup must run on BOTH success and failure.
  // We can't use `.finally()` here because that returns a NEW promise that
  // inherits the rejection state — and since nobody awaits that new
  // promise, Node would log an `unhandledRejection` whenever `fn()` throws.
  // Instead, attach a noop rejection handler (the original rejection is
  // already surfaced to the caller via the returned `promise`).
  promise.then(
    () => {
      if (inflight.get(opts.coalesceKey) === promise) inflight.delete(opts.coalesceKey);
    },
    () => {
      if (inflight.get(opts.coalesceKey) === promise) inflight.delete(opts.coalesceKey);
    },
  );

  return promise;
}

export function getCircuitStats(): Record<
  string,
  { open: boolean; halfOpen: boolean; failures: number; openedAt: number | null }
> {
  const out: Record<
    string,
    { open: boolean; halfOpen: boolean; failures: number; openedAt: number | null }
  > = {};
  const keys = new Set<string>([
    ...CONSECUTIVE_FAILURES.keys(),
    ...CIRCUIT_OPEN.keys(),
  ]);
  for (const k of keys) {
    out[k] = {
      open: CIRCUIT_OPEN.get(k) ?? false,
      halfOpen: CIRCUIT_HALF_OPEN.get(k) ?? false,
      failures: CONSECUTIVE_FAILURES.get(k) ?? 0,
      openedAt: CIRCUIT_OPENED_AT.get(k) ?? null,
    };
  }
  return out;
}
