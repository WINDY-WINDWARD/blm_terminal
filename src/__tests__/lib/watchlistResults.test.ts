import { describe, expect, it } from 'vitest';
import { compareResults, parseResultsDate } from '@/components/widgets/WatchWidget';

describe('parseResultsDate', () => {
  it('parses DD-MMM-YYYY into a UTC timestamp', () => {
    expect(parseResultsDate('09-Nov-2026')).toBe(Date.UTC(2026, 10, 9));
    expect(parseResultsDate('1-Jan-2025')).toBe(Date.UTC(2025, 0, 1));
  });

  it('returns null for malformed dates', () => {
    expect(parseResultsDate('')).toBeNull();
    expect(parseResultsDate('2026-11-09')).toBeNull();
    expect(parseResultsDate('09-Xyz-2026')).toBeNull();
  });
});

describe('compareResults', () => {
  it('sorts by date in both directions', () => {
    const a = { date: '01-Jan-2025', status: 'past' as const };
    const b = { date: '01-Jun-2026', status: 'upcoming' as const };
    expect(compareResults(a, b, 'asc')).toBeLessThan(0);
    expect(compareResults(a, b, 'desc')).toBeGreaterThan(0);
  });

  it('puts upcoming before past when dates match', () => {
    const past = { date: '01-Jan-2025', status: 'past' as const };
    const upcoming = { date: '01-Jan-2025', status: 'upcoming' as const };
    expect(compareResults(upcoming, past, 'asc')).toBeLessThan(0);
    expect(compareResults(past, upcoming, 'asc')).toBeGreaterThan(0);
  });

  it('keeps missing dates last in both directions', () => {
    const present = { date: '01-Jan-2025', status: 'past' as const };
    expect(compareResults(null, present, 'asc')).toBeGreaterThan(0);
    expect(compareResults(null, present, 'desc')).toBeGreaterThan(0);
  });
});
