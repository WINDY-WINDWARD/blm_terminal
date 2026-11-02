import { describe, expect, it } from 'vitest';
import { toDateTimeLocalValue } from '@/lib/aiWorkflowTime';

describe('toDateTimeLocalValue', () => {
  it("formats '2026-11-05T04:30:00' to '2026-11-05T04:30'", () => {
    expect(toDateTimeLocalValue('2026-11-05T04:30:00')).toBe('2026-11-05T04:30');
  });

  it("formats '2026-11-05T04:30:00Z' to '2026-11-05T04:30'", () => {
    expect(toDateTimeLocalValue('2026-11-05T04:30:00Z')).toBe('2026-11-05T04:30');
  });

  it('returns empty string for null and empty string', () => {
    expect(toDateTimeLocalValue(null)).toBe('');
    expect(toDateTimeLocalValue('')).toBe('');
  });

  it("returns empty string for 'nonsense'", () => {
    expect(toDateTimeLocalValue('nonsense')).toBe('');
  });
});
