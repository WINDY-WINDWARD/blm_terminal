'use client';

import { createContext, useContext, useEffect, useRef, useCallback, ReactNode } from 'react';
import { useAtom, useSetAtom } from 'jotai';
import {
  authAtom,
  savedLayoutsAtom,
  layoutSyncStatusAtom,
  type SavedLayout,
} from '@/store/terminalStore';
import {
  bulkSyncServerLayouts,
  saveServerLayout,
  renameServerLayout,
  deleteServerLayout,
  getUserQueue,
  dequeueQueueOperation,
  getUserLayouts,
  setUserLayouts,
  type QueueOperation,
} from '@/lib/layouts';

/**
 * Context for centralized layout sync controller.
 * Ensures only one sync processor owns all queue operations, retries, and initial sync.
 */
interface SavedLayoutsSyncContextType {
  processPendingQueue: (userId: number) => Promise<void>;
}

const SavedLayoutsSyncContext = createContext<SavedLayoutsSyncContextType | undefined>(undefined);

/**
 * Provider component that owns the centralized sync controller.
 * Mounts once in Providers.tsx and manages:
 * - Initial sync on user login
 * - Account transitions (logout/login/switch)
 * - Queue processing with reentrancy protection
 * - Online/reconnect event handling
 * - Retry interval (10 second poll)
 */
