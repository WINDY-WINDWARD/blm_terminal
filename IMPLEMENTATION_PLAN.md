# Layout Sync Runtime Issues - Implementation Plan

## Overview
Three critical runtime issues and several cleanup items identified in second review.
All changes require your approval before execution.

---

## CRITICAL ISSUES

### Issue 1: Rename Into Tombstone Returns 500
**Location:** `backend/app/routers/layout.py:202-209` (rename_user_layout)

**Problem:**
- Delete tombstone and rename are flushed together
- SQLAlchemy may emit UPDATE before DELETE
- Unique constraint (user_id, name) rejects rename with 500 error

**Current Code:**
```python
if target_existing and target_existing.deleted_at is not None:
    await db.delete(target_existing)

layout.name = new_name
await db.commit()  # ← Problem: DELETE might be emitted AFTER UPDATE
```

**Fix:**
```python
if target_existing and target_existing.deleted_at is not None:
    await db.delete(target_existing)
    await db.flush()  # ← Ensure DELETE executes FIRST

layout.name = new_name
await db.commit()
```

**Why It Works:**
- `flush()` executes pending operations immediately
- Guarantees DELETE completes before UPDATE
- Maintains unique constraint satisfaction

**Affected Tests:** Need to add test for rename-into-tombstone scenario

---

### Issue 2: Queue Permanently Wedges on Rename 404
**Location:** `src/components/SavedLayoutsSyncProvider.tsx:150-175`

**Problem:**
- Rename whose source no longer exists returns 404
- Current code treats 404 like a retryable network error
- Operation stays at queue head forever, blocking all later operations

**Current Code:**
```javascript
} else if (op.type === 'rename' && op.oldName && op.newName) {
  const res = await renameServerLayout(op.oldName, op.newName);
  success = res.ok;
  conflict = !!res.conflict;
} else if (op.type === 'delete') {
  const res = await deleteServerLayout(op.name);
  success = res.ok;  // ← 404 treated as retryable
}

if (success) {
  // dequeue
} else if (conflict && op.type === 'rename') {
  // rollback conflict
} else {
  // stop and retry (WRONG: also catches 404)
  break;
}
```

**Fix Strategy:**
1. Modify API functions to return HTTP status code
2. Distinguish terminal vs retriable failures:
   - **Terminal (remove operation):** 404, 409 conflict, 400 bad request
   - **Retriable (keep in queue):** Network errors, 5xx errors
3. For terminal failures, reconcile local state and continue

**Implementation Detail - Modified renameServerLayout():**
```javascript
export async function renameServerLayout(
  oldName: string,
  newName: string
): Promise<{ ok: boolean; conflict?: boolean; status?: number; terminal?: boolean }> {
  // ... existing validation ...
  try {
    const res = await fetch(...);
    if (res.status === 409) {
      return { ok: false, conflict: true, status: 409, terminal: true };
    }
    if (res.status === 404) {
      // Source layout doesn't exist - terminal failure
      return { ok: false, status: 404, terminal: true };
    }
    return { ok: res.ok, status: res.status };
  } catch (err) {
    // Network error - retriable
    return { ok: false, status: 0 }; // status 0 = network error
  }
}
```

**Implementation Detail - Queue Processor:**
```javascript
try {
  if (op.type === 'rename' && op.oldName && op.newName) {
    const res = await renameServerLayout(op.oldName, op.newName);
    success = res.ok;
    conflict = !!res.conflict;
    terminal = !!res.terminal;  // ← Track terminal failures
  } else if (op.type === 'delete') {
    const res = await deleteServerLayout(op.name);
    success = res.ok;
    terminal = res.notFound;  // ← 404 already treated as success
  }
} catch (err) {
  success = false;
  terminal = false;  // ← Network error is retriable
}

if (success) {
  dequeueQueueOperation(targetUserId, op.id);
  reconcileSuccessfulOperation(op, targetUserId);
} else if (conflict && op.type === 'rename') {
  rollbackRenameConflict(op, targetUserId);
  dequeueQueueOperation(targetUserId, op.id);
  lastConflictError = `...`;
} else if (terminal) {
  // Terminal failure: remove operation and reconcile state
  reconcileLocalStateAfterTerminalFailure(op, targetUserId);
  dequeueQueueOperation(targetUserId, op.id);
  // Continue with next operation (don't break)
} else {
  // Retriable error: stop and retry
  break;
}
```

**Helper for Terminal Failures:**
```javascript
const reconcileLocalStateAfterTerminalFailure = useCallback(
  (op: QueueOperation, targetUserId: number) => {
    if (op.type === 'rename') {
      // Source no longer exists - remove local state
      setSavedLayouts((prev) => {
        const next = { ...prev };
        delete next[op.oldName!.toLowerCase()];
        return next;
      });
      const layouts = getUserLayouts(targetUserId);
      delete layouts[op.oldName!.toLowerCase()];
      setUserLayouts(targetUserId, layouts);
    } else if (op.type === 'delete') {
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
```

**Affected Tests:**
- Add test: rename source no longer exists (404)
- Add test: delete already deleted (404)
- Add test: queue continues after terminal failures
- Add test: later operations process after terminal error

---

### Issue 3: Offline First-Login Erases Pre-Auth Layouts
**Location:** `src/components/SavedLayoutsSyncProvider.tsx:288-295`

