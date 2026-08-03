import type { SavedLayout } from '@/store/terminalStore';

/**
 * Result of normalizing and truncating a layout name.
 * Includes whether the name was actually shortened from the input.
 */
export interface NormalizeResult {
  name: string;
  wasShortened: boolean;
}

export interface LayoutTombstone {
  name: string;
  deletedAt: number;
}

export interface LayoutSyncResponse {
  layouts: SavedLayout[];
  tombstones: LayoutTombstone[];
}

export interface QueueOperation {
  id: string;
  userId: number;
  type: 'save' | 'rename' | 'delete';
  name: string; // Current name (old name for rename)
  payload?: SavedLayout; // Layout data for save/rename (original for rename)
  oldName?: string; // For rename
  newName?: string; // For rename
  timestamp: number;
  status?: 'pending' | 'error'; // Track operation state
  error?: string; // Last error message
}

/**
 * Helper: Basic normalization (trim, lowercase).
 */
function basicNormalize(name: string): string {
  return name.trim().toLowerCase();
}

/**
 * Helper: Truncate to max length.
 */
function truncateToMaxLen(name: string, maxLen: number = 64): string {
  return name.length > maxLen ? name.slice(0, maxLen) : name;
}

/**
 * Normalize a name for SAVE operations.
 * Rules:
 * 1. Trim and lowercase.
 * 2. Limit to 64 characters.
 * 3. Do NOT apply collision suffix (allows exact-name overwrites).
 *
 * Returns the normalized name.
 */
export function normalizeSaveName(name: string): string {
  return normalizeSaveNameWithFlag(name).name;
}

export function normalizeSaveNameWithFlag(
  name: string,
  existingNames: string[] = []
): NormalizeResult {
  const clean = basicNormalize(name);
  if (!clean) return { name: '', wasShortened: false };

  const wasShortened = clean.length > 64;
  const candidate = truncateToMaxLen(clean);
  const existing = new Set(existingNames.map(basicNormalize).filter(Boolean));

  // An exact short name is an intentional overwrite. Only truncation creates
  // a collision that needs an automatic suffix.
  if (!wasShortened || !existing.has(candidate)) {
    return { name: candidate, wasShortened };
  }

  for (let counter = 2; counter < 1000; counter++) {
    const suffix = `-${counter}`;
    const result = candidate.slice(0, 64 - suffix.length) + suffix;
    if (!existing.has(result)) return { name: result, wasShortened: true };
  }

  return { name: candidate, wasShortened };
}

/**
 * Normalize a name for RENAME operations.
 * Rules:
 * 1. Trim and lowercase.
 * 2. Limit to 64 characters.
 * 3. If truncation creates a collision (excluding oldName), apply suffix -2, -3, etc.
 * 4. Keep final string at 64 characters or fewer.
 *
 * existingNames: normalized lowercase names to check against
 * oldName: the old name (excluded from collision detection)
 *
 * Returns the normalized name with optional collision suffix.
 */
/**
 * Normalize a layout name for RENAME operations.
 * 
 * Collision semantics:
 * - Exact short-name collisions (no truncation needed):
 *   → Preserved WITHOUT suffix. UI will show conflict message.
 * - Truncation collisions (name > 64 chars and truncated form collides):
 *   → Suffix added (-2, -3, etc.) to make it unique.
 * - OldName is excluded from collision detection (allows no-op renames).
 * 
 * Returns name <= 64 characters.
 */
export function normalizeRenameName(
  name: string,
  existingNames: string[] = [],
  oldName?: string
): string {
  const result = normalizeRenameNameWithFlag(name, existingNames, oldName);
  return result.name;
}

/**
 * Normalize and truncate a layout name to <= 64 characters.
 * For backward compatibility, this is the generic version.
 * New code should use normalizeSaveName() or normalizeRenameName().
 * 
 * Rules:
 * 1. Trim whitespace.
 * 2. Lowercase.
 * 3. Limit final result to 64 characters.
 * 4. If collision with existing name, try -2, -3, etc (oldName excluded).
 * 5. Keep the final string at 64 characters or fewer.
 *
 * Returns the normalized name and a flag indicating whether truncation occurred.
 */
export function normalizeAndTruncateName(
  name: string,
  existingNames: string[] = [],
  currentOldName?: string
): string {
  const result = normalizeAndTruncateNameWithFlag(name, existingNames, currentOldName);
  return result.name;
}

/**
 * Normalize and truncate with a flag indicating whether the input was shortened.
 * 
 * Collision semantics:
 * - Exact short-name collisions: preserved WITHOUT suffix
 * - Truncation collisions: suffix added (-2, -3, etc.)
 * - wasShortened: true ONLY if truncation occurred, not for exact collisions
 * 
 * Used internally to track whether to show the shortening notice.
 * Note: This is the generic version. Use normalizeRenameNameWithFlag() for renames
 * to ensure proper semantics with oldName exclusion.
 */
