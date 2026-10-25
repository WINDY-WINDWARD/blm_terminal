'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import {
  activePanelsAtom,
  aiPrefillAtom,
  focusedPanelAtom,
  scriptChartHandoffAtom,
  AI_REFINE_REQUEST_KEY,
} from '@/store/terminalStore';
import { resolveChartPanel } from '@/lib/scripts/handoff';
import { stampStashedCard } from '@/lib/scripts/cardStash';
import { NEW_CHAT_KEY, type ScriptCard, type SessionState } from '@/types/aiWidgetTypes';

export interface UseScriptHandoffOptions {
  activeKey: number | null;
  setActiveKey: (key: number | null) => void;
  setSessionMap: React.Dispatch<React.SetStateAction<Map<number | null, SessionState>>>;
  patchSession: (key: number | null, patch: Partial<SessionState>) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export interface UseScriptHandoffReturn {
  acceptCard: (card: ScriptCard) => void;
  discardCard: (card: ScriptCard) => void;
}

export function useScriptHandoff({
  activeKey,
  setActiveKey,
  setSessionMap,
  patchSession,
  inputRef,
}: UseScriptHandoffOptions): UseScriptHandoffReturn {
  const panels = useAtomValue(activePanelsAtom);
  const focusedPanel = useAtomValue(focusedPanelAtom);
  const setFocusedPanel = useSetAtom(focusedPanelAtom);
  const setChartHandoff = useSetAtom(scriptChartHandoffAtom);
  const [prefill, setPrefill] = useAtom(aiPrefillAtom);

  const patchCard = useCallback(
    (key: number | null, card: ScriptCard, patch: Partial<ScriptCard>) => {
      if (patch.accepted !== undefined || patch.dismissed !== undefined) {
        stampStashedCard(key, card, {
          accepted: patch.accepted,
          dismissed: patch.dismissed,
        });
      }
      setSessionMap((prev) => {
        const next = new Map(prev);
        const state = next.get(key);
        if (!state) return prev;
        next.set(key, {
          ...state,
          messages: state.messages.map((m) =>
            m.card && m.card.script_id === card.script_id && m.card.rev_no === card.rev_no
              ? { ...m, card: { ...m.card, ...patch } }
              : m,
          ),
        });
        return next;
      });
    },
    [setSessionMap],
  );

  const acceptCard = useCallback(
    (card: ScriptCard) => {
      const target = resolveChartPanel(panels, focusedPanel);
      setChartHandoff({ scriptId: card.script_id, panelId: target, ts: Date.now() });
      setFocusedPanel(target);
      patchCard(activeKey, card, { accepted: true });
    },
    [focusedPanel, panels, setChartHandoff, setFocusedPanel, patchCard, activeKey],
  );

  const discardCard = useCallback(
    (card: ScriptCard) => {
      patchCard(activeKey, card, { dismissed: true });
    },
    [patchCard, activeKey],
  );

  const consumedPrefillRef = useRef(0);
  useEffect(() => {
    if (!prefill || prefill.ts <= consumedPrefillRef.current) return;
    consumedPrefillRef.current = prefill.ts;
    patchSession(activeKey, { input: prefill.text, mode: 'script' });
    setPrefill(null);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [prefill, activeKey, patchSession, setPrefill, inputRef]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(AI_REFINE_REQUEST_KEY);
      if (!raw) return;
      window.localStorage.removeItem(AI_REFINE_REQUEST_KEY);
      const req = JSON.parse(raw) as { text?: string; ts?: number };
      if (!req?.text) return;
      patchSession(NEW_CHAT_KEY, { input: req.text, mode: 'script' });
      setActiveKey(NEW_CHAT_KEY);
    } catch {
      /* ignore */
    }
  }, [patchSession, setActiveKey]);

  return {
    acceptCard,
    discardCard,
  };
}
