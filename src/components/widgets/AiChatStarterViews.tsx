'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import type { PersonaId, StarterPrompt } from '@/types/aiWidgetTypes';
import { PERSONAS } from '@/types/aiWidgetTypes';
import type { CustomPrompt } from '@/types/aiWorkflowTypes';
import { formatIst, formatRelative } from '@/lib/aiWorkflowTime';
import { AiStarterSection } from '@/components/widgets/AiStarterSection';
import { AiStarterCard } from '@/components/widgets/AiStarterCard';
import { AiPromptComposer } from '@/components/widgets/AiPromptComposer';
import { AiPromptEditPanel } from '@/components/widgets/AiPromptEditPanel';

export interface EmptyChatStateProps {
  sessionMode: 'research' | 'script';
  symbol: string;
  exchange: string;
  systemPrompts: StarterPrompt[];
  isStreaming: boolean;
  onLaunchPrompt: (prompt: string) => void;
  userPrompts: CustomPrompt[];
  promptsLoading: boolean;
  promptsTotal: number;
  promptsPage: number;
  promptsHasMore: boolean;
  onCreatePrompt: (description: string) => void;
  onEditPrompt: (p: CustomPrompt) => void;
  onDeletePrompt: (p: CustomPrompt) => void;
  onDuplicateSystemPrompt: (p: StarterPrompt) => void;
  armedWorkflows?: number;
  nextRunAt?: string | null;
  onPageChange?: (page: number) => void;
}

