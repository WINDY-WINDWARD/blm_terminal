import { describe, expect, it } from 'vitest';
import { reorderColumns } from '@/lib/columnOrder';

describe('reorderColumns', () => {
  const order = ['a', 'b', 'c', 'd'];

  it('moves a column before the target', () => {
    expect(reorderColumns(order, 'd', 'b', 'before')).toEqual(['a', 'd', 'b', 'c']);
  });

  it('moves a column after the target', () => {
    expect(reorderColumns(order, 'a', 'c', 'after')).toEqual(['b', 'c', 'a', 'd']);
  });

  it('returns the original order when source and target match', () => {
    expect(reorderColumns(order, 'b', 'b', 'before')).toEqual(order);
  });

  it('returns the original order when a key is unknown', () => {
    expect(reorderColumns(order, 'missing', 'b', 'before')).toEqual(order);
    expect(reorderColumns(order, 'a', 'missing', 'after')).toEqual(order);
  });

  it('preserves hidden columns relative to the moved column', () => {
    expect(reorderColumns(['a', 'hidden', 'b', 'c'], 'c', 'a', 'before')).toEqual([
      'c',
      'a',
      'hidden',
      'b',
    ]);
  });
});
