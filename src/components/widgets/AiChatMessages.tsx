'use client';

import React from 'react';
import type { AttachedDocument, ScriptCard } from '@/types/aiWidgetTypes';
import { cn } from '@/lib/utils';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export interface ToolCallBadgeProps {
  name: string;
  done: boolean;
}

export function ToolCallBadge({ name, done }: ToolCallBadgeProps) {
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

export interface ScriptCardViewProps {
  card: ScriptCard;
  onAccept: (card: ScriptCard) => void;
  onDiscard: (card: ScriptCard) => void;
}

export function ScriptCardView({ card, onAccept, onDiscard }: ScriptCardViewProps) {
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

export function MarkdownContent({ content }: { content: string }) {
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

export interface MessageBubbleProps {
  msg: {
    role: 'user' | 'assistant';
    content: string;
    toolCalls?: string[];
    isError?: boolean;
    card?: ScriptCard;
    attachments?: number[];
  };
  documents?: AttachedDocument[];
  isLastAssistant?: boolean;
  toolsDone?: boolean;
  onRetry?: () => void;
  onAcceptCard?: (card: ScriptCard) => void;
  onDiscardCard?: (card: ScriptCard) => void;
}

export function MessageBubble({ msg, documents = [], isLastAssistant, toolsDone, onRetry, onAcceptCard, onDiscardCard }: MessageBubbleProps) {
  const isUser = msg.role === 'user';
  const toolCalls = msg.toolCalls ?? [];
  const hasError = !isUser && msg.isError;

  if (isUser) {
    return (
      <div className="flex flex-col gap-1 items-end max-w-full">
        {(msg.attachments ?? []).length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5 max-w-[85%]">
            {(msg.attachments ?? []).map((documentId) => {
              const document = documents.find((item) => item.id === documentId);
              return (
                <span
                  key={documentId}
                  className="inline-flex items-center gap-1 rounded border border-[#27272a] bg-[#121216] px-2 py-0.5 text-[10px] font-mono text-zinc-300"
                  title={document?.filename ?? `Document #${documentId}`}
                >
                  <span className={document?.file_type === 'pdf' ? 'text-rose-400' : 'text-emerald-400'}>
                    {document?.file_type === 'pdf' ? 'PDF' : 'CSV'}
                  </span>
                  <span className="max-w-[180px] truncate">{document?.filename ?? `Document #${documentId}`}</span>
                </span>
              );
            })}
          </div>
        )}
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
