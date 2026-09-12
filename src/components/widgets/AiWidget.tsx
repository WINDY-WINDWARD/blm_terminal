'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { unstable_batchedUpdates } from 'react-dom';
import { useAtomValue } from 'jotai';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';
import { cn } from '@/lib/utils';

// ─── Personas ─────────────────────────────────────────────────────────────────

const PERSONAS = [
  { id: 'value',    label: 'Value Analyst',    description: 'Graham/Buffett framework' },
  { id: 'earnings', label: 'Earnings Analyst',  description: 'QoQ/YoY earnings forensics' },
  { id: 'fno',      label: 'F&O Analyst',       description: 'Options strategy & derivatives' },
  { id: 'macro',    label: 'Macro Analyst',     description: 'Sector rotation & India macro' },
] as const;

type PersonaId = (typeof PERSONAS)[number]['id'];

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: string[];
  isError?: boolean;
}

interface ModelOption {
  id: string;
  label: string;
}

interface SessionSummary {
  id: number;
  title: string;
  model: string;
  symbol: string;
  exchange: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

interface SessionDetail {
  id: number;
  title: string;
  model: string;
  symbol: string;
  exchange: string;
  messages: Array<{
    id: number;
    role: string;
    content: string;
    tool_calls: string[] | null;
    created_at: string;
  }>;
}

type StreamEvent =
  | { type: 'session_id'; id: number }
  | { type: 'token'; text: string }
  | { type: 'tool_call'; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; name: string; preview: string }
  | { type: 'error'; message: string }
  | { type: 'done' };

// ─── Per-session state ────────────────────────────────────────────────────────

interface SessionState {
  messages: ChatMessage[];
  isStreaming: boolean;
  toolsDone: boolean;
  input: string;
  model: string;
  abortController: AbortController | null;
}

function emptySessionState(defaultModel = ''): SessionState {
  return {
    messages: [],
    isStreaming: false,
    toolsDone: false,
    input: '',
    model: defaultModel,
    abortController: null,
  };
}

// ─── Module-level persistence (survives unmount/remount) ───────────────────────

const _persistedMap = new Map<number | null, SessionState>();
let _persistedActiveKey: number | null = null;
let _persistedHasSent = false;

// ─── Sub-components ───────────────────────────────────────────────────────────

interface ToolCallBadgeProps {
  name: string;
  done: boolean;
}

function ToolCallBadge({ name, done }: ToolCallBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border',
        done
          ? 'border-terminal-amber/30 text-terminal-amber/50 bg-transparent'
          : 'border-blue-500/50 text-blue-400 bg-blue-900/20 animate-pulse',
      )}
    >
      <span className="opacity-70">{done ? '✓' : '→'}</span>
      {name}
    </span>
  );
}

