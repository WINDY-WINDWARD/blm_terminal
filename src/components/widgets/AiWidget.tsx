'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
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

/**
 * Defense-in-depth: no backend path should ever leak a raw JSON blob into
 * the chat. If a provider error arrives looking like serialized JSON,
 * substitute a generic line (full detail stays in the backend log).
 */
export function sanitizeAiErrorMessage(message: string): string {
  const t = message.trim();
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
  { id: 'value',    label: '◈ Value Analyst',       description: 'Graham/Buffett intrinsic value & margin of safety lens' },
  { id: 'earnings', label: '📊 Earnings Forensics',  description: 'QoQ/YoY revenue, operating margin & cash conversion forensics' },
  { id: 'fno',      label: '⚡ F&O Derivatives',     description: 'Open interest buildup, PCR, implied volatility & option strategies' },
  { id: 'macro',    label: '🌐 Sector & Macro',      description: 'Sector rotation, FII/DII flows & macro policy impact' },
] as const;

type PersonaId = (typeof PERSONAS)[number]['id'];

// ─── Types ────────────────────────────────────────────────────────────────────

/** AI chat mode — per session. Script mode adds the Script Lab system prompt. */
export type AiMode = 'research' | 'script';

/** Script Lab mutation card — emitted by the backend as an extra SSE event */
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

// ─── Starter Prompts ──────────────────────────────────────────────────────────

interface StarterPrompt {
  tag: string;
  title: string;
  desc: string;
  prompt: string;
}

function getResearchStarterPrompts(symbol: string, exchange: string): StarterPrompt[] {
  const sym = symbol ? symbol.toUpperCase() : 'NIFTY';
  const ex = exchange ? exchange.toUpperCase() : 'NSE';
  return [
    {
      tag: 'EQUITY VALUATION & FUNDAMENTALS',
      title: `Evaluate ${sym}`,
      desc: 'Multi-model intrinsic valuation, debt & margin forensics, ROCE/ROE trends, and DCF fair value.',
      prompt: `Perform a comprehensive fundamental and valuation analysis for ${sym}.${ex}. Evaluate: 1) P/E and EV/EBITDA multiples vs sector peers, 2) ROCE and ROE sustainability, 3) Debt-to-equity and interest coverage safety, 4) Operating margin and cash flow trends, and 5) Peter Lynch and DCF intrinsic fair value estimates. Provide clear actionable risk factors.`,
    },
    {
      tag: 'MACRO & MARKET PULSE',
      title: 'Indian Market Rundown',
      desc: 'NIFTY 50 & SENSEX levels, market breadth, sector leadership, FII/DII net flows, and VIX sentiment.',
      prompt: 'Provide a complete Indian market rundown today: 1) Benchmark indices (NIFTY 50, SENSEX, NIFTY BANK) price action and key support/resistance levels, 2) NSE market breadth (advances vs declines), 3) Top outperforming and lagging sectors, 4) FII and DII net cash market flows, and 5) India VIX regime and overall volatility outlook.',
    },
    {
      tag: 'GLOBAL SPILLOVER',
      title: 'Global News & Macro Context',
      desc: 'US & Asian markets, Treasury yields, Brent crude, DXY dollar index, and domestic sector implications.',
      prompt: 'Synthesize current global macro and geopolitical developments: 1) US and Asian market cues, 2) US 10-year Treasury yields and Federal Reserve interest rate expectations, 3) Brent Crude and commodity price trends, and 4) DXY US Dollar index movement. Detail specific positive and negative spillovers onto key Indian sectors (IT, Pharma, Auto, Energy).',
    },
    {
      tag: 'SCREENER & DISCOVERY',
      title: 'Find Next Investment Idea',
      desc: 'High-conviction asymmetric setups across NSE with high ROCE (>20%), low debt, rising FCF, and technical momentum.',
      prompt: 'Identify 3-4 high-conviction asymmetric investment candidates across the NSE universe. Screen for companies with: 1) High capital efficiency (ROCE > 20%, ROE > 18%), 2) Prudent leverage (Debt/Equity < 0.5), 3) Consistent Free Cash Flow generation with expanding operating margins, and 4) Technical momentum or consolidation breakout. Provide the thesis, key catalysts, and risk parameters for each candidate.',
    },
  ];
}