export function EmptyChatState({
  sessionMode,
  symbol,
  exchange,
  systemPrompts,
  isStreaming,
  onLaunchPrompt,
  userPrompts,
  promptsLoading,
  promptsTotal,
  promptsPage,
  onCreatePrompt,
  onEditPrompt,
  onDeletePrompt,
  onDuplicateSystemPrompt,
  armedWorkflows,
  nextRunAt,
  onPageChange,
}: EmptyChatStateProps) {
  const [composerOpen, setComposerOpen] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<CustomPrompt | null>(null);

  const totalPages = Math.max(1, Math.ceil(promptsTotal / 4));
  let startPage = Math.max(0, promptsPage - 2);
  const endPage = Math.min(totalPages - 1, startPage + 4);
  if (endPage - startPage < 4) {
    startPage = Math.max(0, endPage - 4);
  }
  const pages: number[] = [];
  for (let i = startPage; i <= endPage; i++) {
    pages.push(i);
  }

  const startItem = promptsTotal === 0 ? 0 : promptsPage * 4 + 1;
  const endItem = Math.min((promptsPage + 1) * 4, promptsTotal);

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-2 max-w-3xl mx-auto w-full my-auto @3xl:p-4">
      {/* Compact Hero Card */}
      <div className="w-full bg-[#0c0c0f] border border-[#27272a] rounded-lg p-3 shadow-xl">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
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
            : 'Institutional-grade equity analysis powered by real-time NSE tick data, multi-model intrinsic valuation engines, corporate filings, and global macro spillovers.'}
        </p>
        {Boolean(armedWorkflows) && (
          <p className="text-[10px] font-mono text-zinc-500 mt-2">
            {armedWorkflows} {armedWorkflows === 1 ? 'workflow' : 'workflows'} armed
            {nextRunAt ? (
              <>
                {' • Next run: '}
                <span>{formatIst(nextRunAt)}</span>
                {formatRelative(nextRunAt) ? (
                  <span className="text-zinc-600"> ({formatRelative(nextRunAt)})</span>
                ) : null}
              </>
            ) : null}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-4 w-full mt-4">
        {/* SYSTEM PROMPTS section */}
        <AiStarterSection label="SYSTEM PROMPTS" count={4}>
          {systemPrompts.map((p, idx) => (
            <AiStarterCard
              key={idx}
              tag={p.tag}
              title={p.title}
              desc={p.desc}
              kind="system"
              accent={sessionMode === 'script' ? 'emerald' : 'amber'}
              disabled={isStreaming}
              onLaunch={() => onLaunchPrompt(p.prompt)}
              onDuplicate={() => onDuplicateSystemPrompt(p)}
            />
          ))}
        </AiStarterSection>

        {/* MY PROMPTS section */}
        <div className="flex flex-col gap-2 w-full">
          <AiStarterSection
            label="MY PROMPTS"
            count={promptsTotal}
            action={
              <button
                type="button"
                onClick={() => setComposerOpen(true)}
                className="text-[10px] font-mono text-zinc-400 hover:text-terminal-amber transition-colors cursor-pointer"
              >
                + New
              </button>
            }
          >
            <div className="col-span-full">
              <AiPromptComposer
                open={composerOpen}
                disabled={isStreaming}
                onOpenChange={setComposerOpen}
                onSubmit={(description) => {
                  onCreatePrompt(description);
                  setComposerOpen(false);
                }}
              />
            </div>
            {editingPrompt && (
              <AiPromptEditPanel
                key={editingPrompt.id}
                prompt={editingPrompt}
                onSave={(next) => {
                  onEditPrompt(next);
                  setEditingPrompt(null);
                }}
                onCancel={() => setEditingPrompt(null)}
              />
            )}
            {promptsLoading ? (
              <>
                <div className="h-[62px] rounded-lg bg-[#0c0c0f] border border-[#27272a] animate-pulse" />
                <div className="h-[62px] rounded-lg bg-[#0c0c0f] border border-[#27272a] animate-pulse" />
                <div className="h-[62px] rounded-lg bg-[#0c0c0f] border border-[#27272a] animate-pulse" />
              </>
            ) : (
              userPrompts.map((p) => (
                <AiStarterCard
                  key={p.id}
                  tag={p.tag}
                  title={p.title}
                  desc={p.description}
                  kind="user"
                  accent={sessionMode === 'script' ? 'emerald' : 'amber'}
                  disabled={isStreaming}
                  onLaunch={() => onLaunchPrompt(p.prompt)}
                  onEdit={() => setEditingPrompt(p)}
                  onDelete={() => onDeletePrompt(p)}
                />
              ))
            )}
          </AiStarterSection>

          {promptsTotal > 4 && (
            <div className="flex items-center justify-between pt-1 w-full">
              <span className="text-[10px] font-mono text-zinc-500">
                Showing {startItem}–{endItem} of {promptsTotal}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={promptsPage === 0}
                  onClick={() => onPageChange?.(promptsPage - 1)}
                  className="w-6 h-6 rounded text-[10px] font-mono border border-[#27272a] text-zinc-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label="Previous page"
                >
                  ‹
                </button>
                {pages.map((p) => {
                  const isCurrent = p === promptsPage;
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => onPageChange?.(p)}
                      className={cn(
                        'w-6 h-6 rounded text-[10px] font-mono border border-[#27272a] text-zinc-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer',
                        isCurrent &&
                          'bg-terminal-amber text-black font-bold border-terminal-amber hover:bg-terminal-amber hover:text-black',
                      )}
                    >
                      {p + 1}
                    </button>
                  );
                })}
                <button
                  type="button"
                  disabled={promptsPage >= totalPages - 1}
                  onClick={() => onPageChange?.(promptsPage + 1)}
                  className="w-6 h-6 rounded text-[10px] font-mono border border-[#27272a] text-zinc-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label="Next page"
                >
                  ›
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export interface PersonaStripProps {
  activePersona: PersonaId | null;
  onSelectPersona: (persona: PersonaId | null) => void;
}

export function PersonaStrip({ activePersona, onSelectPersona }: PersonaStripProps) {
  return (
    <div className="px-3 py-1.5 bg-[#0c0c0f] border-t border-[#27272a] flex items-center gap-1.5 flex-wrap shrink-0">
      <span className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold mr-1">ANALYST:</span>
      {PERSONAS.map((p) => {
        const isSelected = activePersona === p.id;
        return (
          <button
            key={p.id}
            title={p.description}
            onClick={() => onSelectPersona(isSelected ? null : p.id)}
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
  );
}
