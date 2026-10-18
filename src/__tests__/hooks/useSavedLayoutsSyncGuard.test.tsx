import { describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useSavedLayoutsSync } from '@/components/SavedLayoutsSyncProvider';

describe('useSavedLayoutsSync provider guard', () => {
  it('throws when rendered outside SavedLayoutsSyncProvider', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => renderHook(() => useSavedLayoutsSync())).toThrow(
      'useSavedLayoutsSync must be used within SavedLayoutsSyncProvider'
    );

    consoleError.mockRestore();
  });
});