function _findUniqueSuffix(
  candidate: string,
  normalizedExisting: Set<string>,
  maxLen: number
): string | null {
  let counter = 2;
  while (counter < 1000) {
    const suffix = `-${counter}`;
    const baseLen = maxLen - suffix.length;
    const truncatedBase = candidate.slice(0, baseLen);
    const result = truncatedBase + suffix;
    if (!normalizedExisting.has(result)) {
      return result;
    }
    counter++;
  }
  return null;
}

/**
 * Normalize and truncate with a flag indicating whether the input was shortened.
 * 
 * Collision semantics:
 * - Exact short-name collisions: preserved WITHOUT suffix
 * - Truncation collisions: suffix added (-2, -3, etc.)
 * - wasShortened: true ONLY if truncation occurred, not for exact collisions
 * 
 * Used internally to track whether to show the shortening notice.
 * Note: This is the generic version. Use normalizeRenameNameWithFlag() for renames
 * to ensure proper semantics with oldName exclusion.
 */
export function normalizeAndTruncateNameWithFlag(
  name: string,
  existingNames: string[] = [],
  currentOldName?: string
): NormalizeResult {
  const clean = basicNormalize(name);
  if (!clean) return { name: '', wasShortened: false };

  const maxLen = 64;
  const wasShortened = clean.length > maxLen;
  const candidate = truncateToMaxLen(clean, maxLen);

  const normalizedExisting = new Set(
    existingNames
      .map((n) => basicNormalize(n))
      .filter((n) => n && n !== basicNormalize(currentOldName || ''))
  );

  if (!normalizedExisting.has(candidate) || !wasShortened) {
    return { name: candidate, wasShortened };
  }

  const suffixed = _findUniqueSuffix(candidate, normalizedExisting, maxLen);
  if (suffixed) {
    return { name: suffixed, wasShortened: true };
  }

  return { name: candidate, wasShortened };
}

/**
 * Normalize and truncate for RENAME with flag indicating whether truncation occurred.
 * 
 * Collision semantics:
 * - Exact short-name collisions: preserved WITHOUT suffix or shortening flag
 * - Truncation collisions: suffix added (-2, -3, etc.), wasShortened true
 * - wasShortened: true only if truncation occurred
 * - OldName is excluded from collision detection
 */
export function normalizeRenameNameWithFlag(
  name: string,
  existingNames: string[] = [],
  oldName?: string
): NormalizeResult {
  const clean = basicNormalize(name);
  if (!clean) return { name: '', wasShortened: false };

  const maxLen = 64;
  const wasShortened = clean.length > maxLen;
  const candidate = truncateToMaxLen(clean, maxLen);

  // Exclude the old name from collision detection
  const normalizedOldName = oldName ? basicNormalize(oldName) : '';
  const normalizedExisting = new Set(
    existingNames
      .map((n) => basicNormalize(n))
      .filter((n) => n && n !== normalizedOldName)
  );

  // Exact short-name collisions are handled by the UI as a rename conflict.
  // Only a truncated name gets an automatic suffix.
  if (!normalizedExisting.has(candidate) || !wasShortened) {
    return { name: candidate, wasShortened };
  }

  // Apply suffix for truncation collision
  const suffixed = _findUniqueSuffix(candidate, normalizedExisting, maxLen);
  if (suffixed) {
    return { name: suffixed, wasShortened: true };
  }

  return { name: candidate, wasShortened };
}

export function getUserLayoutsKey(userId: number): string {
  return `terminal.savedLayouts.user.${userId}`;
}

export function getUserQueueKey(userId: number): string {
  return `terminal.layoutSyncQueue.${userId}`;
}

/**
 * Centralized persistence helpers for user-scoped layouts.
 */
export function getUserLayouts(userId: number): Record<string, SavedLayout> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = localStorage.getItem(getUserLayoutsKey(userId));
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, SavedLayout>;
  } catch {
    return {};
  }
}

export function setUserLayouts(userId: number, layouts: Record<string, SavedLayout>): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(getUserLayoutsKey(userId), JSON.stringify(layouts));
  } catch (err) {
    console.error('Failed to save user layouts:', err);
  }
}

/**
 * Helper: update user-scoped layout storage and return for atom update.
 * Used in optimistic updates to ensure both atom and localStorage stay in sync.
 */
export function updateAndPersistLayouts(
  userId: number,
  updater: (prev: Record<string, SavedLayout>) => Record<string, SavedLayout>
): Record<string, SavedLayout> {
  const current = getUserLayouts(userId);
  const updated = updater(current);
  setUserLayouts(userId, updated);
  return updated;
}

export function getUserQueue(userId: number): QueueOperation[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(getUserQueueKey(userId));
    if (!raw) return [];
    return JSON.parse(raw) as QueueOperation[];
  } catch {
    return [];
  }
}

export function setUserQueue(userId: number, queue: QueueOperation[]): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(getUserQueueKey(userId), JSON.stringify(queue));
  } catch (err) {
    console.error('Failed to save user sync queue:', err);
  }
}

