'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { unstable_batchedUpdates } from 'react-dom';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  activeExchangeAtom,
  activePanelsAtom,
  activeSymbolAtom,
  aiPrefillAtom,
  focusedPanelAtom,
  scriptChartHandoffAtom,
  AI_REFINE_REQUEST_KEY,
} from '@/store/terminalStore';
import { resolveChartPanel } from '@/lib/scripts/handoff';
import {
  getStashedCards,
  migrateStash,
  pruneStashedSession,
  reattachStashedCards,
  stampStashedCard,
  stashCard,
} from '@/lib/scripts/cardStash';
import { cn } from '@/lib/utils';
import { computePopoverPos } from '@/lib/scripts/popoverPos';

/**
 * Defense-in-depth: no backend path should ever leak a raw JSON blob into
 * the chat. If a provider error arrives looking like serialized JSON,
 * substitute a generic line (full detail stays in the backend log).
 */
export function sanitizeAiErrorMessage(message: string): string {
  const t = message.trim();
  // Catches both bare blobs (`{ "error": ... }`) and prefixed ones
  // (`Antigravity API 429: { "error": ... }`). Friendly messages never
  // contain a serialized `"error"` object.
  if (/\{\s*"error"/.test(t)) {
    return 'The AI provider returned an unreadable error — please retry, or check the backend log for details.';
  }
  return message;
}

/**
 * Sliding mode-switch contract: a single track tinted with the active hue,
 * one solid knob carrying the active label — amber = Research, emerald =
 * Script. Exported for tests so the switch can never silently regress to
 * two dim buttons again.
 */
export function modeTrackClass(sessionMode: AiMode): string {
  return sessionMode === 'script'
    ? 'bg-emerald-400/15 border-emerald-400/50'
    : 'bg-terminal-amber/15 border-terminal-amber/40';
}

export function modeKnobClass(sessionMode: AiMode): string {
  return sessionMode === 'script'
    ? 'left-[calc(50%+1px)] bg-emerald-400 text-black font-bold'
    : 'left-[2px] bg-terminal-amber text-black font-bold';
}

/** Short label for the model pill — strips any "[Provider]" prefix. */
export function shortModelLabel(label: string): string {
  return label.replace(/^\[[^\]]+\]\s*/, '');
}

// ─── Personas ─────────────────────────────────────────────────────────────────

const PERSONAS = [
  { id: 'value',    label: 'Value Analyst',    description: 'Graham/Buffett framework' },
  { id: 'earnings', label: 'Earnings Analyst',  description: 'QoQ/YoY earnings forensics' },
  { id: 'fno',      label: 'F&O Analyst',       description: 'Options strategy & derivatives' },
  { id: 'macro',    label: 'Macro Analyst',     description: 'Sector rotation & India macro' },
] as const;

type PersonaId = (typeof PERSONAS)[number]['id'];

// ─── Types ────────────────────────────────────────────────────────────────────

/** AI chat mode — per session. Script mode adds the Script Lab system prompt. */
type AiMode = 'research' | 'script';

/** Script Lab mutation card — emitted by the backend as an extra SSE event
 *  right after the tool_result of create_script / revise_script. The card is
 *  the sole path to the chart: Accept writes the handoff atom. */
interface ScriptCard {
  action: 'created' | 'revised';
  script_id: number;
  name: string;
  rev_no: number;
  accepted?: boolean;
  dismissed?: boolean;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: string[];
  isError?: boolean;
  card?: ScriptCard;
}

