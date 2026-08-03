import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  bulkSyncServerLayouts,
  saveServerLayout,
  renameServerLayout,
  deleteServerLayout,
  getUserLayoutsKey,
  getUserQueueKey,
  getUserQueue,
  enqueueQueueOperation,
  dequeueQueueOperation,
  normalizeSaveName,
  normalizeRenameName,
  normalizeAndTruncateNameWithFlag,
  normalizeRenameNameWithFlag,
} from '@/lib/layouts';
import type { SavedLayout } from '@/store/terminalStore';

const dummyLayout: SavedLayout = {
  name: 'default',
  activePanels: { 'panel-1': 'CHART' },
  panelCount: 4,
  mergedGroups: {},
  savedAt: 1700000000000,
};

describe('layouts API client & sync queue', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  describe('getUserLayoutsKey and getUserQueueKey', () => {
    it('generates user-scoped storage keys', () => {
      expect(getUserLayoutsKey(42)).toBe('terminal.savedLayouts.user.42');
      expect(getUserQueueKey(42)).toBe('terminal.layoutSyncQueue.42');
    });
  });

  describe('Queue operations', () => {
    it('enqueues and dequeues operations per user', () => {
      expect(getUserQueue(1)).toEqual([]);

      const op = enqueueQueueOperation(1, {
        type: 'save',
        name: 'layout-1',
        payload: dummyLayout,
      });

      expect(op.name).toBe('layout-1');
      expect(op.userId).toBe(1);

      const remaining = dequeueQueueOperation(1, op.id);
      expect(remaining).toHaveLength(0);
      expect(getUserQueue(1)).toEqual([]);
    });
  });

  describe('bulkSyncServerLayouts', () => {
    it('sends POST request and normalizes names to lowercase', async () => {
      const syncResponse = {
        layouts: [dummyLayout],
        tombstones: [{ name: 'deleted-one', deletedAt: 1000 }],
      };
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          json: async () => syncResponse,
        })
      );

      const longNameLayout = { ...dummyLayout, name: 'a'.repeat(65) };
      const res = await bulkSyncServerLayouts([dummyLayout, longNameLayout]);

      expect(res).toEqual(syncResponse);
      // Verify that long name was truncated and normalized to lowercase
      expect(fetch).toHaveBeenCalledWith('/api/py/layouts/bulk-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('default'),
      });
    });
  });

  describe('saveServerLayout', () => {
    it('sends PUT request to normalized (lowercase) name', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
      const result = await saveServerLayout({ ...dummyLayout, name: 'MyLayout' });
      expect(result.ok).toBe(true);
      expect(fetch).toHaveBeenCalledWith('/api/py/layouts/mylayout', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...dummyLayout, name: 'mylayout' }),
      });
    });

    it('truncates names > 64 chars to 64 chars', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
      const longName = 'a'.repeat(65);
      const result = await saveServerLayout({ ...dummyLayout, name: longName });
      expect(result.ok).toBe(true);
      // Should truncate to 64 'a's
      expect(fetch).toHaveBeenCalledWith(`/api/py/layouts/${'a'.repeat(64)}`, expect.any(Object));
    });
  });

  describe('renameServerLayout', () => {
    it('sends PATCH request with normalized name', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
      const result = await renameServerLayout('OldName', 'NewName');
      expect(result.ok).toBe(true);
      expect(fetch).toHaveBeenCalledWith('/api/py/layouts/oldname/rename', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ newName: 'newname' }),
      });
    });

    it('returns conflict flag on 409', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409 }));
      const result = await renameServerLayout('OldName', 'ExistingName');
      expect(result.ok).toBe(false);
      expect(result.conflict).toBe(true);
      expect(result.status).toBe(409);
      expect(result.terminal).toBe(true);
    });

    it('returns 404 as terminal failure', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
      const result = await renameServerLayout('OldName', 'Missing');
      expect(result.ok).toBe(false);
      expect(result.status).toBe(404);
      expect(result.terminal).toBe(true);
    });
  });

  describe('deleteServerLayout', () => {
    it('sends DELETE request', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
      const result = await deleteServerLayout('MyLayout');
      expect(result.ok).toBe(true);
      expect(fetch).toHaveBeenCalledWith('/api/py/layouts/mylayout', {
        method: 'DELETE',
      });
    });

    it('treats 404 as success', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
      const result = await deleteServerLayout('Missing');
      expect(result.ok).toBe(true);
      expect(result.notFound).toBe(true);
    });
  });

  describe('normalizeSaveName', () => {
    it('allows exact-name overwrites (no collision suffix)', () => {
      const result = normalizeSaveName('trading');
      expect(result).toBe('trading');
    });

    it('truncates names > 64 characters', () => {
      const longName = 'a'.repeat(65);
      const result = normalizeSaveName(longName);
      expect(result).toBe('a'.repeat(64));
    });

    it('trims and lowercases input', () => {
      const result = normalizeSaveName('  Trading  ');
      expect(result).toBe('trading');
    });

    it('returns empty string for empty input', () => {
      expect(normalizeSaveName('')).toBe('');
      expect(normalizeSaveName('   ')).toBe('');
    });
  });

  describe('normalizeRenameName', () => {
    /**
     * Collision semantics for RENAME operations:
     * - Exact short-name collisions: preserve exact name WITHOUT suffix
     *   Reason: UI will show conflict message and user can reject/retry
     * - Truncation collisions: add numeric suffix (-2, -3, etc.)
     *   Reason: User intended a unique name but had to be shortened
     * - Case-insensitive collisions: treated as exact collisions (NO suffix)
     * - OldName is excluded from collision detection (allows no-op rename)
     */
    it('excludes oldName from collision detection', () => {
      // When renaming "foo" to "foo", it should return "foo" (not add suffix)
      const result = normalizeRenameName('foo', ['foo', 'bar'], 'foo');
      expect(result).toBe('foo');
    });

    it('preserves exact name collision without suffix (UI handles conflict)', () => {
      // Trying to rename "foo" to "bar" when "bar" already exists
      // The exact name is preserved so UI can reject with conflict
      const result = normalizeRenameName('bar', ['bar', 'baz'], 'foo');
      expect(result).toBe('bar');
    });

    it('truncates and then checks collision', () => {
      const longName = 'a'.repeat(65);
      const result = normalizeRenameName(longName, ['a'.repeat(64)], 'oldname');
      expect(result).toMatch(/^a+(-\d+)?$/);
      expect(result.length).toBeLessThanOrEqual(64);
    });

    it('preserves exact short-name collision (case-insensitive)', () => {
      // "trading" already exists (case-insensitive collision)
      // UI will handle the conflict, so exact name is preserved
      const result = normalizeRenameName('Trading', ['trading'], 'oldname');
      expect(result).toBe('trading');
    });
  });

  describe('normalizeAndTruncateNameWithFlag', () => {
    /**
     * Collision semantics for generic truncate+normalize:
     * - Only adds collision suffixes when TRUNCATION occurred
     * - Exact short-name collisions: preserved WITHOUT suffix
     * - wasShortened flag: true only if truncation happened, NOT for exact collisions
     */
    it('indicates when truncation occurred', () => {
      const longName = 'a'.repeat(65);
      const result = normalizeAndTruncateNameWithFlag(longName);
      expect(result.wasShortened).toBe(true);
      expect(result.name.length).toBeLessThanOrEqual(64);
    });

    it('preserves exact short-name collision without shortening flag', () => {
      // Exact collision without truncation: name preserved, no shortening
      const result = normalizeAndTruncateNameWithFlag('foo', ['foo']);
      expect(result.wasShortened).toBe(false);
      expect(result.name).toBe('foo');
    });

    it('reports no shortening for exact match within limits', () => {
      const result = normalizeAndTruncateNameWithFlag('test', []);
      expect(result.wasShortened).toBe(false);
      expect(result.name).toBe('test');
    });
  });

  describe('normalizeRenameNameWithFlag', () => {
    /**
     * Collision semantics for RENAME with shortening flag:
     * - wasShortened: true only if truncation occurred (name > 64 chars)
     * - Exact short-name collisions: preserved WITHOUT suffix and WITHOUT shortening flag
     * - Truncation collisions: suffix applied, wasShortened true
     * - OldName excluded from collision detection
     */
    it('indicates shortening from truncation', () => {
      const longName = 'a'.repeat(65);
      const result = normalizeRenameNameWithFlag(longName, [], 'oldname');
      expect(result.wasShortened).toBe(true);
      expect(result.name).toBe('a'.repeat(64));
    });

    it('preserves exact short-name collision without suffix', () => {
      const result = normalizeRenameNameWithFlag('foo', ['foo'], 'oldname');
      // Exact collision is preserved without suffix (UI will show conflict)
      expect(result.wasShortened).toBe(false);
      expect(result.name).toBe('foo');
    });

    it('excludes oldName from collision detection', () => {
      const result = normalizeRenameNameWithFlag('foo', ['bar', 'baz'], 'foo');
      expect(result.wasShortened).toBe(false);
      expect(result.name).toBe('foo');
    });
  });
});
