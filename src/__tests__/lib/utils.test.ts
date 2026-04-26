import { describe, it, expect } from 'vitest';
import { cn } from '@/lib/utils';

describe('cn utility', () => {
  it('should merge conflicting Tailwind classes, later one wins', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4');
    expect(cn('text-red', 'text-blue')).toBe('text-blue');
    expect(cn('m-1', 'm-2', 'm-3')).toBe('m-3');
  });

  it('should handle falsy values', () => {
    expect(cn('a', false, undefined, 'b')).toBe('a b');
    expect(cn('a', null, 'b')).toBe('a b');
    expect(cn(0, 'a', 'b')).toBe('a b');
  });

  it('should handle conditional objects', () => {
    expect(cn({ 'text-red': true, 'text-green': false })).toBe('text-red');
    expect(cn({ 'text-red': false, 'text-green': true })).toBe('text-green');
    // When both are true, tailwind-merge keeps only one (last one wins for conflicting)
    const result = cn({ 'text-red': true, 'text-green': true });
    expect(result).toMatch(/text-green/); // tailwind-merge: last wins
  });

  it('should handle mixed inputs', () => {
    expect(cn('p-2', { 'text-red': true }, 'm-4')).toBe('p-2 text-red m-4');
    expect(cn('base-class', false, 'another-class')).toBe('base-class another-class');
  });
});