function getScriptStarterPrompts(): StarterPrompt[] {
  return [
    {
      tag: 'OVERLAY SCRIPT',
      title: 'Σ Trend Ribbon (EMA 9/21/55)',
      desc: 'Multi-EMA institutional trend ribbon with dynamic bullish/bearish cloud fill and crossover signals.',
      prompt: 'Create an EMA 9, 21, and 55 trend ribbon indicator with dynamic cloud color fill and crossover signals.',
    },
    {
      tag: 'MEAN REVERSION',
      title: 'Σ Anchored VWAP + σ Bands',
      desc: 'Intraday anchored VWAP with upper and lower volatility exhaustion bands.',
      prompt: 'Build a VWAP indicator with +2 and -2 standard deviation bands for intraday mean reversion.',
    },
    {
      tag: 'MOMENTUM OSCILLATOR',
      title: 'Σ RSI Regime & Divergence',
      desc: 'RSI 14 with 70/30 overbought/oversold regime shading and price momentum divergence markers.',
      prompt: 'Write an RSI 14 script with 70/30 horizontal bands, regime coloring, and momentum divergence markers.',
    },
    {
      tag: 'VOLATILITY EXIT',
      title: 'Σ ATR Trailing Stop Line',
      desc: 'Dynamic chandelier exit stop line using 14-period Average True Range for risk management.',
      prompt: 'Create an ATR 14 trailing stop overlay script for systematic trend following and stop loss management.',
    },
  ];
}

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
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono border transition-colors',
        done
          ? 'border-[#27272a] text-zinc-300 bg-[#121216]'
          : 'border-terminal-amber/50 text-terminal-amber bg-terminal-amber/10 animate-pulse',
      )}
    >
      <span className={cn('text-[9px]', done ? 'text-emerald-400' : 'text-terminal-amber')}>
        {done ? '✓' : '⚡'}
      </span>
      <span>{name}</span>
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
    <div className="mt-2.5 rounded-md border border-emerald-500/40 bg-[#0d1512] p-2.5 max-w-full shadow-lg">
      <div className="flex items-center gap-2">
        <span className="text-emerald-400 font-bold text-sm">Σ</span>
        <span className="text-emerald-300 font-bold text-xs truncate flex-1 font-mono" title={card.name}>
          {card.name}
        </span>
        <span className="text-[10px] text-zinc-400 shrink-0 font-mono">
          {card.action === 'created' ? 'created' : `revised · rev ${card.rev_no}`}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-2">
        {card.accepted ? (
          <span className="text-xs text-emerald-400 font-semibold flex items-center gap-1 font-mono">
            <span>✓</span> on chart — tune parameters in the Σ menu
          </span>
        ) : (
          <>
            <button
              onClick={() => onAccept(card)}
              className="text-xs font-mono font-bold px-2.5 py-1 bg-emerald-500 text-black hover:bg-emerald-400 rounded transition-colors shadow-sm"
              title="Enable this script revision on the chart"
            >
              Accept → Chart
            </button>
            <button
              onClick={() => onDiscard(card)}
              className="text-xs font-mono px-2 py-1 border border-[#27272a] text-zinc-300 hover:text-white hover:border-zinc-500 rounded transition-colors"
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
        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed font-mono">{children}</p>,
        h1: ({ children }) => (
          <h1 className="text-sm font-bold text-terminal-amber mt-3 mb-1.5 border-b border-[#27272a] pb-1 font-mono">
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-xs font-bold text-terminal-amber mt-2.5 mb-1 font-mono">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-xs font-semibold text-terminal-amber/90 mt-2 mb-0.5 font-mono">{children}</h3>
        ),
        code: ({ children, className }) => {
          const isBlock = className?.startsWith('language-');
          if (isBlock) {
            return (
              <code className="block bg-[#050508] border border-[#27272a] rounded p-2.5 text-[11px] text-emerald-300 whitespace-pre overflow-x-auto my-2 font-mono">
                {children}
              </code>
            );
          }
          return (
            <code className="bg-[#121216] border border-[#27272a] rounded px-1.5 py-0.5 text-[11px] text-terminal-amber font-mono">
              {children}
            </code>
          );
        },
        pre: ({ children }) => <pre className="my-2">{children}</pre>,
        ul: ({ children }) => <ul className="list-none pl-3 mb-2 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside pl-1 mb-2 space-y-1 font-mono">{children}</ol>,
        li: ({ children }) => (
          <li className="flex gap-2 leading-relaxed">
            <span className="text-terminal-amber font-bold shrink-0">▸</span>
            <span className="flex-1">{children}</span>
          </li>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-terminal-amber/60 bg-[#121216]/60 pl-3 py-1 my-2 text-zinc-300 italic rounded-r">
            {children}
          </blockquote>
        ),
        strong: ({ children }) => <strong className="font-bold text-white">{children}</strong>,
        em: ({ children }) => <em className="italic text-terminal-amber/90">{children}</em>,
        hr: () => <hr className="border-[#27272a] my-3" />,
        table: ({ children }) => (
          <div className="overflow-x-auto my-2.5 rounded border border-[#27272a]">
            <table className="text-xs border-collapse w-full font-mono">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-[#14141a] border-b border-[#27272a]">{children}</thead>,
        th: ({ children }) => (
          <th className="px-3 py-1.5 text-left font-bold text-terminal-amber border-r border-[#27272a] last:border-r-0 text-[11px]">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-1.5 border-t border-r border-[#27272a] last:border-r-0 text-zinc-200 text-xs">
            {children}
          </td>
        ),
        tr: ({ children }) => <tr className="even:bg-[#101014] hover:bg-[#141418] transition-colors">{children}</tr>,
        a: ({ children, href }) => (
          <a
            href={href ?? '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="text-terminal-amber underline underline-offset-2 hover:text-amber-300 transition-colors"
          >
            {children}
          </a>
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

  if (isUser) {
    return (
      <div className="flex flex-col gap-1 items-end max-w-full">
        <div className="bg-[#14141a] text-zinc-100 border border-[#27272a] border-r-2 border-r-terminal-amber rounded-lg px-3 py-2 text-xs font-mono leading-relaxed max-w-[85%] break-words whitespace-pre-wrap shadow-md">
          {msg.content || <span className="opacity-40 animate-pulse">▋</span>}
        </div>
        <div className="flex items-center gap-1.5 px-1 text-[10px] text-zinc-400 font-mono">
          <span className="font-bold text-terminal-amber">YOU</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 items-start w-full">
      {toolCalls.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-1">
          {toolCalls.map((name, i) => (
            <ToolCallBadge key={i} name={name} done={isLastAssistant ? (toolsDone ?? false) : true} />
          ))}
        </div>
      )}
      <div
        className={cn(
          'w-full rounded-lg px-3.5 py-3 text-xs font-mono leading-relaxed break-words shadow-lg border transition-colors',
          hasError
            ? 'bg-rose-950/20 text-rose-300 border-rose-500/40'
            : 'bg-[#0c0c0f] text-zinc-200 border-[#27272a]',
        )}
      >
        <div className="flex items-center justify-between border-b border-[#27272a]/60 pb-1.5 mb-2">
          <div className="flex items-center gap-2">
            <span className="text-terminal-amber font-bold text-xs">◈ BLM AI</span>
            <span className="text-[10px] text-zinc-400 border border-[#27272a] bg-[#121216] px-1.5 py-0.2 rounded font-mono">
              COPILOT
            </span>
          </div>
        </div>
        {msg.content ? (
          <MarkdownContent content={msg.content} />
        ) : (
          <span className="opacity-40 animate-pulse">▋</span>
        )}
        {msg.card && !msg.card.dismissed && onAcceptCard && onDiscardCard && (
          <ScriptCardView card={msg.card} onAccept={onAcceptCard} onDiscard={onDiscardCard} />
        )}
      </div>
      <div className="flex items-center gap-2 px-1 text-[10px] text-zinc-400 font-mono">
        <span>blm ai copilot</span>
        {hasError && isLastAssistant && onRetry && (
          <button
            onClick={onRetry}
            className="text-terminal-amber hover:underline text-[10px]"
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
    try {
      const d = new Date(iso);
      return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
    } catch {
      return '';
    }
  };

  return (
    <div className="flex flex-col h-full w-full border-r border-[#27272a] bg-[#0c0c0f]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#27272a] shrink-0">
        <span className="text-xs font-bold text-zinc-300 font-mono uppercase tracking-wider">
          Sessions
        </span>
        <button
          onClick={() => onNewChat()}
          className="text-[11px] font-mono font-semibold text-terminal-amber hover:underline"
          title="New scratch chat"
        >
          + Scratch
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5 custom-scroll">
        {sessions.length === 0 ? (
          <div className="px-2 py-6 text-xs text-zinc-400 text-center font-mono">
            No past sessions
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
                  'group p-2 rounded cursor-pointer transition-all border text-left',
                  isActive
                    ? 'bg-terminal-amber/10 border-terminal-amber/50 text-white'
                    : 'bg-[#121216] border-[#27272a] hover:border-zinc-500 text-zinc-300',
                )}
              >
                <div className="flex items-start justify-between gap-1">
                  <span
                    className={cn(
                      'text-xs font-medium leading-tight flex-1 truncate',
                      isActive ? 'text-terminal-amber font-bold' : 'text-zinc-200',
                    )}
                  >
                    {s.title}
                  </span>
                  <div className="flex items-center gap-1 shrink-0">
                    {isStreaming && (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" title="Streaming…" />
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(s.id);
                      }}
                      className="opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-rose-400 text-xs px-1 transition-opacity"
                      title="Delete session"
                    >
                      ✕
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between text-[10px] text-zinc-400 mt-1.5 font-mono">
                  <span className="font-bold text-zinc-300">{s.symbol}</span>
                  <span>{s.message_count} msgs · {fmt(s.updated_at)}</span>
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
  const [aiAuthStatus, setAiAuthStatus] = useState<{ provider: string; is_configured: boolean } | null>(null);

  useEffect(() => {
    fetch('/api/py/ai/status')
      .then((r) => r.json())
      .then((d) => setAiAuthStatus(d))
      .catch(console.error);

    const intv = setInterval(() => {
      fetch('/api/py/ai/status')
        .then((r) => r.json())
        .then((d) => setAiAuthStatus(d))
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

  // ── Session map ────────────────────────────────────────────────────────────

  const [sessionMap, setSessionMap] = useState<Map<number | null, SessionState>>(() => {
    if (_persistedMap.size > 0) {
      const restored = new Map<number | null, SessionState>();
      for (const [k, v] of _persistedMap) {
        restored.set(k, { ...v, isStreaming: false, abortController: null });
      }
      return restored;
    }
    return new Map([[NEW_CHAT_KEY, emptySessionState()]]);
  });
  const [activeKey, setActiveKey] = useState<number | null>(() => {
    if (_persistedMap.size > 0) return _persistedActiveKey;
    return NEW_CHAT_KEY;
  });
  const hasSentRef = useRef(_persistedHasSent);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activePersona, setActivePersona] = useState<PersonaId | null>(null);

  const current = sessionMap.get(activeKey) ?? emptySessionState(defaultModel);
  const { messages, isStreaming, toolsDone, input, model, mode: sessionMode = 'research' } = current;

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

  // ── Module-level sync ──────────────────────────────────────────────────────

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

  const ongoingAbortsRef = useRef<Set<AbortController>>(new Set());
  useEffect(() => {
    return () => {
      for (const ctrl of ongoingAbortsRef.current) {
        ctrl.abort();
      }
    };
  }, []);

  // ── Helpers ────────────────────────────────────────────────────────────────

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
    staleTime: 0,
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

  const streamingKeys = new Set<number | null>(
    [...sessionMap.entries()].filter(([, s]) => s.isStreaming).map(([k]) => k),
  );

  // ── Handlers ───────────────────────────────────────────────────────────────

  const loadSession = useCallback(
    async (id: number) => {
      setActiveKey(id);
      setSidebarOpen(false);
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
    [sessionMap, activeKey, refetchSessions],
  );

  const startNewChat = useCallback(
    (mode: AiMode = 'research') => {
      setSessionMap((prev) => {
        const next = new Map(prev);
        next.set(NEW_CHAT_KEY, emptySessionState(defaultModel, mode));
        return next;
      });
      setActiveKey(NEW_CHAT_KEY);
      setSidebarOpen(false);
      setActivePersona(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    },
    [defaultModel],
  );

  const sendMessage = useCallback(
    async (forcedInput?: string, replaceLastAssistant?: boolean) => {
      const sessionKey = activeKey;
      const sessionState = sessionMap.get(sessionKey) ?? emptySessionState(defaultModel);
      const trimmed = (forcedInput ?? sessionState.input).trim();

      if (!trimmed || sessionState.isStreaming) return;

      const userMessage: ChatMessage = { role: 'user', content: trimmed };
      const priorMessages = replaceLastAssistant
        ? sessionState.messages.filter(
            (_, i, arr) => !(arr[i].role === 'assistant' && i === arr.length - 1),
          )
        : sessionState.messages;
      const historyWithUser = [...priorMessages, userMessage];

      const abort = new AbortController();
      ongoingAbortsRef.current.add(abort);

      hasSentRef.current = true;

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
        model: sessionState.model || defaultModel,
        mode: sessionState.mode ?? 'research',
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
            model: sessionState.model || defaultModel,
            session_id: sessionKey,
            persona: activePersona,
            mode: sessionState.mode ?? 'research',
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
        if ((err as Error)?.name === 'AbortError') {
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
    [activeKey, sessionMap, defaultModel, symbol, exchange, patchSession, refetchSessions, activePersona],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const handleStop = useCallback(() => {
    current.abortController?.abort();
  }, [current]);

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
  }, [prefill, activeKey, patchSession, setPrefill]);

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
  }, []);

  const starterPrompts =
    sessionMode === 'script' ? getScriptStarterPrompts() : getResearchStarterPrompts(symbol, exchange);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-full w-full flex overflow-hidden font-mono text-xs bg-[#09090b] text-[#f4f4f5] relative select-none">
      {/* Disclaimer Modal */}
      {showDisclaimer && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-terminal-amber/50 bg-[#09090b] p-4 text-center text-terminal-amber animate-pulse max-w-sm shadow-2xl rounded">
            <div className="font-bold mb-2 uppercase text-sm">⚠️ Disclaimer</div>
            <div className="text-[10px] leading-relaxed text-zinc-300">
              AI can make mistakes and the user takes all responsibility for any actions taken using the AI's advice/recommendations.
            </div>
          </div>
        </div>
      )}

      {/* Provider Configuration Banner */}
      {aiAuthStatus && !aiAuthStatus.is_configured && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-rose-500/50 bg-[#09090b] p-6 text-center text-rose-400 shadow-2xl max-w-sm flex flex-col items-center gap-3 rounded">
            <div className="font-bold uppercase text-lg">⚠️ Configuration Required</div>
            <div className="text-xs text-zinc-300 leading-relaxed font-mono">
              The AI Provider ({aiAuthStatus.provider}) is not fully configured.
              Please complete the setup in the <span className="text-terminal-amber font-bold">Settings widget</span>.
            </div>
            <div className="text-[10px] text-zinc-500 mt-2 font-mono">
              (This widget is locked until a valid provider is set)
            </div>
          </div>
        </div>
      )}

      {/* Collapsible Session Drawer */}
      {sidebarOpen && (
        <aside className="w-64 bg-[#0c0c0f] border-r border-[#27272a] flex flex-col shrink-0 z-20 transition-all">
          <SessionSidebar
            sessions={sessions}
            activeKey={activeKey}
            streamingKeys={streamingKeys}
            onSelectSession={loadSession}
            onDeleteSession={deleteSession}
            onNewChat={startNewChat}
          />
        </aside>
      )}

      {/* Main Workspace */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0 bg-[#09090b]">
        {/* Unified Bento Command Toolbar */}
        <div className="bg-[#09090b] border-b border-[#27272a] p-2 flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            {/* History Drawer Button */}
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-mono transition-colors',
                sidebarOpen
                  ? 'bg-terminal-amber/15 border-terminal-amber/50 text-terminal-amber font-bold'
                  : 'bg-[#121216] border-[#27272a] text-zinc-300 hover:border-terminal-amber/40 hover:text-white',
              )}
              title="Toggle Session Drawer"
            >
              <span className="text-terminal-amber">☰</span>
              <span className="text-[11px] font-medium">Sessions</span>
              {sessions.length > 0 && (
                <span className="text-[10px] bg-zinc-800 text-zinc-300 px-1 py-0.2 rounded font-mono">
                  {sessions.length}
                </span>
              )}
            </button>

            {/* Model Selector Bento Pill */}
            <div className="flex items-center bg-[#121216] border border-[#27272a] rounded px-2 py-0.5 focus-within:border-terminal-amber">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 shrink-0" title="Provider Active" />
              <select
                value={model || defaultModel}
                onChange={(e) => patchSession(activeKey, { model: e.target.value })}
                disabled={isStreaming}
                data-testid="ai-model-select"
                className="bg-transparent text-xs text-white font-mono outline-none cursor-pointer pr-1 py-0.5 disabled:opacity-50 max-w-[170px]"
              >
                {availableModels.length > 0 ? (
                  availableModels.some((m) => m.is_free !== undefined) ? (
                    <>
                      {availableModels.some((m) => m.is_free) && (
                        <optgroup label="Free Models" className="bg-[#121418] text-terminal-amber font-bold">
                          {availableModels
                            .filter((m) => m.is_free)
                            .map((m) => (
                              <option key={m.id} value={m.id} className="text-white font-normal">
                                {m.label}
                              </option>
                            ))}
                        </optgroup>
                      )}
                      {availableModels.some((m) => !m.is_free) && (
                        <optgroup label="Paid Models" className="bg-[#121418] text-zinc-400 font-bold">
                          {availableModels
                            .filter((m) => !m.is_free)
                            .map((m) => (
                              <option key={m.id} value={m.id} className="text-white font-normal">
                                {m.label}
                              </option>
                            ))}
                        </optgroup>
                      )}
                    </>
                  ) : (
                    (() => {
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
                      if (groups.size === 0) {
                        return availableModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                          </option>
                        ));
                      }
                      return (
                        <>
                          {[...groups.entries()].map(([name, items]) => (
                            <optgroup key={name} label={name} className="bg-[#121418] text-terminal-amber font-bold">
                              {items.map((m) => (
                                <option key={m.id} value={m.id} className="text-white font-normal">
                                  {m.label}
                                </option>
                              ))}
                            </optgroup>
                          ))}
                          {ungrouped.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.label}
                            </option>
                          ))}
                        </>
                      );
                    })()
                  )
                ) : (
                  <option value="">Loading models…</option>
                )}
              </select>
            </div>

            {/* Active Context Stock Pill */}
            <div className="flex items-center gap-1.5 bg-terminal-amber/10 border border-terminal-amber/30 px-2.5 py-1 rounded text-xs font-mono">
              <span className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold">CTX</span>
              <span className="text-terminal-amber font-bold">
                {symbol ? `${symbol}.${exchange}` : 'NIFTY.NSE'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Thinking indicator */}
            {isStreaming && (
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-500/10 border border-blue-400/30 text-blue-300 text-[11px] font-mono animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                <span>thinking…</span>
              </div>
            )}

            {/* Sliding Research | Script mode toggle */}
            <button
              role="switch"
              aria-checked={sessionMode === 'script'}
              data-testid="ai-mode-toggle"
              data-mode={sessionMode}
              onClick={() => patchSession(activeKey, { mode: sessionMode === 'script' ? 'research' : 'script' })}
              disabled={isStreaming}
              title="Research answers questions; Script writes versioned chart scripts (Script Lab)"
              className={cn(
                'relative w-[130px] h-[24px] rounded-full border transition-all shrink-0 disabled:opacity-50',
                modeTrackClass(sessionMode),
              )}
            >
              <span
                className={cn(
                  'absolute inset-0 flex items-center justify-between px-2 text-[10px] font-mono font-bold pointer-events-none',
                  sessionMode === 'script' ? 'text-emerald-300/85' : 'text-terminal-amber/85',
                )}
              >
                <span>Research</span>
                <span>Σ Script</span>
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

            {/* New Chat Button */}
            <button
              onClick={() => startNewChat(sessionMode)}
              className="px-2.5 py-1 rounded bg-[#121216] border border-[#27272a] hover:border-terminal-amber hover:text-terminal-amber text-zinc-200 text-xs font-mono font-semibold transition-colors"
              title="Create new scratch session"
            >
              + New
            </button>
          </div>
        </div>

        {/* Scrollable Message List / Empty State */}
        <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-3 min-h-0 custom-scroll">
          {messages.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center p-4 max-w-3xl mx-auto w-full my-auto">
              {/* Hero Bento Card */}
              <div className="w-full bg-[#0c0c0f] border border-[#27272a] rounded-lg p-4 mb-3 shadow-xl">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'text-base font-bold',
                        sessionMode === 'script' ? 'text-emerald-400' : 'text-terminal-amber',
                      )}
                    >
                      {sessionMode === 'script' ? 'Σ' : '◈'}
                    </span>
                    <span className="text-xs font-bold tracking-wider uppercase text-white font-mono">
                      {sessionMode === 'script' ? 'QUANT SCRIPT LAB' : 'BLM INTELLIGENCE COPILOT'}
                    </span>
                    <span className="text-[10px] text-zinc-400 bg-[#141419] border border-[#27272a] px-1.5 py-0.5 rounded font-mono">
                      {sessionMode === 'script' ? 'INDICATORS & OVERLAYS' : 'NSE LIVE ENGINE'}
                    </span>
                  </div>
                  <div className="text-[11px] font-mono text-zinc-400">
                    CTX: <span className="text-terminal-amber font-bold">{symbol ? `${symbol}.${exchange}` : 'NIFTY.NSE'}</span>
                  </div>
                </div>
                <p className="text-xs text-zinc-300 leading-relaxed font-mono">
                  {sessionMode === 'script'
                    ? 'Generate, optimize, and backtest custom technical indicators and chart overlays. Accept generated scripts to instantly mount them onto your chart panels.'
                    : `Institutional-grade equity analysis powered by real-time NSE tick data, multi-model intrinsic valuation engines, corporate filings, and global macro spillovers.`}
                </p>
              </div>

              {/* 2x2 Bento Starter Prompts Grid */}
              <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2.5">
                {starterPrompts.map((p, idx) => (
                  <button
                    key={idx}
                    onClick={() => void sendMessage(p.prompt)}
                    disabled={isStreaming}
                    className="group flex flex-col justify-between p-3 rounded-lg bg-[#0c0c0f] border border-[#27272a] hover:border-terminal-amber/60 hover:bg-[#121217] transition-all text-left shadow-md cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className={cn(
                            'text-[9px] font-mono font-bold uppercase tracking-wider',
                            sessionMode === 'script' ? 'text-emerald-400' : 'text-terminal-amber',
                          )}
                        >
                          {p.tag}
                        </span>
                        <span className="text-[10px] text-zinc-500 group-hover:text-terminal-amber font-mono transition-colors">
                          ↵ Launch
                        </span>
                      </div>
                      <h4 className="text-xs font-bold text-white group-hover:text-terminal-amber transition-colors font-mono mb-1">
                        {p.title}
                      </h4>
                      <p className="text-[11px] text-zinc-400 leading-relaxed group-hover:text-zinc-300 transition-colors font-mono">
                        {p.desc}
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, i) => {
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
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Persona Bento Strip */}
        <div className="px-3 py-1.5 bg-[#0c0c0f] border-t border-[#27272a] flex items-center gap-1.5 flex-wrap shrink-0">
          <span className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold mr-1">ANALYST:</span>
          {PERSONAS.map((p) => {
            const isSelected = activePersona === p.id;
            return (
              <button
                key={p.id}
                title={p.description}
                onClick={() => setActivePersona((prev) => (prev === p.id ? null : p.id))}
                className={cn(
                  'px-2.5 py-1 rounded text-xs font-medium border font-mono transition-all',
                  isSelected
                    ? 'bg-terminal-amber/15 border-terminal-amber text-terminal-amber font-bold shadow-sm'
                    : 'bg-[#121216] border-[#27272a] text-zinc-300 hover:border-zinc-500 hover:text-white',
                )}
              >
                {p.label}
              </button>
            );
          })}
          {activePersona && (
            <span className="ml-auto text-xs text-terminal-amber font-medium font-mono">
              {PERSONAS.find((p) => p.id === activePersona)?.description}
            </span>
          )}
        </div>

        {/* Elevated Bento Input Bar */}
        <div className="p-2.5 bg-[#09090b] border-t border-[#27272a] shrink-0">
          <div className="flex items-end gap-2 bg-[#121216] border border-[#27272a] focus-within:border-terminal-amber rounded-md p-2 transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => patchSession(activeKey, { input: e.target.value })}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              placeholder={
                isStreaming
                  ? 'AI is reasoning — you can switch sessions while waiting…'
                  : sessionMode === 'script'
                    ? 'Describe a chart script… e.g. "RSI 14 with 70/30 bands & divergence" (Enter to send)'
                    : `Ask about ${symbol ? `${symbol}.${exchange}` : 'NSE stocks'}, peers, valuation, or macro… (Enter to send)`
              }
              rows={1}
              className={cn(
                'flex-1 bg-transparent text-xs text-white placeholder-zinc-500 outline-none resize-none font-mono leading-relaxed min-h-[32px] max-h-[120px] overflow-y-auto',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
              style={{ fieldSizing: 'content' } as React.CSSProperties}
            />
            {isStreaming ? (
              <button
                onClick={handleStop}
                className="px-3.5 py-1.5 rounded bg-red-600/90 hover:bg-red-500 text-white font-bold text-xs font-mono transition-colors shrink-0"
              >
                STOP ■
              </button>
            ) : (
              <button
                onClick={() => void sendMessage()}
                disabled={!input.trim()}
                className={cn(
                  'px-3.5 py-1.5 rounded font-bold text-xs font-mono transition-colors shrink-0',
                  input.trim()
                    ? 'bg-terminal-amber text-black hover:bg-amber-400'
                    : 'bg-zinc-800 text-zinc-500 border border-zinc-700 cursor-not-allowed',
                )}
              >
                SEND ↵
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
