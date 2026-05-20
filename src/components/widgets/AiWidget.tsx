'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAtomValue } from 'jotai';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';
import { cn } from '@/lib/utils';

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: string[];
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
}

function MessageBubble({ msg, isLastAssistant, toolsDone }: MessageBubbleProps) {
  const isUser = msg.role === 'user';
  const toolCalls = msg.toolCalls ?? [];
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
          'rounded px-2 py-1.5 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-w-full',
          isUser
            ? 'bg-blue-900/40 text-blue-100 border border-blue-800/50'
            : 'bg-terminal-gray/30 text-terminal-amber border border-terminal-amber/10',
        )}
      >
        {msg.content || <span className="opacity-40 animate-pulse">▋</span>}
      </div>
      <span className="text-[10px] text-terminal-amber/30 px-1">
        {isUser ? 'you' : 'blm ai'}
      </span>
    </div>
  );
}

// ─── Session sidebar ──────────────────────────────────────────────────────────

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeSessionId: number | null;
  onSelectSession: (id: number) => void;
  onDeleteSession: (id: number) => void;
  onNewChat: () => void;
}

function SessionSidebar({
  sessions,
  activeSessionId,
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
      {/* Sidebar header */}
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

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="px-2 py-4 text-[10px] text-terminal-amber/25 text-center">
            No past chats
          </div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => onSelectSession(s.id)}
              className={cn(
                'group flex flex-col px-2 py-1.5 cursor-pointer border-b border-terminal-amber/5 hover:bg-terminal-amber/5 transition-colors',
                activeSessionId === s.id && 'bg-terminal-amber/8 border-l-2 border-l-terminal-amber/40',
              )}
            >
              <div className="flex items-start justify-between gap-1">
                <span
                  className={cn(
                    'text-[10px] font-mono leading-tight flex-1 truncate',
                    activeSessionId === s.id ? 'text-terminal-amber' : 'text-terminal-amber/60',
                  )}
                >
                  {s.title}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(s.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 text-red-400/60 hover:text-red-400 text-[9px] px-1 transition-all shrink-0"
                  title="Delete session"
                >
                  ✕
                </button>
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[9px] text-terminal-amber/30">{s.symbol}</span>
                <span className="text-[9px] text-terminal-amber/20">·</span>
                <span className="text-[9px] text-terminal-amber/30">{s.message_count} msgs</span>
                <span className="text-[9px] text-terminal-amber/20">·</span>
                <span className="text-[9px] text-terminal-amber/25">{fmt(s.updated_at)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ─── Main widget ──────────────────────────────────────────────────────────────

export function AiWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const exchange = useAtomValue(activeExchangeAtom);
  const queryClient = useQueryClient();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [toolsDone, setToolsDone] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // ── Data fetching ──────────────────────────────────────────────────────────

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

  // Set model to first backend option once loaded; never hardcode an ID here
  useEffect(() => {
    if (availableModels.length > 0 && !model) {
      setModel(availableModels[0].id);
    }
  }, [availableModels, model]);

  const { data: sessions = [], refetch: refetchSessions } = useQuery<SessionSummary[]>({
    queryKey: ['ai-chat-sessions'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/chat/sessions');
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: 30_000,
  });

  // ── Effects ────────────────────────────────────────────────────────────────

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // ── Handlers ───────────────────────────────────────────────────────────────

  const loadSession = useCallback(async (id: number) => {
    try {
      const res = await fetch(`/api/py/ai/chat/sessions/${id}`);
      if (!res.ok) {
        console.error(`Failed to load session ${id}: ${res.status}`);
        return;
      }
      const data: SessionDetail = await res.json();
      setActiveSessionId(id);
      setModel(data.model);
      setMessages(
        data.messages.map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          toolCalls: m.tool_calls ?? undefined,
        })),
      );
      setSidebarOpen(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    } catch (err) {
      console.error('loadSession error:', err);
    }
  }, []);

  const deleteSession = useCallback(
    async (id: number) => {
      const res = await fetch(`/api/py/ai/chat/sessions/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        console.error(`Failed to delete session ${id}: ${res.status}`);
        return;
      }
      if (activeSessionId === id) {
        setActiveSessionId(null);
        setMessages([]);
      }
      refetchSessions();
    },
    [activeSessionId, refetchSessions],
  );

  const startNewChat = useCallback(() => {
    if (isStreaming) abortRef.current?.abort();
    setMessages([]);
    setActiveSessionId(null);
    setInput('');
    setToolsDone(false);
    setSidebarOpen(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [isStreaming]);

  const sendMessage = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = { role: 'user', content: trimmed };
    const updatedHistory = [...messages, userMessage];

    setMessages(updatedHistory);
    setInput('');
    setIsStreaming(true);
    setToolsDone(false);

    let assistantContent = '';
    let assistantToolCalls: string[] = [];

    // Add streaming assistant placeholder
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      const res = await fetch('/api/py/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abort.signal,
        body: JSON.stringify({
          messages: updatedHistory.map((m) => ({ role: m.role, content: m.content })),
          symbol,
          exchange,
          model,
          session_id: activeSessionId,
        }),
      });

      if (!res.ok || !res.body) {
        const text = await res.text();
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: 'assistant',
            content: `Error: ${res.status} — ${text.slice(0, 200)}`,
          };
          return next;
        });
        setIsStreaming(false);
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
            setActiveSessionId(event.id);
          } else if (event.type === 'token') {
            assistantContent += event.text;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                role: 'assistant',
                content: assistantContent,
                toolCalls: assistantToolCalls.length ? [...assistantToolCalls] : undefined,
              };
              return next;
            });
          } else if (event.type === 'tool_call') {
            assistantToolCalls = [...assistantToolCalls, event.name];
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...next[next.length - 1],
                toolCalls: [...assistantToolCalls],
              };
              return next;
            });
          } else if (event.type === 'error') {
            assistantContent += assistantContent ? `\n\n⚠ ${event.message}` : `⚠ ${event.message}`;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: 'assistant', content: assistantContent };
              return next;
            });
          } else if (event.type === 'done') {
            setToolsDone(true);
            streamDone = true;
            // Refresh session list so sidebar stays current
            void queryClient.invalidateQueries({ queryKey: ['ai-chat-sessions'] });
            break;
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return;
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: 'assistant', content: `Error: ${msg}` };
        return next;
      });
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [input, isStreaming, messages, symbol, exchange, model, activeSessionId, queryClient]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setToolsDone(true);
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-full w-full flex overflow-hidden font-mono text-xs bg-terminal-bg">
      {/* Collapsible sidebar */}
      {sidebarOpen && (
        <div className="w-44 shrink-0 flex flex-col overflow-hidden">
          <SessionSidebar
            sessions={sessions}
            activeSessionId={activeSessionId}
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
          {/* History toggle */}
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
            value={model}
            onChange={(e) => setModel(e.target.value)}
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
              <option value="">Loading models...</option>
            )}
          </select>

          <span className="text-terminal-amber/30 text-[10px] truncate flex-1">
            ctx: {symbol}.{exchange}
          </span>

          <button
            onClick={startNewChat}
            className="text-[10px] text-terminal-amber/40 hover:text-terminal-amber/70 px-1.5 py-0.5 border border-terminal-amber/10 hover:border-terminal-amber/30 rounded transition-colors"
          >
            clear
          </button>
        </div>

        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-3 min-h-0">
          {messages.length === 0 && (
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
              />
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-terminal-amber/10 px-2 py-1.5 flex gap-2 items-end bg-terminal-gray/5">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder={
              isStreaming
                ? 'thinking…'
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
              onClick={sendMessage}
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