**Problem:**
1. Initial sync fails (server unreachable)
2. Fallback code loads legacy layouts into atom but NOT into user-scoped storage
3. User logs out (clears atom, atom and legacy key out of sync)
4. Later login sees empty legacy key and overwrites user storage with empty state

**Current Code:**
```javascript
if (syncRes) {
  // ... success path, persists to user-scoped storage ...
  setUserLayouts(targetUserId, updatedMap);
} else {
  // Server unreachable during startup — load local user storage as fallback
  setSavedLayouts(initialLocalMap);  // ← Atom updated
  // ← BUT user-scoped storage NOT persisted!
  setSyncStatus({...});
}
```

**Fix:**
```javascript
if (syncRes) {
  // ... success path ...
  setUserLayouts(targetUserId, updatedMap);
  setSavedLayouts(updatedMap);
  await processPendingQueue(targetUserId);
} else {
  // Server unreachable during startup — load local user storage as fallback
  // Persist fallback layouts to user-scoped storage to prevent loss on logout
  setUserLayouts(targetUserId, initialLocalMap);  // ← Persist to storage
  setSavedLayouts(initialLocalMap);                // ← Persist to atom
  setSyncStatus({
    status: 'error',
    pendingCount: getUserQueue(targetUserId).length,
    lastError: 'Server unreachable during startup',
  });
}
```

**Why It Works:**
- Both atom and user-scoped storage are now synchronized
- Logout clears atom but leaves user-scoped storage intact
- On next login, legacy migration check finds populated user storage
- No data loss

**Affected Tests:**
- Add test: offline first-login with legacy layouts
- Add test: logout after offline first-login preserves user storage
- Add test: re-login shows previously offline layouts

---

## CLEANUP ITEMS

### Cleanup 1: Validate Path Names on Backend (64 char limit)
**Location:** `backend/app/routers/layout.py` - all endpoints

**Current:** No validation on PUT endpoint (only in frontend)

**Fix:** Add validation to `save_or_update_user_layout`:
```python
clean_name = name.strip().lower()
if len(clean_name) > 64:
    raise HTTPException(status_code=400, detail="Layout name must be ≤ 64 characters")
if body.name != clean_name:
    body.name = clean_name
```

---

### Cleanup 2: Replace alert() With layoutToastAtom
**Locations:**
- `src/components/TerminalContainer.tsx` - shortening notice
- `src/components/widgets/SettingsWidget.tsx` - conflict notice

**Current:** Uses `alert()` from browser

**Fix:** Use existing `layoutToastAtom` for consistent UI:
```javascript
const [, setLayoutToast] = useAtom(layoutToastAtom);
setLayoutToast({
  type: 'info',
  title: 'Layout Name Shortened',
  message: `Your name was shortened from 65 to 64 characters.`,
  duration: 5000,
});
```

---

### Cleanup 3: Remove Dead Code & Consolidate
**Dead Code:**
- Remove `fetchServerLayouts()` from `src/lib/layouts.ts` (unused)

**Duplication:**
- Normalization suffix logic appears in `normalizeAndTruncateNameWithFlag()` and `normalizeRenameNameWithFlag()`
- Extract into shared helper `_addCollisionSuffix(candidate, existing, maxLen)` if consolidation risk is low

---

## TEST UPDATES REQUIRED

### Backend Tests (Python)
- [ ] Test rename-into-tombstone doesn't return 500
- [ ] Test offline first-login persists fallback layouts

### Frontend Tests (TypeScript)
- [ ] Test rename 404 removes operation and continues queue
- [ ] Test delete 404 treated as success
- [ ] Test network errors remain retriable
- [ ] Test offline first-login with legacy layouts
- [ ] Test queue continues after terminal failure
- [ ] Test terminal vs retriable failure distinction

---

## VERIFICATION CHECKLIST

After implementation:
- [ ] Backend rename-into-tombstone does not return 500
- [ ] Rename 404 removes operation without blocking queue
- [ ] Delete 404 removes operation without blocking queue
- [ ] Network errors remain queued for retry
- [ ] Offline first-login layouts persist and don't get lost
- [ ] Queue processes all operations (no permanent wedge)
- [ ] layoutToastAtom used instead of alert()
- [ ] Backend validates 64-char limit
- [ ] Build: successful, no new errors
- [ ] Tests: all pass
- [ ] ESLint: no new issues

---

## EXECUTION ORDER

1. **Backend Fix** - Rename-into-tombstone flush ordering (lowest risk)
2. **Frontend Critical** - Terminal failure handling for 4xx
3. **Frontend Critical** - Distinguish retriable vs non-retriable
4. **Frontend Critical** - Offline first-login persistence
5. **Backend Validation** - 64-char limit on PUT
6. **Frontend UI** - Replace alert() with toast
7. **Cleanup** - Remove dead code (if low risk)
8. **Tests** - Update affected tests
9. **Verification** - Run test suite and build

---

## APPROVAL REQUIRED

Please confirm you'd like to proceed with this plan, or request modifications before I start implementation.

Key decision points:
- Should terminal failures (404/409/400) clear the operation or retry?
  → Answer: Terminal failures should remove operation, continue queue (prevents wedge)
  
- Should offline fallback layouts be persisted immediately?
  → Answer: Yes (prevents loss on logout)
  
- Should we consolidate suffix logic or keep duplication?
  → Answer: Keep separate unless consolidation is clearly low-risk (extract if trivial)
