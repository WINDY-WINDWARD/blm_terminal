'use client';

import React, { useState } from 'react';
import type { WorkflowCardPayload } from '@/types/aiWorkflowTypes';
import { formatIst, formatRelative } from '@/lib/aiWorkflowTime';
import { cn } from '@/lib/utils';
import { AiPromptTextEditor } from './AiPromptTextEditor';

export interface AiWorkflowCardViewProps {
  card: WorkflowCardPayload;
  onAction: (
    action: 'run' | 'open' | 'undo' | 'apply' | 'discard' | 'edit',
    card: WorkflowCardPayload,
  ) => void;
  disabled?: boolean;
}

function extractLines(data: unknown): string[] {
  if (data === null || data === undefined) return [];
  if (typeof data === 'string') {
    return data.split('\n');
  }
  if (Array.isArray(data)) {
    return data.flatMap((item) => extractLines(item));
  }
  if (typeof data === 'object') {
    const lines: string[] = [];
    for (const [key, val] of Object.entries(data as Record<string, unknown>)) {
      if (val === undefined || val === null) continue;
      if (typeof val === 'string') {
        if (val.includes('\n')) {
          lines.push(`${key}:`);
          lines.push(...val.split('\n'));
        } else {
          lines.push(`${key}: ${val}`);
        }
      } else if (typeof val === 'object') {
        lines.push(`${key}: ${JSON.stringify(val)}`);
      } else {
        lines.push(`${key}: ${String(val)}`);
      }
    }
    return lines;
  }
  return [String(data)];
}

function computeLineDiff(prevData: unknown, newData: unknown) {
  const prevLines = extractLines(prevData);
  const newLines = extractLines(newData);

  const prevSet = new Set(prevLines);
  const newSet = new Set(newLines);

  const removed = Array.from(new Set(prevLines.filter((l) => !newSet.has(l))));
  const added = Array.from(new Set(newLines.filter((l) => !prevSet.has(l))));

  return [
    ...removed.map((line) => ({ type: 'removed' as const, line })),
    ...added.map((line) => ({ type: 'added' as const, line })),
  ];
}

export function AiWorkflowCardView({
  card,
  onAction,
  disabled = false,
}: AiWorkflowCardViewProps) {
  const initialPrompt =
    (card as { prompt?: string }).prompt ??
    (card.changes?.prompt as string) ??
    (card.previous?.prompt as string) ??
    '';

  const [isEditing, setIsEditing] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState(initialPrompt);

  const handleStartEdit = () => {
    setDraftPrompt(initialPrompt);
    setIsEditing(true);
  };

  const handleSaveEdit = () => {
    onAction('edit', { ...card, prompt: draftPrompt } as WorkflowCardPayload);
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setDraftPrompt(initialPrompt);
  };

  const ist = card.next_run_at ? formatIst(card.next_run_at) : '';
  const rel = card.next_run_at ? formatRelative(card.next_run_at) : '';
  const nextFormatted = ist
    ? `Next ${ist}${rel ? ` (${rel})` : ''}`
    : rel
      ? `Next ${rel}`
      : null;

  const prevObj = card.previous;
  const newObj =
    (card as { new?: unknown }).new ??
    (typeof card.changes === 'object' && card.changes
      ? { ...(typeof card.previous === 'object' ? card.previous : {}), ...card.changes }
      : card.changes);

  const diffLines = card.status === 'proposed' ? computeLineDiff(prevObj, newObj) : [];

  const name = card.name || card.title || 'Workflow';

  return (
    <div className="mt-2.5 rounded-md border border-terminal-amber/40 bg-[#12100a] p-2.5 max-w-full shadow-lg">
      <div className="flex items-center gap-2">
        <span className="text-terminal-amber text-xs font-mono shrink-0">⏱</span>
        <span
          className="text-terminal-amber font-bold text-xs truncate flex-1 font-mono"
          title={name}
        >
          {name}
        </span>
        {card.status === 'created' ? (
          <span className="text-[10px] font-mono uppercase text-terminal-amber border border-terminal-amber/30 bg-terminal-amber/10 px-1.5 py-0.5 rounded shrink-0">
            CREATED
          </span>
        ) : (
          <span className="text-[10px] font-mono uppercase text-blue-300 border border-blue-400/30 bg-blue-950/20 px-1.5 py-0.5 rounded shrink-0">
            PROPOSED
          </span>
        )}
      </div>

      {isEditing ? (
        <div className="mt-2">
          <AiPromptTextEditor
            value={draftPrompt}
            onChange={setDraftPrompt}
            onSave={handleSaveEdit}
            onCancel={handleCancelEdit}
            saving={disabled}
            label="Workflow Prompt"
          />
        </div>
      ) : (
        <>
          {(card.schedule_label || nextFormatted) && (
            <div className="text-[11px] font-mono text-zinc-400 mt-1 flex flex-wrap items-center gap-1.5">
              {card.schedule_label && <span>{card.schedule_label}</span>}
              {card.schedule_label && nextFormatted && <span>·</span>}
              {nextFormatted && <span>{nextFormatted}</span>}
            </div>
          )}

          {card.symbols && card.symbols.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {card.symbols.map((sym) => (
                <span
                  key={sym}
                  className="text-[9px] font-mono px-1 py-0.5 rounded bg-[#1a1a20] border border-[#27272a] text-zinc-300"
                >
                  {sym}
                </span>
              ))}
            </div>
          )}

          {card.status === 'proposed' && (
            <div className="mt-2 bg-[#050508] border border-[#27272a] rounded p-2 text-[10px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
              {diffLines.length === 0 ? (
                <div className="text-zinc-500 italic">No line changes</div>
              ) : (
                diffLines.map((item, idx) => (
                  <div
                    key={idx}
                    className={cn(item.type === 'removed' ? 'text-red-400' : 'text-emerald-400')}
                  >
                    {item.type === 'removed' ? `- ${item.line}` : `+ ${item.line}`}
                  </div>
                ))
              )}
            </div>
          )}

          <div className="flex items-center gap-2 mt-2">
            {card.status === 'created' ? (
              <>
                <button
                  type="button"
                  onClick={() => onAction('run', card)}
                  disabled={disabled}
                  className="text-xs font-mono font-bold px-2.5 py-1 bg-terminal-amber text-black hover:bg-terminal-amber/80 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors shadow-sm"
                >
                  Run now
                </button>
                <button
                  type="button"
                  onClick={() => onAction('open', card)}
                  disabled={disabled}
                  className="text-xs font-mono px-2 py-1 border border-[#27272a] text-zinc-300 hover:text-white hover:border-zinc-500 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                >
                  Open
                </button>
                <button
                  type="button"
                  onClick={handleStartEdit}
                  disabled={disabled}
                  className="text-xs font-mono px-2 py-1 border border-[#27272a] text-zinc-300 hover:text-white hover:border-zinc-500 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => onAction('undo', card)}
                  disabled={disabled}
                  className="text-xs font-mono px-2 py-1 border border-[#27272a] text-red-400 hover:text-red-300 hover:border-red-500/50 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                >
                  Undo
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => onAction('apply', card)}
                  disabled={disabled}
                  className="text-xs font-mono font-bold px-2.5 py-1 bg-terminal-amber text-black hover:bg-terminal-amber/80 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors shadow-sm"
                >
                  Apply
                </button>
                <button
                  type="button"
                  onClick={() => onAction('discard', card)}
                  disabled={disabled}
                  className="text-xs font-mono px-2 py-1 border border-[#27272a] text-zinc-300 hover:text-white hover:border-zinc-500 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
                >
                  Discard
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