interface MessageBubbleProps {
  msg: ChatMessage;
  isLastAssistant?: boolean;
  toolsDone?: boolean;
  onRetry?: () => void;
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-1.5 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="text-sm font-bold text-terminal-amber mt-2 mb-1 border-b border-terminal-amber/20 pb-0.5">{children}</h1>,
        h2: ({ children }) => <h2 className="text-xs font-bold text-terminal-amber mt-2 mb-1">{children}</h2>,
        h3: ({ children }) => <h3 className="text-xs font-semibold text-terminal-amber/80 mt-1.5 mb-0.5">{children}</h3>,
        code: ({ children, className }) => {
          const isBlock = className?.startsWith('language-');
          if (isBlock) {
            return (
              <code className="block bg-black/40 border border-terminal-amber/15 rounded px-2 py-1.5 text-[10px] text-terminal-amber/90 whitespace-pre overflow-x-auto my-1">
                {children}
              </code>
            );
          }
          return (
            <code className="bg-black/30 border border-terminal-amber/20 rounded px-1 py-0.5 text-[10px] text-terminal-amber/90">
              {children}
            </code>
          );
        },
        pre: ({ children }) => <pre className="my-1">{children}</pre>,
        ul: ({ children }) => <ul className="list-none pl-3 mb-1.5 space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside pl-1 mb-1.5 space-y-0.5">{children}</ol>,
        li: ({ children }) => (
          <li className="flex gap-1.5 leading-relaxed">
            <span className="text-terminal-amber/40 shrink-0">-</span>
            <span className="flex-1">{children}</span>
          </li>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-terminal-amber/30 pl-2 my-1 text-terminal-amber/70 italic">
            {children}
          </blockquote>
        ),
        strong: ({ children }) => <strong className="font-bold text-terminal-amber">{children}</strong>,
        em: ({ children }) => <em className="italic text-terminal-amber/80">{children}</em>,
        hr: () => <hr className="border-terminal-amber/15 my-2" />,
        table: ({ children }) => (
          <div className="overflow-x-auto my-1.5">
            <table className="text-[10px] border-collapse w-full">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="border-b border-terminal-amber/20">{children}</thead>,
        th: ({ children }) => (
          <th className="px-2 py-0.5 text-left font-semibold text-terminal-amber/80 border border-terminal-amber/10">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-2 py-0.5 border border-terminal-amber/10 text-terminal-amber/70">{children}</td>
        ),
        tr: ({ children }) => <tr className="even:bg-terminal-amber/3">{children}</tr>,
        a: ({ children, href }) => (
          <span className="text-blue-400/70 underline underline-offset-2 cursor-default" title={href ?? ''}>
            {children}
          </span>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function MessageBubble({ msg, isLastAssistant, toolsDone, onRetry }: MessageBubbleProps) {
  const isUser = msg.role === 'user';
  const toolCalls = msg.toolCalls ?? [];
  const hasError = !isUser && msg.isError;
  return (
    <div className={cn('flex flex-col gap-1', isUser ? 'items-end' : 'items-start')}>
      {!isUser && toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1 max-w-full px-1">
          {toolCalls.map((name, i) => (
            <ToolCallBadge key={i} name={name} done={isLastAssistant ? (toolsDone ?? false) : true} />
          ))}
        </div>
      )}
      <div
        className={cn(
          'rounded px-2 py-1.5 text-xs font-mono leading-relaxed break-words max-w-full',
          isUser
            ? 'bg-blue-900/40 text-blue-100 border border-blue-800/50 whitespace-pre-wrap'
            : hasError
              ? 'bg-red-900/20 text-red-300 border border-red-500/30'
              : 'bg-terminal-gray/30 text-terminal-amber border border-terminal-amber/10',
        )}
      >
        {isUser ? (
          msg.content || <span className="opacity-40 animate-pulse">▋</span>
        ) : msg.content ? (
          <MarkdownContent content={msg.content} />
        ) : (
          <span className="opacity-40 animate-pulse">▋</span>
        )}
      </div>
      <div className="flex items-center gap-2 px-1">
        <span className="text-[10px] text-terminal-amber/30">
          {isUser ? 'you' : 'blm ai'}
        </span>
        {hasError && isLastAssistant && onRetry && (
          <button
            onClick={onRetry}
            className="text-[10px] text-terminal-amber/50 hover:text-terminal-amber underline underline-offset-2"
            title="Resend last message"
          >
            retry
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Session sidebar ──────────────────────────────────────────────────────────

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeKey: number | null;
  streamingKeys: Set<number | null>;
  onSelectSession: (id: number) => void;
  onDeleteSession: (id: number) => void;
  onNewChat: () => void;
}

function SessionSidebar({
  sessions,
  activeKey,
  streamingKeys,
  onSelectSession,
  onDeleteSession,
  onNewChat,
}: SessionSidebarProps) {
  const fmt = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
  };

  return (
    <div className="flex flex-col h-full w-full border-r border-terminal-amber/10 bg-terminal-bg">
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-terminal-amber/10 shrink-0">
        <span className="text-[10px] text-terminal-amber/50 font-mono uppercase tracking-wider">
          History
        </span>
        <button
          onClick={onNewChat}
          className="text-[10px] font-mono text-terminal-amber/50 hover:text-terminal-amber px-1.5 py-0.5 border border-terminal-amber/15 hover:border-terminal-amber/40 rounded transition-colors"
          title="New chat"
        >
          + new
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="px-2 py-4 text-[10px] text-terminal-amber/25 text-center">
            No past chats
          </div>
        ) : (
          sessions.map((s) => {
            const isActive = activeKey === s.id;
            const isStreaming = streamingKeys.has(s.id);
            return (
              <div
                key={s.id}
                onClick={() => onSelectSession(s.id)}
                className={cn(
                  'group flex flex-col px-2 py-1.5 cursor-pointer border-b border-terminal-amber/5 hover:bg-terminal-amber/5 transition-colors',
                  isActive && 'bg-terminal-amber/8 border-l-2 border-l-terminal-amber/40',
                )}
              >
                <div className="flex items-start justify-between gap-1">
                  <span
                    className={cn(
                      'text-[10px] font-mono leading-tight flex-1 truncate',
                      isActive ? 'text-terminal-amber' : 'text-terminal-amber/60',
                    )}
                  >
                    {s.title}
                  </span>
                  <div className="flex items-center gap-1 shrink-0">
                    {isStreaming && (
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" title="Streaming…" />
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(s.id);
                      }}
                      className="opacity-0 group-hover:opacity-100 text-red-400/60 hover:text-red-400 text-[9px] px-1 transition-[opacity,color]"
                      title="Delete session"
                    >
                      ✕
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[9px] text-terminal-amber/30">{s.symbol}</span>
                  <span className="text-[9px] text-terminal-amber/20">·</span>
                  <span className="text-[9px] text-terminal-amber/30">{s.message_count} msgs</span>
                  <span className="text-[9px] text-terminal-amber/20">·</span>
                  <span className="text-[9px] text-terminal-amber/25">{fmt(s.updated_at)}</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ─── Main widget ──────────────────────────────────────────────────────────────

// Sentinel key for an unsent "new chat" scratch session
const NEW_CHAT_KEY = null;

export function AiWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const exchange = useAtomValue(activeExchangeAtom);
  const queryClient = useQueryClient();

  const [showDisclaimer, setShowDisclaimer] = useState(true);
  const [aiAuthStatus, setAiAuthStatus] = useState<{provider: string, is_configured: boolean} | null>(null);

  useEffect(() => {
    fetch('/api/py/ai/status')
      .then(r => r.json())
      .then(d => setAiAuthStatus(d))
      .catch(console.error);
      
    // Poll it occasionally
    const intv = setInterval(() => {
      fetch('/api/py/ai/status')
        .then(r => r.json())
        .then(d => setAiAuthStatus(d))
        .catch(console.error);
    }, 10000);
    return () => clearInterval(intv);
  }, []);


  useEffect(() => {
    const timer = setTimeout(() => setShowDisclaimer(false), 4000);
    return () => clearTimeout(timer);
  }, []);

  // ── Models ─────────────────────────────────────────────────────────────────

  const { data: modelsData } = useQuery<ModelOption[]>({
    queryKey: ['ai-chat-models'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/chat/models');
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: Infinity,
  });
  const availableModels: ModelOption[] = modelsData ?? [];
  const defaultModel = availableModels[0]?.id ?? '';

  // ── Session map — the core of the isolation model ─────────────────────────
  // Keys: real session IDs (number) OR null for the unsent scratch chat.
  // Each session owns its own messages, streaming state, input, and abort handle.
  // Switching activeKey is a pure view operation — no other key is ever touched.

  const [sessionMap, setSessionMap] = useState<Map<number | null, SessionState>>(
    () => {
      if (_persistedMap.size > 0) {
        // Restore from module-level store but mark as not streaming
        // (the underlying connection is dead after unmount)
        const restored = new Map<number | null, SessionState>();
        for (const [k, v] of _persistedMap) {
          restored.set(k, { ...v, isStreaming: false, abortController: null });
        }
        return restored;
      }
      return new Map([[NEW_CHAT_KEY, emptySessionState()]]);
    },
  );
  const [activeKey, setActiveKey] = useState<number | null>(() => {
    if (_persistedMap.size > 0) return _persistedActiveKey;
    return NEW_CHAT_KEY;
  });
  const hasSentRef = useRef(_persistedHasSent);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activePersona, setActivePersona] = useState<PersonaId | null>(null);

  // Derive current session's state for rendering — always safe to destructure
  const current = sessionMap.get(activeKey) ?? emptySessionState(defaultModel);
  const { messages, isStreaming, toolsDone, input, model } = current;

  // Once models load, back-fill the default model into any session that has ''
  useEffect(() => {
    if (!defaultModel) return;
    setSessionMap((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const [key, state] of next) {
        if (!state.model) {
          next.set(key, { ...state, model: defaultModel });
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [defaultModel]);

  // ── Sync to module-level store — survives unmount/remount ──────────────────

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

  // Abort all in-flight streams on unmount by tracking them in a ref
  const ongoingAbortsRef = useRef<Set<AbortController>>(new Set());
  useEffect(() => {
    return () => {
      for (const ctrl of ongoingAbortsRef.current) {
        ctrl.abort();
      }
    };
  }, []);

  // ── Helpers ────────────────────────────────────────────────────────────────

  /** Immutably patch one session's state without touching any other key. */
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

  // ── Sessions list (sidebar) ────────────────────────────────────────────────

  const { data: sessions = [], refetch: refetchSessions } = useQuery<SessionSummary[]>({
    queryKey: ['ai-chat-sessions'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/chat/sessions');
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: 0,       // always re-fetch when invalidated
    refetchOnMount: true,
  });

  // ── DOM refs ───────────────────────────────────────────────────────────────

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [activeKey]);

  // ── Streaming keys (for sidebar pulse dots) ────────────────────────────────

  const streamingKeys = new Set<number | null>(
    [...sessionMap.entries()].filter(([, s]) => s.isStreaming).map(([k]) => k),
  );

  // ── Handlers ───────────────────────────────────────────────────────────────

  /** Switch to a past session. Fetches from backend unless the session is currently streaming. */
  const loadSession = useCallback(
    async (id: number) => {
      setActiveKey(id);
      setSidebarOpen(false);
      setActivePersona(null);
      setTimeout(() => inputRef.current?.focus(), 50);

      // Never clobber a live stream — the in-memory state IS the truth while streaming
      if (sessionMap.get(id)?.isStreaming) return;

      try {
        const res = await fetch(`/api/py/ai/chat/sessions/${id}`);
        if (!res.ok) {
          console.error(`Failed to load session ${id}: ${res.status}`);
          return;
        }
        const data: SessionDetail = await res.json();
        // Always apply DB state so completed replies are reflected after re-visiting
        patchSession(id, {
          model: data.model,
          messages: data.messages.map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            toolCalls: m.tool_calls ?? undefined,
          })),
        });
      } catch (err) {
        console.error('loadSession error:', err);
      }
    },
    [sessionMap, patchSession],
  );

  /** Delete a session both from backend and from the local map. */
  const deleteSession = useCallback(
    async (id: number) => {
      // Abort any in-flight stream for this session before deleting
      sessionMap.get(id)?.abortController?.abort();

      const res = await fetch(`/api/py/ai/chat/sessions/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        console.error(`Failed to delete session ${id}: ${res.status}`);
        return;
      }
      setSessionMap((prev) => {
        const next = new Map(prev);
        next.delete(id);
        return next;
      });
      if (activeKey === id) setActiveKey(NEW_CHAT_KEY);
      void refetchSessions();
    },
    [sessionMap, activeKey, refetchSessions],
  );

  /** Create a fresh scratch session and switch to it. Does not abort others. */
  const startNewChat = useCallback(() => {
    // Reset the scratch slot and switch to it
    setSessionMap((prev) => {
      const next = new Map(prev);
      next.set(NEW_CHAT_KEY, emptySessionState(defaultModel));
      return next;
    });
    setActiveKey(NEW_CHAT_KEY);
    setSidebarOpen(false);
    setActivePersona(null);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [defaultModel]);

  /** Send a message. Fully scoped to sessionKey — safe to switch sessions during streaming. */
  const sendMessage = useCallback(async (forcedInput?: string, replaceLastAssistant?: boolean) => {
    // Capture session key and current state AT CALL TIME — these become
    // immutable locals so the stream closure never reads stale React state.
    const sessionKey = activeKey;
    const sessionState = sessionMap.get(sessionKey) ?? emptySessionState(defaultModel);
    const trimmed = (forcedInput ?? sessionState.input).trim();

    if (!trimmed || sessionState.isStreaming) return;

    const userMessage: ChatMessage = { role: 'user', content: trimmed };
    // If retrying after an error, strip the last assistant message so we don't duplicate
    const priorMessages = replaceLastAssistant
      ? sessionState.messages.filter(
          (_, i, arr) => !(arr[i].role === 'assistant' && i === arr.length - 1)
        )
      : sessionState.messages;
    const historyWithUser = [...priorMessages, userMessage];

    const abort = new AbortController();
    ongoingAbortsRef.current.add(abort);

    hasSentRef.current = true;

    // Build the optimistic state for the session — will be committed via patchSession
    // and also kept as a closure fallback for the session_id migration below.
    const optimisticMessages = [...historyWithUser, { role: 'assistant' as const, content: '' }];
    patchSession(sessionKey, {
      messages: optimisticMessages,
      input: '',
      isStreaming: true,
      toolsDone: false,
      abortController: abort,
    });

    // After a session_id event the server assigns a real ID; we migrate the
    // map entry from null → realId. This ref tracks the live key for writes
    // that happen after the migration.
    let liveKey: number | null = sessionKey;
    // Closure-level fallback for the migration — set synchronously so that even
    // if React hasn't committed patchSession yet, the migration can find its state.
    const migrationFallback: SessionState = {
      messages: optimisticMessages,
      input: '',
      isStreaming: true,
      toolsDone: false,
      model: sessionState.model || defaultModel,
      abortController: abort,
    };

    // Accumulated content for the current streaming turn
    let assistantContent = '';
    let assistantToolCalls: string[] = [];

    /** Write streaming progress to whichever key this stream owns. */
    const writeStreamState = (patch: Partial<SessionState>) => {
      setSessionMap((prev) => {
        const next = new Map(prev);
        const existing = next.get(liveKey) ?? emptySessionState(defaultModel);
        next.set(liveKey, { ...existing, ...patch });
        return next;
      });
    };

      try {
        const res = await fetch('/api/py/ai/chat', {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
          },
          signal: abort.signal,
          body: JSON.stringify({
            messages: historyWithUser.map((m) => ({ role: m.role, content: m.content })),
          symbol: symbol.toUpperCase(),
          exchange: exchange.toUpperCase(),
          model: sessionState.model || defaultModel,
          session_id: sessionKey, // null for new chats — backend creates the session
          persona: activePersona,
        }),
      });

      if (!res.ok || !res.body) {
        const text = await res.text();
        // Proxy now returns JSON { error: string } for non-OK responses
        let displayError = text.slice(0, 200);
        try {
          const parsed = JSON.parse(text) as { error?: string };
          if (parsed.error) displayError = parsed.error.slice(0, 200);
        } catch {
          /* not JSON — use raw text */
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
          try {
            event = JSON.parse(raw) as StreamEvent;
          } catch {
            continue;
          }

          if (event.type === 'session_id') {
            // Migrate the map entry from null/old-key → assigned real session ID
            const assignedId = event.id;
            if (liveKey !== assignedId) {
              unstable_batchedUpdates(() => {
                setSessionMap((prev) => {
                  const next = new Map(prev);
                  const fromNext = next.get(liveKey);
                  const existing = (fromNext && fromNext.messages.length > 0)
                    ? fromNext
                    : migrationFallback;
                  next.delete(liveKey);
                  next.set(assignedId, existing);
                  return next;
                });
                setActiveKey((prev) => (prev === sessionKey ? assignedId : prev));
              });
              liveKey = assignedId;
              // Immediately refresh sidebar so the new session appears
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
                },
              ],
            });
          } else if (event.type === 'error') {
            assistantContent += assistantContent
              ? `\n\n⚠ ${event.message}`
              : `⚠ ${event.message}`;
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
            // Force-refetch so sidebar message count and updated_at reflect the new reply
            void refetchSessions();
            break;
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') {
        // User stopped the stream — mark as done, keep whatever content arrived
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
      ongoingAbortsRef.current.delete(abort);
      // Ensure isStreaming is always cleared even on unexpected throws
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
  }, [activeKey, sessionMap, defaultModel, symbol, exchange, patchSession, refetchSessions]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const handleStop = useCallback(() => {
    current.abortController?.abort();
    // isStreaming/abortController cleared in the AbortError catch path of sendMessage
  }, [current]);

  /** Retry the last user message (useful after an error response). */
  const retryLastMessage = useCallback(() => {
    const state = sessionMap.get(activeKey) ?? emptySessionState(defaultModel);
    const lastUser = [...state.messages].reverse().find((m) => m.role === 'user');
    if (!lastUser) return;
    void sendMessage(lastUser.content, true);
  }, [activeKey, sessionMap, defaultModel, sendMessage]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-full w-full flex overflow-hidden font-mono text-xs bg-terminal-bg relative">
      {showDisclaimer && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-terminal-amber/50 bg-black p-4 text-center text-terminal-amber animate-pulse max-w-sm shadow-xl">
            <div className="font-bold mb-2 uppercase text-sm">⚠️ Disclaimer</div>
            <div className="text-[10px] leading-relaxed">
              AI can make mistakes and the user takes all responsibility for any actions taken using the AI's advice/recommendations.
            </div>
          </div>
        </div>
      )}

      {/* Provider Configuration Banner */}
      {aiAuthStatus && !aiAuthStatus.is_configured && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-terminal-red/50 bg-black p-6 text-center text-terminal-red shadow-xl max-w-sm flex flex-col items-center gap-3">
            <div className="font-bold uppercase text-lg">⚠️ Configuration Required</div>
            <div className="text-xs text-white/70 leading-relaxed font-mono">
              The AI Provider ({aiAuthStatus.provider}) is not fully configured.
              Please complete the setup in the <span className="text-terminal-amber font-bold">Settings widget</span>.
            </div>
            <div className="text-[10px] text-terminal-red/50 mt-2">
              (This widget is locked until a valid provider is set)
            </div>
          </div>
        </div>
      )}

      {/* Collapsible sidebar */}
      {sidebarOpen && (
        <div className="w-44 shrink-0 flex flex-col overflow-hidden">
          <SessionSidebar
            sessions={sessions}
            activeKey={activeKey}
            streamingKeys={streamingKeys}
            onSelectSession={loadSession}
            onDeleteSession={deleteSession}
            onNewChat={startNewChat}
          />
        </div>
      )}

      {/* Main chat area */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Header */}
        <div className="flex items-center gap-2 px-2 py-1 border-b border-terminal-amber/10 bg-terminal-gray/10 shrink-0">
          <button
            onClick={() => setSidebarOpen((o) => !o)}
            className={cn(
              'text-[10px] font-mono px-1.5 py-0.5 border rounded transition-colors',
              sidebarOpen
                ? 'border-terminal-amber/40 text-terminal-amber/80'
                : 'border-terminal-amber/15 text-terminal-amber/40 hover:border-terminal-amber/35 hover:text-terminal-amber/60',
            )}
            title="Toggle chat history"
          >
            ☰
          </button>

          <select
            value={model || defaultModel}
            onChange={(e) => patchSession(activeKey, { model: e.target.value })}
            disabled={isStreaming}
            className="bg-terminal-bg border border-terminal-amber/20 text-terminal-amber/70 text-[10px] font-mono px-1 py-0.5 rounded outline-none focus:border-terminal-amber/50 disabled:opacity-50 max-w-[160px]"
          >
            {availableModels.length > 0 ? (
              availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))
            ) : (
              <option value="">Loading models…</option>
            )}
          </select>

          <span className="text-terminal-amber/30 text-[10px] truncate flex-1">
            ctx: {symbol}.{exchange}
          </span>

          {/* Streaming indicator in header when viewing a streaming session */}
          {isStreaming && (
            <span className="text-[10px] text-blue-400/70 animate-pulse shrink-0">thinking…</span>
          )}

          <button
            onClick={startNewChat}
            className="text-[10px] text-terminal-amber/40 hover:text-terminal-amber/70 px-1.5 py-0.5 border border-terminal-amber/10 hover:border-terminal-amber/30 rounded transition-colors shrink-0"
          >
            + new
          </button>
        </div>

        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-3 min-h-0">
          {!hasSentRef.current && messages.length === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center gap-2 text-terminal-amber/25 text-[11px]">
              <span className="text-2xl opacity-20">◈</span>
              <span>BLM AI — ask anything about NSE markets</span>
              <span className="text-[10px] opacity-60">
                Has access to live prices, fundamentals, news, deals, alerts &amp; more
              </span>
            </div>
          )}
          {messages.map((msg, i) => {
            const isLastAssistant = msg.role === 'assistant' && i === messages.length - 1;
            return (
              <MessageBubble
                key={i}
                msg={msg}
                isLastAssistant={isLastAssistant}
                toolsDone={isLastAssistant ? toolsDone : undefined}
                onRetry={isLastAssistant ? retryLastMessage : undefined}
              />
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* Persona selector */}
        <div className="flex gap-1 px-2 py-1.5 border-t border-white/5 flex-wrap">
          {PERSONAS.map((p) => (
            <button
              key={p.id}
              title={p.description}
              onClick={() => setActivePersona((prev) => (prev === p.id ? null : p.id))}
              className={cn(
                'px-2 py-0.5 rounded text-[10px] font-medium border transition-colors',
                activePersona === p.id
                  ? 'bg-blue-500/20 border-blue-400/50 text-blue-300'
                  : 'bg-white/5 border-white/10 text-white/40 hover:text-white/70 hover:border-white/20'
              )}
            >
              {p.label}
            </button>
          ))}
          {activePersona && (
            <span className="ml-auto text-[10px] text-blue-400/70 self-center pr-1">
              {PERSONAS.find((p) => p.id === activePersona)?.description}
            </span>
          )}
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-terminal-amber/10 px-2 py-1.5 flex gap-2 items-end bg-terminal-gray/5">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => patchSession(activeKey, { input: e.target.value })}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder={
              isStreaming
                ? 'AI is thinking — you can switch to another chat while waiting…'
                : 'Ask about NSE markets… (Enter to send, Shift+Enter for newline)'
            }
            rows={1}
            className={cn(
              'flex-1 resize-none bg-terminal-bg border border-terminal-amber/20 text-terminal-amber text-xs font-mono px-2 py-1.5 rounded outline-none',
              'placeholder:text-terminal-amber/25',
              'focus:border-terminal-amber/50',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'leading-relaxed min-h-[32px] max-h-[80px] overflow-y-auto',
            )}
            style={{ fieldSizing: 'content' } as React.CSSProperties}
          />
          {isStreaming ? (
            <button
              onClick={handleStop}
              className="shrink-0 px-2 py-1.5 text-[10px] font-mono border border-red-500/40 text-red-400 hover:bg-red-900/20 rounded transition-colors"
            >
              stop
            </button>
          ) : (
            <button
              onClick={() => void sendMessage()}
              disabled={!input.trim()}
              className={cn(
                'shrink-0 px-2 py-1.5 text-[10px] font-mono border rounded transition-colors',
                input.trim()
                  ? 'border-terminal-amber/40 text-terminal-amber hover:bg-terminal-amber/10'
                  : 'border-terminal-amber/10 text-terminal-amber/20 cursor-not-allowed',
              )}
            >
              send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
