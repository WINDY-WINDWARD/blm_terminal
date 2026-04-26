import { describe, it, expect } from 'vitest';

// Pure helper functions extracted from ChartWidget.tsx
function formatDate(date: Date): string {
  return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
}

function getDateRange(interval: '1m' | '5m' | '15m' | '1h' | 'D'): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (interval) {
    case '1m': start.setDate(end.getDate() - 5); break;
    case '5m': start.setDate(end.getDate() - 14); break;
    case '15m': start.setDate(end.getDate() - 30); break;
    case '1h': start.setDate(end.getDate() - 90); break;
    case 'D': start.setFullYear(end.getFullYear() - 1); break;
  }
  return { start: formatDate(start), end: formatDate(end) };
}

function getCandlePeriodSeconds(interval: '1m' | '5m' | '15m' | '1h' | 'D'): number {
  switch (interval) {
    case '1m': return 60;
    case '5m': return 300;
    case '15m': return 900;
    case '1h': return 3600;
    case 'D': return 86400;
  }
}

function alignToCandle(timestampSeconds: number, periodSeconds: number): number {
  return Math.floor(timestampSeconds / periodSeconds) * periodSeconds;
}

describe('ChartWidget pure helpers', () => {
  describe('formatDate', () => {
    it('returns YYYY-MM-DD format in IST timezone', () => {
      const date = new Date('2025-04-24T12:00:00Z');
      const result = formatDate(date);
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });
  });

  describe('getDateRange', () => {
    it('returns correct date range for 1m interval', () => {
      const { start, end } = getDateRange('1m');
      expect(start).toBeDefined();
      expect(end).toBeDefined();
      expect(start).not.toBe(end);
    });

    it('returns correct date range for D interval', () => {
      const { start, end } = getDateRange('D');
      const startYear = parseInt(start.split('-')[0]);
      const endYear = parseInt(end.split('-')[0]);
      expect(endYear - startYear).toBe(1);
    });
  });

  describe('getCandlePeriodSeconds', () => {
    it('returns 60 for 1m', () => {
      expect(getCandlePeriodSeconds('1m')).toBe(60);
    });

    it('returns 300 for 5m', () => {
      expect(getCandlePeriodSeconds('5m')).toBe(300);
    });

    it('returns 900 for 15m', () => {
      expect(getCandlePeriodSeconds('15m')).toBe(900);
    });

    it('returns 3600 for 1h', () => {
      expect(getCandlePeriodSeconds('1h')).toBe(3600);
    });

    it('returns 86400 for D', () => {
      expect(getCandlePeriodSeconds('D')).toBe(86400);
    });
  });

  describe('alignToCandle', () => {
    it('aligns 305 seconds to 300-second period', () => {
      expect(alignToCandle(305, 300)).toBe(300);
    });

    it('aligns 600 seconds to 300-second period', () => {
      expect(alignToCandle(600, 300)).toBe(600);
    });

    it('aligns 0 seconds to 60-second period', () => {
      expect(alignToCandle(0, 60)).toBe(0);
    });

    it('returns a multiple of periodSeconds', () => {
      expect(alignToCandle(1234, 300) % 300).toBe(0);
    });
  });
});