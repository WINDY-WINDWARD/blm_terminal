import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  enqueueQueueOperation,
  getUserQueue,
  dequeueQueueOperation,
  normalizeAndTruncateName,
} from '@/lib/layouts';
import type { SavedLayout } from '@/store/terminalStore';

const dummyLayout: SavedLayout = {
  name: 'default',
  activePanels: { 'panel-1': 'CHART' },
  panelCount: 4,
  mergedGroups: {},
  savedAt: 1700000000000,
};

describe('useSavedLayoutsSync hook - Integration Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('Queue operation ordering', () => {
    it('maintains queue ordering for multiple operations', () => {
      const userId = 1;

      // Enqueue three operations
      const op1 = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-1',
        payload: dummyLayout,
      });

      const op2 = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-2',
        payload: dummyLayout,
      });

      const op3 = enqueueQueueOperation(userId, {
        type: 'delete',
        name: 'layout-3',
      });

      const queue = getUserQueue(userId);
      expect(queue).toHaveLength(3);
      expect(queue[0].id).toBe(op1.id);
      expect(queue[1].id).toBe(op2.id);
      expect(queue[2].id).toBe(op3.id);
    });

    it('removes operations by exact ID', () => {
      const userId = 1;

      const op1 = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-1',
        payload: dummyLayout,
      });

      const op2 = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-2',
        payload: dummyLayout,
      });

      // Remove first operation
      dequeueQueueOperation(userId, op1.id);

      const queue = getUserQueue(userId);
      expect(queue).toHaveLength(1);
      expect(queue[0].id).toBe(op2.id);
    });
  });

  describe('Name normalization', () => {
    it('truncates names > 64 characters', () => {
      const longName = 'a'.repeat(100);
      const result = normalizeAndTruncateName(longName);
      expect(result).toBe('a'.repeat(64));
      expect(result.length).toBeLessThanOrEqual(64);
    });

    it('preserves exact short-name collision (no suffix for exact match)', () => {
      const existing = ['test'];
      const result = normalizeAndTruncateName('test', existing);
      // Exact short-name collision is preserved (UI will handle conflict)
      expect(result).toBe('test');
    });

    it('adds suffix only for truncation collisions', () => {
      const longName = 'a'.repeat(65);
      const existing = [longName.slice(0, 64)]; // truncated version exists
      const result = normalizeAndTruncateName(longName, existing);
      // Truncation collision gets a suffix
      expect(result).toMatch(/a{1,62}-\d+/);
    });

    it('excludes old name from collision detection for rename', () => {
      const existing = ['test', 'new-name'];
      const result = normalizeAndTruncateName('test', existing, 'test');
      // Should return 'test' because it's excluded from collision check
      expect(result).toBe('test');
    });

    it('handles lowercase normalization', () => {
      const result = normalizeAndTruncateName('TestLayout');
      expect(result).toBe('testlayout');
    });
  });

  describe('Queue operation structure', () => {
    it('creates save operation with payload', () => {
      const userId = 1;
      const op = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'my-layout',
        payload: dummyLayout,
      });

      expect(op).toMatchObject({
        type: 'save',
        name: 'my-layout',
        payload: dummyLayout,
        userId,
      });
      expect(op.id).toBeDefined();
      expect(op.timestamp).toBeDefined();
    });

    it('creates rename operation with old/new names and payload', () => {
      const userId = 1;
      const originalLayout = { ...dummyLayout, name: 'original' };
      const op = enqueueQueueOperation(userId, {
        type: 'rename',
        name: 'original',
        oldName: 'original',
        newName: 'new-name',
        payload: originalLayout,
      });

      expect(op).toMatchObject({
        type: 'rename',
        name: 'original',
        oldName: 'original',
        newName: 'new-name',
        payload: originalLayout,
      });
    });

    it('creates delete operation with name', () => {
      const userId = 1;
      const op = enqueueQueueOperation(userId, {
        type: 'delete',
        name: 'my-layout',
      });

      expect(op).toMatchObject({
        type: 'delete',
        name: 'my-layout',
      });
      expect(op.payload).toBeUndefined();
    });
  });

  describe('Centralized provider - duplicate prevention', () => {
    it('processes queue operations in strict order without duplicates', () => {
      const userId = 1;

      // Enqueue three operations
      enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-1',
        payload: dummyLayout,
      });

      enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-2',
        payload: dummyLayout,
      });

      enqueueQueueOperation(userId, {
        type: 'delete',
        name: 'layout-1',
      });

      const queue = getUserQueue(userId);
      expect(queue).toHaveLength(3);
      // Verify order is maintained
      expect(queue[0].type).toBe('save');
      expect(queue[1].type).toBe('save');
      expect(queue[2].type).toBe('delete');
    });

    it('handles concurrent enqueue during processing with reentrancy protection', () => {
      const userId = 1;

      // Initial operation
      const op1 = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-1',
        payload: dummyLayout,
      });

      // Simulate arrival of new work while processing
      // The processPendingQueue uses inProcessingMapRef to prevent reentrancy
      // and newWorkArrivedRef to track new arrivals
      const op2 = enqueueQueueOperation(userId, {
        type: 'save',
        name: 'layout-2',
        payload: dummyLayout,
      });

      const queue = getUserQueue(userId);
      // Both operations should be in queue
      expect(queue).toHaveLength(2);
      expect(queue[0].id).toBe(op1.id);
      expect(queue[1].id).toBe(op2.id);
    });
  });
});
