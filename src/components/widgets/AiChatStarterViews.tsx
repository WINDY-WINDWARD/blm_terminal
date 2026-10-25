'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import type { PersonaId, StarterPrompt } from '@/types/aiWidgetTypes';
import { PERSONAS } from '@/types/aiWidgetTypes';

export interface EmptyChatStateProps {
  sessionMode: 'research' | 'script';
  symbol: string;
  exchange: string;
  starterPrompts: StarterPrompt[];
  isStreaming: boolean;
  onLaunchPrompt: (prompt: string) => void;
}

export function EmptyChatState({
  sessionMode,
  symbol,
  exchange,
  starterPrompts,
  isStreaming,
  onLaunchPrompt,
}: EmptyChatStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-2 max-w-3xl mx-auto w-full my-auto @3xl:p-4">
      {/* Hero Bento Card */}
      <div className="w-full bg-[#0c0c0f] border border-[#27272a] rounded-lg p-3 mb-3 shadow-xl @3xl:p-4">
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
            : `Institutional-grade equity analysis powered by real-time NSE tick data, multi-model intrinsic valuation engines, corporate filings, and global macro spillovers.`}
        </p>
      </div>

      {/* 2x2 Bento Starter Prompts Grid */}
      <div className="w-full grid grid-cols-1 @md:grid-cols-2 gap-2.5">
        {starterPrompts.map((p, idx) => (
          <button
            key={idx}
            onClick={() => onLaunchPrompt(p.prompt)}
            disabled={isStreaming}
            className="group flex flex-col justify-between p-3 rounded-lg bg-[#0c0c0f] border border-[#27272a] hover:border-amber-400/60 hover:bg-[#121217] transition-all text-left shadow-md cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
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
