export type ColumnDropPlacement = 'before' | 'after';

export function reorderColumns<T extends string>(
  order: readonly T[],
  fromKey: T,
  toKey: T,
  placement: ColumnDropPlacement,
): T[] {
  const fromIndex = order.indexOf(fromKey);
  const toIndex = order.indexOf(toKey);
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) {
    return [...order];
  }

  const next = [...order];
  const [moved] = next.splice(fromIndex, 1);
  const targetIndex = next.indexOf(toKey);
  const insertAt = placement === 'before' ? targetIndex : targetIndex + 1;
  next.splice(insertAt, 0, moved);
  return next;
}
