'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { unstable_batchedUpdates } from 'react-dom';
import type { UseQueryResult } from '@tanstack/react-query';
import {
  emptySessionState,
  NEW_CHAT_KEY,
  sanitizeAiErrorMessage,
  type AttachedDocument,
  type ChatMessage,
  type ModelOption,
  type PersonaId,
  type ScriptCard,
  type SessionDetail,
  type SessionState,
  type StreamEvent,
  type AiMode,
} from '@/types/aiWidgetTypes';
import { getStashedCards, migrateStash, pruneStashedSession, reattachStashedCards, stashCard } from '@/lib/scripts/cardStash';
import type { RouteModelCatalogResponse } from '@/types/aiRoutes';

export interface UseAiChatSessionOptions {
  sessionMap: Map<number | null, SessionState>;
  setSessionMap: React.Dispatch<React.SetStateAction<Map<number | null, SessionState>>>;
  activeKey: number | null;
  setActiveKey: React.Dispatch<React.SetStateAction<number | null>>;
  patchSession: (key: number | null, patch: Partial<SessionState>) => void;
  defaultModel: string;
  availableModels: ModelOption[];
  catalogData?: RouteModelCatalogResponse;
  symbol: string;
  exchange: string;
  hasSentRef: React.MutableRefObject<boolean>;
  refetchSessions: () => Promise<unknown>;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export interface UseAiChatSessionReturn {
  currentSession: SessionState;
  activePersona: PersonaId | null;
  setActivePersona: React.Dispatch<React.SetStateAction<PersonaId | null>>;
  streamRouteLabel: string | null;
  streamElapsed: number;
  streamingKeys: Set<number | null>;
  sendMessage: (forcedInput?: string, replaceLastAssistant?: boolean) => Promise<void>;
  handleStop: () => void;
  retryLastMessage: () => void;
  startNewChat: (mode?: AiMode) => void;
  loadSession: (id: number) => Promise<void>;
  deleteSession: (id: number) => Promise<void>;
}

export function useAiChatSession({
  sessionMap,
  setSessionMap,
  activeKey,
  setActiveKey,
  patchSession,
  defaultModel,
  availableModels,
  catalogData,
  symbol,
  exchange,
  hasSentRef,
  refetchSessions,
  inputRef,
}: UseAiChatSessionOptions): UseAiChatSessionReturn {
  const [activePersona, setActivePersona] = useState<PersonaId | null>(null);
  const [streamRouteLabel, setStreamRouteLabel] = useState<string | null>(null);
  const [streamElapsed, setStreamElapsed] = useState(0);

  const currentSession = sessionMap.get(activeKey) ?? emptySessionState(defaultModel);

  // Sync models into existing sessions if defaultModel becomes available
  useEffect(() => {
    if (!defaultModel || availableModels.length === 0) return;
    const validIds = new Set(availableModels.map((m) => m.id));
    setSessionMap((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const [key, state] of next) {
        if (!state.model || !validIds.has(state.model)) {
          next.set(key, { ...state, model: defaultModel });
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [defaultModel, availableModels, setSessionMap]);

  const ongoingAbortsRef = useRef<Set<AbortController>>(new Set());
  useEffect(() => {
    return () => {
      for (const ctrl of ongoingAbortsRef.current) {
        ctrl.abort();
      }
    };
  }, []);

  const streamingKeys = new Set<number | null>(
    [...sessionMap.entries()].filter(([, s]) => s.isStreaming).map(([k]) => k),
  );

  const loadSession = useCallback(
    async (id: number) => {
      setActiveKey(id);
      setActivePersona(null);
      setTimeout(() => inputRef.current?.focus(), 50);

      if (sessionMap.get(id)?.isStreaming) return;

      try {
        const res = await fetch(`/api/py/ai/chat/sessions/${id}`);
        if (!res.ok) {
          console.error(`Failed to load session ${id}: ${res.status}`);
          return;
        }
        const data: SessionDetail = await res.json();
        const SCRIPT_TOOL_NAMES = new Set([
          'list_scripts',
          'get_script',
          'validate_script_code',
          'create_script',
          'revise_script',
        ]);
        const hasScriptActivity = data.messages.some((m) =>
          (m.tool_calls ?? []).some((t) => SCRIPT_TOOL_NAMES.has(t)),
        );
        patchSession(id, {
          model: data.model,
          documents: data.documents ?? [],
          messages: reattachStashedCards(
            data.messages.map((m) => ({
              role: m.role as 'user' | 'assistant',
              content: m.content,
              toolCalls: m.tool_calls ?? undefined,
              attachments: m.attachments ?? undefined,
            })),
            getStashedCards(id),
          ),
          ...(hasScriptActivity ? { mode: 'script' as const } : {}),
        });
      } catch (err) {
        console.error('loadSession error:', err);
      }
    },
    [sessionMap, patchSession, setActiveKey, inputRef],
  );

  const deleteSession = useCallback(
    async (id: number) => {
      sessionMap.get(id)?.abortController?.abort();

      const res = await fetch(`/api/py/ai/chat/sessions/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        console.error(`Failed to delete session ${id}: ${res.status}`);
        return;
      }
      pruneStashedSession(id);
      setSessionMap((prev) => {
        const next = new Map(prev);
        next.delete(id);
        return next;
      });
      if (activeKey === id) setActiveKey(NEW_CHAT_KEY);
      void refetchSessions();
    },
    [sessionMap, activeKey, refetchSessions, setSessionMap, setActiveKey],
  );

  const startNewChat = useCallback(
    (mode: AiMode = 'research') => {
      setSessionMap((prev) => {
        const next = new Map(prev);
        next.set(NEW_CHAT_KEY, emptySessionState(defaultModel, mode));
        return next;
      });
      setActiveKey(NEW_CHAT_KEY);
      setActivePersona(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    },
    [defaultModel, setSessionMap, setActiveKey, inputRef],
  );

  const sendMessage = useCallback(
    async (forcedInput?: string, replaceLastAssistant?: boolean) => {
      const sessionKey = activeKey;
      const sessionState = sessionMap.get(sessionKey) ?? emptySessionState(defaultModel);
      const trimmed = (forcedInput ?? sessionState.input).trim();

      if (!trimmed || sessionState.isStreaming) return;

      const documentIds = (sessionState.documents ?? []).map((document) => document.id);
      const userMessage: ChatMessage = {
        role: 'user',
        content: trimmed,
        attachments: documentIds.length ? documentIds : undefined,
      };
      const priorMessages = replaceLastAssistant
        ? sessionState.messages.filter(
            (_, i, arr) => !(arr[i].role === 'assistant' && i === arr.length - 1),
          )
        : sessionState.messages;
      const historyWithUser = [...priorMessages, userMessage];

      const abort = new AbortController();
      ongoingAbortsRef.current.add(abort);

      hasSentRef.current = true;

      const validModelIds = new Set(availableModels.map((m) => m.id));
      const modelToSend = sessionState.model && validModelIds.has(sessionState.model) ? sessionState.model : defaultModel;
      const sendRouteLabel = (catalogData?.routes ?? []).find((r) => r.models.some((m) => m.id === modelToSend))?.label ?? null;
      setStreamRouteLabel(sendRouteLabel);
      setStreamElapsed(0);
      const streamStart = Date.now();
      const elapsedTimer = setInterval(() => setStreamElapsed(Math.floor((Date.now() - streamStart) / 1000)), 1000);
      const optimisticMessages = [...historyWithUser, { role: 'assistant' as const, content: '' }];
      patchSession(sessionKey, {
        messages: optimisticMessages,
        input: '',
        isStreaming: true,
        toolsDone: false,
        abortController: abort,
      });

      let liveKey: number | null = sessionKey;
      const migrationFallback: SessionState = {
        messages: optimisticMessages,
        input: '',
        isStreaming: true,
        toolsDone: false,
        model: modelToSend,
        mode: sessionState.mode ?? 'research',
        documents: sessionState.documents ?? [],
        abortController: abort,
      };

      let assistantContent = '';
      let assistantToolCalls: string[] = [];
      let assistantCard: ScriptCard | undefined;

      const writeStreamState = (patch: Partial<SessionState>) => {
        setSessionMap((prev) => {
          const next = new Map(prev);
          const existing = next.get(liveKey) ?? emptySessionState(defaultModel);
          next.set(liveKey, { ...existing, ...patch });
          return next;
        });
      };

      let firstByteGuard: ReturnType<typeof setTimeout> | null = null;
      try {
        const res = await fetch('/api/py/ai/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
          },
          signal: abort.signal,
          body: JSON.stringify({
            messages: historyWithUser.map((m) => ({ role: m.role, content: m.content })),
            symbol: symbol.toUpperCase(),
            exchange: exchange.toUpperCase(),
            model: modelToSend,
            session_id: sessionKey,
            persona: activePersona,
            mode: sessionState.mode ?? 'research',
            document_ids: documentIds,
          }),
        });

        if (!res.ok || !res.body) {
          const text = await res.text();
          let displayError = text.slice(0, 200);
          try {
            const parsed = JSON.parse(text) as { error?: string };
            if (parsed.error) displayError = parsed.error.slice(0, 200);
          } catch {
            /* not JSON */
          }
          writeStreamState({
            messages: [
              ...historyWithUser,
              { role: 'assistant', content: `Error: ${res.status} — ${displayError}`, isError: true },
            ],
            isStreaming: false,
            abortController: null,
          });
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let streamDone = false;

        let firstEventReceived = false;
        firstByteGuard = setTimeout(() => {
          if (!firstEventReceived) abort.abort(new Error('First-byte timeout: the provider did not answer within 100s'));
        }, 100_000);
        while (!streamDone) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;

            let event: StreamEvent;
            firstEventReceived = true;
            if (firstByteGuard) clearTimeout(firstByteGuard);
            try {
              event = JSON.parse(raw) as StreamEvent;
            } catch {
              continue;
            }

            if (event.type === 'session_id') {
              const assignedId = event.id;
              if (liveKey !== assignedId) {
                const fromKey = liveKey;
                migrateStash(fromKey, assignedId);
                unstable_batchedUpdates(() => {
                  setSessionMap((prev) => {
                    const next = new Map(prev);
                    const fromNext = next.get(liveKey);
                    const existing = fromNext && fromNext.messages.length > 0 ? fromNext : migrationFallback;
                    next.delete(liveKey);
                    next.set(assignedId, existing);
                    return next;
                  });
                  setActiveKey((prev) => (prev === sessionKey ? assignedId : prev));
                });
                liveKey = assignedId;
                void refetchSessions();
              }
            } else if (event.type === 'token') {
              assistantContent += event.text;
              writeStreamState({
                messages: [
                  ...historyWithUser,
                  {
                    role: 'assistant',
                    content: assistantContent,
                    toolCalls: assistantToolCalls.length ? [...assistantToolCalls] : undefined,
                    ...(assistantCard ? { card: assistantCard } : {}),
                  },
                ],
              });
            } else if (event.type === 'tool_call') {
              assistantToolCalls = [...assistantToolCalls, event.name];
              writeStreamState({
                messages: [
                  ...historyWithUser,
                  {
                    role: 'assistant',
                    content: assistantContent,
                    toolCalls: [...assistantToolCalls],
                    ...(assistantCard ? { card: assistantCard } : {}),
                  },
                ],
              });
            } else if (event.type === 'script_card') {
              const card: ScriptCard = {
                action: event.action,
                script_id: event.script_id,
                name: event.name,
                rev_no: event.rev_no,
              };
              assistantCard = card;
              stashCard(liveKey, { ...card, ts: Date.now() });
              writeStreamState({
                messages: [
                  ...historyWithUser,
                  {
                    role: 'assistant',
                    content: assistantContent,
                    toolCalls: assistantToolCalls.length ? [...assistantToolCalls] : undefined,
                    card,
                  },
                ],
              });
            } else if (event.type === 'error') {
              const clean = sanitizeAiErrorMessage(event.message);
              assistantContent += assistantContent ? `\n\n⚠ ${clean}` : `⚠ ${clean}`;
              writeStreamState({
                messages: [
                  ...historyWithUser,
                  { role: 'assistant', content: assistantContent, isError: true },
                ],
                isStreaming: false,
                abortController: null,
              });
            } else if (event.type === 'done') {
              streamDone = true;
              writeStreamState({ isStreaming: false, toolsDone: true, abortController: null });
              void refetchSessions();
              break;
            }
          }
        }
      } catch (err: unknown) {
        if (firstByteGuard) clearTimeout(firstByteGuard);
        if ((err as Error)?.name === 'AbortError') {
          const reason = (err as Error)?.message ?? '';
          if (reason.includes('First-byte timeout')) {
            writeStreamState({
              messages: [
                ...historyWithUser,
                { role: 'assistant', content: 'Error: AI provider timed out waiting for the first response (100s). The provider did not answer — retry, or pick another route.', isError: true },
              ],
              isStreaming: false,
              abortController: null,
            });
            return;
          }
          writeStreamState({ isStreaming: false, toolsDone: true, abortController: null });
          return;
        }
        const msg = err instanceof Error ? err.message : 'Unknown error';
        writeStreamState({
          messages: [
            ...historyWithUser,
            { role: 'assistant', content: `Error: ${msg}`, isError: true },
          ],
          isStreaming: false,
          abortController: null,
        });
      } finally {
        if (firstByteGuard) clearTimeout(firstByteGuard);
        clearInterval(elapsedTimer);
        setStreamRouteLabel(null);
        ongoingAbortsRef.current.delete(abort);
        setSessionMap((prev) => {
          const next = new Map(prev);
          const s = next.get(liveKey);
          if (s?.isStreaming) {
            next.set(liveKey, { ...s, isStreaming: false, abortController: null });
          }
          return next;
        });
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    },
    [activeKey, sessionMap, defaultModel, symbol, exchange, patchSession, refetchSessions, activePersona, availableModels, catalogData, hasSentRef, setSessionMap, setActiveKey, inputRef],
  );

  const handleStop = useCallback(() => {
    currentSession.abortController?.abort();
  }, [currentSession]);

  const retryLastMessage = useCallback(() => {
    const state = sessionMap.get(activeKey) ?? emptySessionState(defaultModel);
    const lastUser = [...state.messages].reverse().find((m) => m.role === 'user');
    if (!lastUser) return;
    void sendMessage(lastUser.content, true);
  }, [activeKey, sessionMap, defaultModel, sendMessage]);

  return {
    currentSession,
    activePersona,
    setActivePersona,
    streamRouteLabel,
    streamElapsed,
    streamingKeys,
    sendMessage,
    handleStop,
    retryLastMessage,
    startNewChat,
    loadSession,
    deleteSession,
  };
}