export function SavedLayoutsSyncProvider({ children }: { children: ReactNode }) {
  const [auth] = useAtom(authAtom);
  const [, setSavedLayouts] = useAtom(savedLayoutsAtom);
  const setSyncStatus = useSetAtom(layoutSyncStatusAtom);

  const activeUserIdRef = useRef<number | null>(null);
  const inProcessingMapRef = useRef<Record<number, boolean>>({});
  const newWorkArrivedRef = useRef<Record<number, boolean>>({});

  const userId = auth?.user?.id ?? null;

  /**
   * Restore a layout to its original name after a conflict.
   * Assumes the operation has the original payload stored.
   */
  const rollbackRenameConflict = useCallback(
    (op: QueueOperation, targetUserId: number) => {
      if (op.type !== 'rename' || !op.oldName || !op.newName || !op.payload) return;

      setSavedLayouts((prev) => {
        const next = { ...prev };
        // Remove the failed new name
        delete next[op.newName!.toLowerCase()];
        // Restore the original layout
        next[op.oldName!.toLowerCase()] = op.payload!;
        return next;
      });

      // Also restore in localStorage
      const layouts = getUserLayouts(targetUserId);
      delete layouts[op.newName!.toLowerCase()];
      layouts[op.oldName!.toLowerCase()] = op.payload!;
      setUserLayouts(targetUserId, layouts);
    },
    [setSavedLayouts]
  );

  /**
   * Reconcile local state after a terminal failure (404, 409, 400).
   * Ensures local state matches server reality:
   * - Rename 404: source no longer exists, remove it locally
   * - Delete 404: already deleted, remove it locally
   */
  const reconcileLocalStateAfterTerminalFailure = useCallback(
    (op: QueueOperation, targetUserId: number) => {
      if (op.type === 'rename' && op.oldName) {
        // Source no longer exists - remove local state
        setSavedLayouts((prev) => {
          const next = { ...prev };
          delete next[op.oldName!.toLowerCase()];
          return next;
        });
        const layouts = getUserLayouts(targetUserId);
        delete layouts[op.oldName!.toLowerCase()];
        setUserLayouts(targetUserId, layouts);
      } else if (op.type === 'delete' && op.name) {
        // Already deleted on server (404), ensure removed locally
        setSavedLayouts((prev) => {
          const next = { ...prev };
          delete next[op.name!.toLowerCase()];
          return next;
        });
        const layouts = getUserLayouts(targetUserId);
        delete layouts[op.name!.toLowerCase()];
        setUserLayouts(targetUserId, layouts);
      }
    },
    [setSavedLayouts]
  );

  const reconcileSuccessfulOperation = useCallback(
    (op: QueueOperation, targetUserId: number) => {
      setSavedLayouts((prev) => {
        const next = { ...prev };

        if (op.type === 'save' && op.payload) {
          next[op.payload.name.toLowerCase()] = op.payload;
        } else if (op.type === 'rename' && op.oldName && op.newName && op.payload) {
          delete next[op.oldName.toLowerCase()];
          next[op.newName.toLowerCase()] = { ...op.payload, name: op.newName };
        } else if (op.type === 'delete') {
          delete next[op.name.toLowerCase()];
        }

        setUserLayouts(targetUserId, next);
        return next;
      });
    },
    [setSavedLayouts]
  );

  /**
   * Process queue operations strictly in order.
   * Maintains reentrancy protection and stops on first failure.
   * Preserves conflict status even after queue becomes empty.
   */
  const processPendingQueue = useCallback(
    async (targetUserId: number) => {
      if (inProcessingMapRef.current[targetUserId]) {
        // Mark that new work arrived while processing
        newWorkArrivedRef.current[targetUserId] = true;
        return;
      }

      inProcessingMapRef.current[targetUserId] = true;
      newWorkArrivedRef.current[targetUserId] = false;

      try {
        // Track if a conflict occurred during this processing cycle
        let lastConflictError: string | null = null;

        // Main processing loop
        while (true) {
          // Verify user hasn't changed
          if (activeUserIdRef.current !== targetUserId) break;

          const queue = getUserQueue(targetUserId);
          if (queue.length === 0) {
            if (activeUserIdRef.current === targetUserId) {
              // If a conflict occurred, preserve the error status
              if (lastConflictError) {
                setSyncStatus({ status: 'error', pendingCount: 0, lastError: lastConflictError });
              } else {
                setSyncStatus({ status: 'synced', pendingCount: 0 });
              }
            }
            break;
          }

          setSyncStatus({ status: 'pending', pendingCount: queue.length });

          // Process first operation in queue
          const op = queue[0];
          let success = false;
          let conflict = false;
          let terminal = false;

          // Verify identity before sending request
          if (activeUserIdRef.current !== targetUserId) break;

          try {
            if (op.type === 'save' && op.payload) {
              const res = await saveServerLayout(op.payload);
              success = res.ok;
              terminal = res.terminal ?? false;
            } else if (op.type === 'rename' && op.oldName && op.newName) {
              const res = await renameServerLayout(op.oldName, op.newName);
              success = res.ok;
              conflict = !!res.conflict;
              terminal = res.terminal ?? false;
            } else if (op.type === 'delete') {
              const res = await deleteServerLayout(op.name);
              success = res.ok;
              terminal = res.terminal ?? false;
            }
          } catch (err) {
            console.error(`Failed to process ${op.type} operation:`, err);
            success = false;
            terminal = false; // Network errors are retriable
          }

          // Verify identity before applying result
          if (activeUserIdRef.current !== targetUserId) break;

          if (success) {
            dequeueQueueOperation(targetUserId, op.id);
            reconcileSuccessfulOperation(op, targetUserId);
            // Continue processing next operation
          } else if (conflict && op.type === 'rename') {
            // Rename conflict: restore original layout and remove failed operation
            rollbackRenameConflict(op, targetUserId);
            dequeueQueueOperation(targetUserId, op.id);
            // Track the conflict error to preserve it
            lastConflictError = `Rename conflict for "${op.newName}" — reverted to "${op.oldName}"`;
            // Continue with next operation
            if (activeUserIdRef.current === targetUserId) {
              const remaining = getUserQueue(targetUserId);
              setSyncStatus({
                status: remaining.length > 0 ? 'pending' : 'error',
                pendingCount: remaining.length,
                lastError: lastConflictError,
              });
            }
          } else if (terminal) {
            // Terminal failure (404, 409, 400): remove operation and continue queue
            // This prevents permanent queue wedging on non-retriable errors
            reconcileLocalStateAfterTerminalFailure(op, targetUserId);
            dequeueQueueOperation(targetUserId, op.id);
            // Continue with next operation in queue
            if (activeUserIdRef.current === targetUserId) {
              const remaining = getUserQueue(targetUserId);
              setSyncStatus({
                status: remaining.length > 0 ? 'pending' : 'synced',
                pendingCount: remaining.length,
              });
            }
          } else {
            // Retriable error (network/5xx): stop processing to preserve ordering
            const remaining = getUserQueue(targetUserId);
            if (activeUserIdRef.current === targetUserId) {
              setSyncStatus({
                status: 'error',
                pendingCount: remaining.length,
                lastError: `Failed to sync operation: ${op.type}`,
              });
            }
            break;
          }
        }

        // Final check: process newly arrived work if any
        if (newWorkArrivedRef.current[targetUserId] && activeUserIdRef.current === targetUserId) {
          newWorkArrivedRef.current[targetUserId] = false;
          // Recursive call, but the lock prevents true reentrancy
          if (inProcessingMapRef.current[targetUserId]) {
            inProcessingMapRef.current[targetUserId] = false;
            await processPendingQueue(targetUserId);
            return;
          }
        }
      } finally {
        inProcessingMapRef.current[targetUserId] = false;
      }
    },
    [setSyncStatus, rollbackRenameConflict, reconcileSuccessfulOperation, reconcileLocalStateAfterTerminalFailure]
  );

  const performInitialSync = useCallback(
    async (targetUserId: number) => {
      const legacyMigrationOwner = localStorage.getItem(
        'terminal.savedLayouts.legacyMigrationOwner'
      );

      let initialLocalMap: Record<string, SavedLayout> = {};

      if (!legacyMigrationOwner) {
        // First authenticated session — claim global legacy localStorage layouts
        const legacyRaw = localStorage.getItem('terminal.savedLayouts');
        if (legacyRaw) {
          try {
            initialLocalMap = JSON.parse(legacyRaw) as Record<string, SavedLayout>;
          } catch {
            initialLocalMap = {};
          }
        }
      } else {
        // Read user-scoped local storage
        initialLocalMap = getUserLayouts(targetUserId);
      }

      // Read pending queue and identify rename destinations to exclude from bulk sync
      // This prevents queued renames from being created as new layouts before the rename request runs
      const queue = getUserQueue(targetUserId);
      const renameDestinations = new Set<string>();
      for (const op of queue) {
        if (op.type === 'rename' && op.newName) {
          renameDestinations.add(op.newName.toLowerCase());
        }
      }

      // Filter out rename destinations before bulk sync to prevent them from being
      // treated as new layouts by passive sync
      const localList = Object.values(initialLocalMap).filter(
        (layout) => !renameDestinations.has(layout.name.toLowerCase())
      );

      const syncRes = await bulkSyncServerLayouts(localList);

      // Verify active user hasn't changed while awaiting backend
      if (activeUserIdRef.current !== targetUserId) return;

      if (syncRes) {
        if (!legacyMigrationOwner) {
          localStorage.setItem(
            'terminal.savedLayouts.legacyMigrationOwner',
            String(targetUserId)
          );
        }

        const updatedMap: Record<string, SavedLayout> = {};

        // 1. Keep local layouts (server always wins for existing layouts)
        // 2. Add active server layouts (server always wins)
        for (const layout of syncRes.layouts) {
          updatedMap[layout.name.toLowerCase()] = layout;
        }

        // 3. Remove tombstones (server tombstones remove stale local layouts)
        for (const tomb of syncRes.tombstones) {
          delete updatedMap[tomb.name.toLowerCase()];
        }

        // Persist into user-scoped storage and update atom
        setUserLayouts(targetUserId, updatedMap);
        setSavedLayouts(updatedMap);

        // Process any pending local queue operations
        await processPendingQueue(targetUserId);
      } else {
        // Server unreachable during startup — load local user storage as fallback
        // Persist fallback layouts to user-scoped storage to prevent loss on logout
        setUserLayouts(targetUserId, initialLocalMap);
        setSavedLayouts(initialLocalMap);
        setSyncStatus({
          status: 'error',
          pendingCount: getUserQueue(targetUserId).length,
          lastError: 'Server unreachable during startup',
        });
      }
    },
    [processPendingQueue, setSavedLayouts, setSyncStatus]
  );

  // Handle user login/logout/switch
  useEffect(() => {
    if (!userId) {
      if (activeUserIdRef.current !== null) {
        activeUserIdRef.current = null;
        setSavedLayouts({}); // Immediately clear atom on logout
        setSyncStatus({ status: 'synced', pendingCount: 0 });
        // Don't clear the queue or user-scoped storage for privacy reasons
      }
      return;
    }

    if (activeUserIdRef.current === userId) return;

    // Immediately clear previous user's layouts before hydrating new user
    activeUserIdRef.current = userId;
    setSavedLayouts({});

    performInitialSync(userId);
  }, [userId, performInitialSync, setSavedLayouts, setSyncStatus]);

  // Handle online / reconnect events
  useEffect(() => {
    const handleOnline = () => {
      if (userId) {
        processPendingQueue(userId);
      }
    };
    window.addEventListener('online', handleOnline);
    return () => window.removeEventListener('online', handleOnline);
  }, [userId, processPendingQueue]);

  // Interval check for pending retries (every 10 seconds)
  useEffect(() => {
    if (!userId) return;
    const interval = setInterval(() => {
      const queue = getUserQueue(userId);
      if (queue.length > 0) {
        processPendingQueue(userId);
      }
    }, 10_000);
    return () => clearInterval(interval);
  }, [userId, processPendingQueue]);

  return (
    <SavedLayoutsSyncContext.Provider value={{ processPendingQueue }}>
      {children}
    </SavedLayoutsSyncContext.Provider>
  );
}

/**
 * Hook to access the centralized sync controller.
 * Components should call this hook instead of instantiating their own sync processor.
 */
const DEFAULT_SYNC_FALLBACK: SavedLayoutsSyncContextType = {
  processPendingQueue: async () => {},
};

export function useSavedLayoutsSync() {
  const context = useContext(SavedLayoutsSyncContext);
  return context ?? DEFAULT_SYNC_FALLBACK;
}