interface ModelOption {
  id: string;
  label: string;
  is_free?: boolean;
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
  | { type: 'script_card'; action: 'created' | 'revised'; script_id: number; name: string; rev_no: number }
  | { type: 'error'; message: string }
  | { type: 'done' };

// ─── Per-session state ────────────────────────────────────────────────────────

interface SessionState {
  messages: ChatMessage[];
  isStreaming: boolean;
  toolsDone: boolean;
  input: string;
  model: string;
  mode: AiMode;
  abortController: AbortController | null;
}

function emptySessionState(defaultModel = '', mode: AiMode = 'research'): SessionState {
  return {
    messages: [],
    isStreaming: false,
    toolsDone: false,
    input: '',
    model: defaultModel,
    mode,
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

interface ScriptCardViewProps {
  card: ScriptCard;
  onAccept: (card: ScriptCard) => void;
  onDiscard: (card: ScriptCard) => void;
}

/** Script Lab mutation card — Accept is the sole path onto the chart. */
function ScriptCardView({ card, onAccept, onDiscard }: ScriptCardViewProps) {
  return (
    <div className="mt-1 rounded border border-terminal-amber/30 bg-black/40 px-2 py-1.5 max-w-full">
      <div className="flex items-center gap-1.5">
        <span className="text-terminal-amber font-bold">Σ</span>
        <span className="text-terminal-amber truncate flex-1" title={card.name}>
          {card.name}
        </span>
        <span className="text-[10px] text-terminal-amber/50 shrink-0">
          {card.action === 'created' ? 'created' : `revised · rev ${card.rev_no}`}
        </span>
      </div>
      <div className="flex items-center gap-1.5 mt-1">
        {card.accepted ? (
          <span className="text-[10px] text-green-400/80">✓ on chart — tune params in the Σ menu</span>
        ) : (
          <>
            <button
              onClick={() => onAccept(card)}
              className="text-[10px] font-mono px-1.5 py-0.5 border border-terminal-amber/40 text-terminal-amber hover:bg-terminal-amber/10 rounded transition-colors"
              title="Enable this script revision on the chart"
            >
              Accept → chart
            </button>
            <button
              onClick={() => onDiscard(card)}
              className="text-[10px] font-mono px-1.5 py-0.5 border border-white/10 text-white/40 hover:text-white/70 hover:border-white/25 rounded transition-colors"
              title="Dismiss this card (script stays saved)"
            >
              Discard
            </button>
          </>
        )}
      </div>
    </div>
  );
}

interface MessageBubbleProps {
  msg: ChatMessage;
  isLastAssistant?: boolean;
  toolsDone?: boolean;
  onRetry?: () => void;
  onAcceptCard?: (card: ScriptCard) => void;
  onDiscardCard?: (card: ScriptCard) => void;
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

function MessageBubble({ msg, isLastAssistant, toolsDone, onRetry, onAcceptCard, onDiscardCard }: MessageBubbleProps) {
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
        {!isUser && msg.card && !msg.card.dismissed && onAcceptCard && onDiscardCard && (
          <ScriptCardView card={msg.card} onAccept={onAcceptCard} onDiscard={onDiscardCard} />
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
          onClick={() => onNewChat()}
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

  // Model-picker groups for the input-area pill — same grouping the old
  // header <select> used: Free/Paid when is_free is known, otherwise split
  // "[Provider]" label prefixes into sections.
  const modelGroups = React.useMemo(() => {
    if (availableModels.some((m) => m.is_free !== undefined)) {
      return [
        { label: 'Free Models', items: availableModels.filter((m) => m.is_free) },
        { label: 'Paid Models', items: availableModels.filter((m) => !m.is_free) },
      ].filter((g) => g.items.length > 0);
    }
    const groups = new Map<string, ModelOption[]>();
    const ungrouped: ModelOption[] = [];
    for (const m of availableModels) {
      const match = /^\[([^\]]+)\]\s*/.exec(m.label);
      if (match) {
        const g = groups.get(match[1]) ?? [];
        g.push(m);
        groups.set(match[1], g);
      } else {
        ungrouped.push(m);
      }
    }
    const out = [...groups.entries()].map(([label, items]) => ({ label, items }));
    if (ungrouped.length > 0) out.push({ label: '', items: ungrouped });
    return out;
  }, [availableModels]);

  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [modelMenuPos, setModelMenuPos] = useState({ top: 0, left: 0 });
  const modelPillRef = useRef<HTMLButtonElement>(null);

  const openModelMenu = useCallback(() => {
    const r = modelPillRef.current?.getBoundingClientRect();
    if (r) {
      // Anchored at the input pill (bottom of widget): no room below, so
      // the shared anchor math flips it into a drop-up automatically.
      const pos = computePopoverPos(
        r,
        { width: window.innerWidth, height: window.innerHeight },
        220,
        280,
      );
      setModelMenuPos({ top: pos.top, left: pos.left });
    }
    setModelMenuOpen(true);
  }, []);

  // Dismiss the model menu on outside pointer-down or Esc.
  useEffect(() => {
    if (!modelMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest?.('[data-model-menu]') || t?.closest?.('[data-testid="ai-model-pill"]')) return;
      setModelMenuOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setModelMenuOpen(false);
    };
    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [modelMenuOpen]);

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
  const { messages, isStreaming, toolsDone, input, model, mode: sessionMode = 'research' } = current;

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
        // Always apply DB state so completed replies are reflected after re-visiting.
        // Cards themselves are in-session only, but a session whose turns called
        // script tools reopens in Script mode so the workflow continues.
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
          messages: reattachStashedCards(
            data.messages.map((m) => ({
              role: m.role as 'user' | 'assistant',
              content: m.content,
              toolCalls: m.tool_calls ?? undefined,
            })),
            getStashedCards(id),
          ),
          ...(hasScriptActivity ? { mode: 'script' as const } : {}),
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
      pruneStashedSession(id);
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
  const startNewChat = useCallback((mode: AiMode = 'research') => {
    // Reset the scratch slot and switch to it
    setSessionMap((prev) => {
      const next = new Map(prev);
      next.set(NEW_CHAT_KEY, emptySessionState(defaultModel, mode));
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
      mode: sessionState.mode ?? 'research',
      abortController: abort,
    };

    // Accumulated content for the current streaming turn. assistantCard
    // survives across token/tool_call rebuilds of the in-flight turn — every
    // rebuild must carry it or the card vanishes mid-stream.
    let assistantContent = '';
    let assistantToolCalls: string[] = [];
    let assistantCard: ScriptCard | undefined;

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
          mode: sessionState.mode ?? 'research',
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
              const fromKey = liveKey;
              migrateStash(fromKey, assignedId);
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
            // Script Lab mutation card — attach to the in-flight assistant turn
            // and stash for reload survival (cards are SSE-only; the DB keeps
            // tool names, never the card itself).
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
            assistantContent += assistantContent
              ? `\n\n⚠ ${clean}`
              : `⚠ ${clean}`;
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

  // ── Script Lab: card accept/discard + refine prefill ─────────────────────

  const panels = useAtomValue(activePanelsAtom);
  const focusedPanel = useAtomValue(focusedPanelAtom);
  const setFocusedPanel = useSetAtom(focusedPanelAtom);
  const setChartHandoff = useSetAtom(scriptChartHandoffAtom);
  const [prefill, setPrefill] = useAtom(aiPrefillAtom);

  /** Stamp one card (matched by script+rev) with a patch, scoped to a session key. */
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
    [],
  );

  /**
   * Accept is the sole path from a card onto the chart: enable the script on
   * the focused CHART panel (else the first CHART panel found) and focus it
   * so the user sees the overlay land. The ChartWidget handoff consumer does
   * the actual slot enable.
   */
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

  // Same-window refine path: the chart Scripts menu sets aiPrefillAtom.
  // Consume into the active session (switching it to Script mode) and focus input.
  const consumedPrefillRef = useRef(0);
  useEffect(() => {
    if (!prefill || prefill.ts <= consumedPrefillRef.current) return;
    consumedPrefillRef.current = prefill.ts;
    patchSession(activeKey, { input: prefill.text, mode: 'script' });
    setPrefill(null);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [prefill, activeKey, patchSession, setPrefill]);

  // Popout refine path: the menu wrote localStorage then opened /widget/AI.
  // This window is fresh, so the scratch session is the safe consume target.
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
      /* corrupt bridge payload — ignore */
    }
    // Mount-only: the bridge key is consumed once by whoever mounts first.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

          <span className="text-terminal-amber/30 text-[10px] truncate flex-1">
            ctx: {symbol}.{exchange}
          </span>

          {/* Sliding Research | Script switch — per session, sent with every
              chat POST. Single track tinted with the active hue, one solid
              knob carrying the active label: amber = Research, emerald = Script. */}
          <button
            role="switch"
            aria-checked={sessionMode === 'script'}
            data-testid="ai-mode-toggle"
            data-mode={sessionMode}
            onClick={() => patchSession(activeKey, { mode: sessionMode === 'script' ? 'research' : 'script' })}
            disabled={isStreaming}
            title="Research answers questions; Script writes versioned chart scripts (Script Lab)"
            className={cn(
              'relative w-[112px] h-[22px] rounded-full border transition-colors shrink-0 disabled:opacity-50',
              modeTrackClass(sessionMode),
            )}
          >
            <span className="absolute inset-0 flex items-center justify-between px-2 text-[9px] font-mono text-terminal-amber/40 pointer-events-none">
              <span>Research</span>
              <span>Σ</span>
            </span>
            <span
              className={cn(
                'absolute top-[2px] bottom-[2px] w-[calc(50%-3px)] rounded-full text-[10px] font-mono flex items-center justify-center transition-all',
                modeKnobClass(sessionMode),
              )}
            >
              {sessionMode === 'script' ? 'Σ Script' : 'Research'}
            </span>
          </button>

          {/* Streaming indicator in header when viewing a streaming session */}
          {isStreaming && (
            <span className="text-[10px] text-blue-400/70 animate-pulse shrink-0">thinking…</span>
          )}

          <button
            onClick={() => startNewChat(sessionMode)}
            className="text-[10px] text-terminal-amber/40 hover:text-terminal-amber/70 px-1.5 py-0.5 border border-terminal-amber/10 hover:border-terminal-amber/30 rounded transition-colors shrink-0"
          >
            + new
          </button>
        </div>

        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-3 min-h-0">
          {!hasSentRef.current && messages.length === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center gap-2 text-terminal-amber/25 text-[11px]">
              <span className="text-2xl opacity-20">{sessionMode === 'script' ? 'Σ' : '◈'}</span>
              <span>
                {sessionMode === 'script'
                  ? 'Script Lab — describe a chart overlay'
                  : 'BLM AI — ask anything about NSE markets'}
              </span>
              <span className="text-[10px] opacity-60">
                {sessionMode === 'script'
                  ? 'AI writes, validates & saves versioned scripts — accept the card to put it on the chart'
                  : 'Has access to live prices, fundamentals, news, deals, alerts & more'}
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
                onAcceptCard={acceptCard}
                onDiscardCard={discardCard}
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
          {/* Model pill — shows the session's model; click to switch. The
              header sliding switch owns the Research/Script mode now. */}
          <button
            ref={modelPillRef}
            data-testid="ai-model-pill"
            title={`Model: ${availableModels.find((m) => m.id === (model || defaultModel))?.label ?? 'loading…'} — click to switch`}
            onClick={() => (modelMenuOpen ? setModelMenuOpen(false) : openModelMenu())}
            disabled={isStreaming || availableModels.length === 0}
            className="shrink-0 self-center max-w-[110px] truncate px-1.5 py-0.5 text-[10px] font-mono font-bold rounded bg-terminal-amber/15 border border-terminal-amber/40 text-terminal-amber hover:bg-terminal-amber/25 transition-colors disabled:opacity-50"
          >
            ▾ {shortModelLabel(availableModels.find((m) => m.id === (model || defaultModel))?.label ?? 'model…')}
          </button>
          {modelMenuOpen && createPortal(
            <div
              data-model-menu
              className="fixed z-[90] w-[220px] max-h-[280px] overflow-y-auto rounded border border-terminal-amber/30 bg-[#121418] py-1 shadow-xl"
              style={{ top: modelMenuPos.top, left: modelMenuPos.left }}
            >
              {modelGroups.map((g) => (
                <div key={g.label || 'all'}>
                  {g.label && (
                    <div className="px-2 pt-1 text-[9px] font-mono font-bold text-terminal-amber/60">{g.label}</div>
                  )}
                  {g.items.map((m) => {
                    const current = m.id === (model || defaultModel);
                    return (
                      <button
                        key={m.id}
                        onClick={() => { patchSession(activeKey, { model: m.id }); setModelMenuOpen(false); }}
                        className={cn(
                          'w-full text-left px-2 py-1 text-[10px] font-mono truncate transition-colors',
                          current ? 'text-terminal-amber font-bold' : 'text-white/70 hover:bg-terminal-amber/10 hover:text-white',
                        )}
                      >
                        {current ? '✓ ' : ''}{shortModelLabel(m.label)}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>,
            document.body,
          )}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => patchSession(activeKey, { input: e.target.value })}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder={
              isStreaming
                ? 'AI is thinking — you can switch to another chat while waiting…'
                : sessionMode === 'script'
                  ? 'Describe a chart script… e.g. "RSI bands with 70/30 lines" (Enter to send)'
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
