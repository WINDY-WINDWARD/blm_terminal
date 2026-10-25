'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  emptySessionState,
  NEW_CHAT_KEY,
  type AttachedDocument,
  type ChatMessage,
  type ScriptCard,
  type SessionState,
  type AiMode,
} from '@/types/aiWidgetTypes';

export type { AiMode, SessionState };
export { emptySessionState, NEW_CHAT_KEY };

// Module-level persistence (survives unmount/remount)
const _persistedMap = new Map<number | null, SessionState>();
let _persistedActiveKey: number | null = null;
let _persistedHasSent = false;

export interface UseAiSessionPersistenceReturn {
  sessionMap: Map<number | null, SessionState>;
  setSessionMap: React.Dispatch<React.SetStateAction<Map<number | null, SessionState>>>;
  activeKey: number | null;
  setActiveKey: React.Dispatch<React.SetStateAction<number | null>>;
  hasSentRef: React.MutableRefObject<boolean>;
  patchSession: (key: number | null, patch: Partial<SessionState>) => void;
}

export function useAiSessionPersistence(defaultModel: string): UseAiSessionPersistenceReturn {
  const [sessionMap, setSessionMap] = useState<Map<number | null, SessionState>>(() => {
    if (_persistedMap.size > 0) {
      const restored = new Map<number | null, SessionState>();
      for (const [k, v] of _persistedMap) {
        restored.set(k, { ...v, isStreaming: false, abortController: null });
      }
      return restored;
    }
    return new Map([[NEW_CHAT_KEY, emptySessionState(defaultModel)]]);
  });

  const [activeKey, setActiveKey] = useState<number | null>(() => {
    if (_persistedMap.size > 0) return _persistedActiveKey;
    return NEW_CHAT_KEY;
  });

  const hasSentRef = useRef(_persistedHasSent);

  // Sync back to module-level cache
  useEffect(() => {
    _persistedMap.clear();
    for (const [k, v] of sessionMap) {
      const { abortController: _, ...rest } = v;
      _persistedMap.set(k, rest as SessionState);
    }
  }, [sessionMap]);

  useEffect(() => {
    _persistedActiveKey = activeKey;
  }, [activeKey]);

  useEffect(() => {
    _persistedHasSent = hasSentRef.current;
  });

  const patchSession = useCallback(
    (key: number | null, patch: Partial<SessionState>) => {
      setSessionMap((prev) => {
        const next = new Map(prev);
        const existing = next.get(key) ?? emptySessionState(defaultModel);
        next.set(key, { ...existing, ...patch });
        return next;
      });
    },
    [defaultModel],
  );

  return {
    sessionMap,
    setSessionMap,
    activeKey,
    setActiveKey,
    hasSentRef,
    patchSession,
  };
}
