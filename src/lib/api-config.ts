// Centralized API configuration
// Cache TTLs, timeouts, and rate limits per endpoint

export const API_CONFIG = {
  // Request timeout in milliseconds
  timeout: parseInt(process.env.OPENALGO_TIMEOUT_MS ?? '10000', 10),

  // Cache TTLs in seconds per endpoint
  cacheTtl: {
    positions: 2,
    orders: 2,
    trades: 2,
    funds: 5,
    quotes: 1,
    history: 300, // 5 minutes for historical data
    placeorder: 0, // No caching for mutations
  } as const,

  // Rate limits per minute per endpoint
  rateLimitPerMinute: parseInt(process.env.RATE_LIMIT_PER_MINUTE ?? '60', 10),

  // Custom rate limits for specific endpoints
  customRateLimits: {
    placeorder: 30, // Stricter limit for order placement
  } as const,
} as const;

/**
 * Get cache TTL for an endpoint
 * @param endpoint - The endpoint name (without /api/v1/ prefix)
 * @returns TTL in seconds, or 0 if caching is disabled
 */
export function getCacheTtl(endpoint: keyof typeof API_CONFIG.cacheTtl): number {
  return API_CONFIG.cacheTtl[endpoint] ?? 0;
}

/**
 * Get rate limit for an endpoint
 * @param endpoint - The endpoint name
 * @returns Rate limit in requests per minute
 */
export function getRateLimit(endpoint: string): number {
  return API_CONFIG.customRateLimits[endpoint as keyof typeof API_CONFIG.customRateLimits] ??
    API_CONFIG.rateLimitPerMinute;
}
