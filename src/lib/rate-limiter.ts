// Simple rate limiter using sliding window approach
// Tracks requests per minute per endpoint
// Usage: rateLimiter.isAllowed('endpoint-name') returns true/false

interface RateLimitBucket {
  count: number;
  resetAt: number;
}

class RateLimiter {
  private buckets = new Map<string, RateLimitBucket>();
  private readonly defaultLimitPerMinute: number;
  private readonly customLimits: Map<string, number> = new Map();

  constructor(defaultLimitPerMinute: number = 60) {
    this.defaultLimitPerMinute = defaultLimitPerMinute;

    // Custom limits for specific endpoints
    this.customLimits.set('placeorder', 30); // Stricter limit for order placement
  }

  isAllowed(key: string): boolean {
    const now = Date.now();
    const limit = this.customLimits.get(key) ?? this.defaultLimitPerMinute;

    const bucket = this.buckets.get(key);

    // No existing bucket or bucket has expired
    if (!bucket || now > bucket.resetAt) {
      this.buckets.set(key, {
        count: 1,
        resetAt: now + 60 * 1000, // Reset after 60 seconds
      });
      return true;
    }

    // Check if under limit
    if (bucket.count < limit) {
      bucket.count++;
      return true;
    }

    // Over limit
    return false;
  }

  reset(key?: string): void {
    if (key) {
      this.buckets.delete(key);
    } else {
      this.buckets.clear();
    }
  }

  getStats(key: string): { count: number; limit: number; resetAtMs: number } | null {
    const bucket = this.buckets.get(key);
    if (!bucket) {
      return null;
    }

    const limit = this.customLimits.get(key) ?? this.defaultLimitPerMinute;
    return {
      count: bucket.count,
      limit,
      resetAtMs: bucket.resetAt,
    };
  }
}

export const rateLimiter = new RateLimiter();
