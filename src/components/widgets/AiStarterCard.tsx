'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export interface AiStarterCardProps {
  tag: string;
  title: string;
  desc?: string | null;
  kind: 'system' | 'user';
  accent: 'amber' | 'emerald';
  disabled?: boolean;
  onLaunch: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onDuplicate?: () => void;
}

export function AiStarterCard({
  tag,
  title,
  desc,
  kind,
  accent,
  disabled,
  onLaunch,
  onEdit,
  onDelete,
  onDuplicate,
}: AiStarterCardProps) {
  return (
    <div className="group relative flex flex-col p-3 rounded-lg bg-[#0c0c0f] border border-[#27272a] hover:border-amber-400/60 hover:bg-[#121217] transition-all shadow-md">
      <button
        type="button"
        onClick={onLaunch}
        disabled={disabled}
        className="text-left flex-1 flex flex-col cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <div className="flex items-center justify-between mb-1 gap-2 w-full">
          <span
            className={cn(
              'text-[9px] font-mono font-bold uppercase tracking-wider',
              accent === 'emerald' ? 'text-emerald-400' : 'text-terminal-amber',
            )}
          >
            {tag}
          </span>
          {kind === 'system' ? (
            <span className="text-[9px] font-mono uppercase px-1 py-0.5 rounded border border-zinc-700 text-zinc-500">
              SYS
            </span>
          ) : (
            <span className="text-[10px] text-zinc-500 group-hover:text-terminal-amber font-mono transition-colors">
              ↵ Launch
            </span>
          )}
        </div>
        <h4 className="text-xs font-bold text-white group-hover:text-terminal-amber transition-colors font-mono mb-1">
          {title}
        </h4>
        {desc && (
          <p className="text-[11px] text-zinc-400 leading-relaxed line-clamp-2 font-mono">
            {desc}
          </p>
        )}
      </button>

      <div className="absolute bottom-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
        {kind === 'system' && onDuplicate && (
          <button
            type="button"
            title="Duplicate to my prompts"
            aria-label="Duplicate to my prompts"
            onClick={(e) => {
              e.stopPropagation();
              onDuplicate();
            }}
            className="w-5 h-5 flex items-center justify-center rounded border border-[#27272a] bg-[#121216] text-zinc-400 hover:text-white transition-colors cursor-pointer"
          >
            <svg
              className="w-3 h-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
          </button>
        )}
        {kind === 'user' && (
          <>
            {onEdit && (
              <button
                type="button"
                title="Edit"
                aria-label="Edit"
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit();
                }}
                className="w-5 h-5 flex items-center justify-center rounded border border-[#27272a] bg-[#121216] text-zinc-400 hover:text-white text-[11px] font-mono transition-colors cursor-pointer"
              >
                ✎
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                title="Delete"
                aria-label="Delete"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
                className="w-5 h-5 flex items-center justify-center rounded border border-[#27272a] bg-[#121216] text-zinc-400 hover:text-white text-[10px] font-mono transition-colors cursor-pointer"
              >
                ✕
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