export function enqueueQueueOperation(
  userId: number,
  op: Omit<QueueOperation, 'id' | 'userId' | 'timestamp'>
): QueueOperation {
  const current = getUserQueue(userId);
  const newOp: QueueOperation = {
    ...op,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    userId,
    timestamp: Date.now(),
  };
  const updated = [...current, newOp];
  setUserQueue(userId, updated);
  return newOp;
}

export function dequeueQueueOperation(userId: number, opId: string): QueueOperation[] {
  const current = getUserQueue(userId);
  const updated = current.filter((item) => item.id !== opId);
  setUserQueue(userId, updated);
  return updated;
}

/**
 * Fetch active saved layouts for the currently authenticated user.
 */
/**
 * Bulk sync local layouts to server and return active layouts + tombstones.
 * Uses save normalization (truncate only, allows exact-name overwrites).
 */
export async function bulkSyncServerLayouts(
  layouts: SavedLayout[]
): Promise<LayoutSyncResponse | null> {
  try {
    // Normalize names in order so truncation cannot silently merge layouts.
    const usedNames: string[] = [];
    const validLayouts = layouts
      .filter((l) => l.name && l.name.trim())
      .map((layout) => {
        const result = normalizeSaveNameWithFlag(layout.name, usedNames);
        usedNames.push(result.name);
        return { ...layout, name: result.name };
      });

    const res = await fetch('/api/py/layouts/bulk-sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(validLayouts),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as LayoutSyncResponse;
    return data;
  } catch (err) {
    console.error('Failed to bulk sync layouts:', err);
    return null;
  }
}

/**
 * Save or overwrite a single layout on the server (explicit action).
 * Uses save normalization (truncate only, allows exact-name overwrites).
 */
export async function saveServerLayout(layout: SavedLayout): Promise<{ ok: boolean; status?: number; terminal?: boolean }> {
  const cleanName = normalizeSaveName(layout.name);
  if (!cleanName) return { ok: false, terminal: true };
  try {
    const payload = { ...layout, name: cleanName };
    const res = await fetch(`/api/py/layouts/${encodeURIComponent(cleanName)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    // 400 (bad request) is terminal
    if (res.status === 400) {
      return { ok: false, status: 400, terminal: true };
    }
    return { ok: res.ok, status: res.status };
  } catch (err) {
    console.error('Failed to save layout to server:', err);
    // Network error - retriable
    return { ok: false, status: 0 };
  }
}

/**
 * Rename a layout on the server.
 * Distinguishes terminal failures (404, 409, 400) from retriable errors (network, 5xx).
 */
export async function renameServerLayout(
  oldName: string,
  newName: string
): Promise<{ ok: boolean; conflict?: boolean; status?: number; terminal?: boolean }> {
  const cleanOld = oldName.trim().toLowerCase();
  const cleanNew = normalizeRenameName(newName);
  if (!cleanNew) return { ok: false, terminal: true };
  try {
    const res = await fetch(`/api/py/layouts/${encodeURIComponent(cleanOld)}/rename`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ newName: cleanNew }),
    });
    // 409: conflict - terminal (UI will show message)
    if (res.status === 409) {
      return { ok: false, conflict: true, status: 409, terminal: true };
    }
    // 404: source no longer exists - terminal (remove operation)
    if (res.status === 404) {
      return { ok: false, status: 404, terminal: true };
    }
    // 400: bad request - terminal
    if (res.status === 400) {
      return { ok: false, status: 400, terminal: true };
    }
    // 5xx or network errors will be caught and returned as retriable
    return { ok: res.ok, status: res.status };
  } catch (err) {
    console.error('Failed to rename layout on server:', err);
    // Network error - retriable (status 0 indicates network error)
    return { ok: false, status: 0 };
  }
}

/**
 * Delete a layout on the server (creates persistent tombstone).
 * Treats 404 as success (desired final state already exists) - terminal success.
 * Distinguishes network errors (retriable) from 404 (terminal).
 */
export async function deleteServerLayout(name: string): Promise<{ ok: boolean; notFound?: boolean; status?: number; terminal?: boolean }> {
  const cleanName = name.trim().toLowerCase();
  try {
    const res = await fetch(`/api/py/layouts/${encodeURIComponent(cleanName)}`, {
      method: 'DELETE',
    });
    if (res.status === 404) {
      // 404: already deleted (desired state) - terminal success
      return { ok: true, notFound: true, status: 404, terminal: true };
    }
    // 400: bad request - terminal
    if (res.status === 400) {
      return { ok: false, status: 400, terminal: true };
    }
    // 5xx or network errors will be caught and returned as retriable
    return { ok: res.ok, status: res.status };
  } catch (err) {
    console.error('Failed to delete layout on server:', err);
    // Network error - retriable (status 0 indicates network error)
    return { ok: false, status: 0 };
  }
}
