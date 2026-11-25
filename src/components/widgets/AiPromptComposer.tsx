'use client';

import React, { useState } from 'react';

export interface AiPromptComposerProps {
  open: boolean;
  disabled?: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (description: string) => void;
}

const MAX_CHARS = 4000;

export function AiPromptComposer({
  open,
  disabled,
  onOpenChange,
  onSubmit,
}: AiPromptComposerProps) {
  const [description, setDescription] = useState('');

  const trimmed = description.trim();
  const isOverLimit = description.length > MAX_CHARS;
  const canSubmit = trimmed.length > 0 && !isOverLimit && !disabled;

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit(trimmed);
    setDescription('');
    onOpenChange(false);
  };

  const handleCancel = () => {
    setDescription('');
    onOpenChange(false);
  };

  if (!open) {
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={() => onOpenChange(true)}
        className="w-full border border-dashed border-[#27272a] hover:border-terminal-amber/60 rounded-lg p-3 flex items-center justify-center gap-2 text-[11px] font-mono text-zinc-500 hover:text-terminal-amber transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
      >
        + Create a prompt
      </button>
    );
  }

  return (
    <div className="w-full bg-[#0c0c0f] border border-terminal-amber/40 rounded-lg p-3 flex flex-col gap-2.5">
      <textarea
        value={description}
        disabled={disabled}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        placeholder="Describe what this prompt should do. e.g. Screen my watchlist for volume breakouts with rising delivery %."
        rows={3}
        className="w-full min-h-[64px] bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 resize-y p-2.5 outline-none transition-colors placeholder:text-zinc-600"
      />
      <div className="flex items-center justify-between gap-2">
        <span
          className={`text-[10px] font-mono ${
            isOverLimit ? 'text-red-400' : 'text-zinc-500'
          }`}
        >
          {description.length}/{MAX_CHARS}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCancel}
            className="border border-[#27272a] text-zinc-400 hover:text-white text-xs font-mono px-2.5 py-1 rounded transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={handleSubmit}
            className="bg-terminal-amber text-black text-xs font-mono font-bold px-2.5 py-1 rounded hover:bg-amber-400 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            CREATE WITH AI
          </button>
        </div>
      </div>
    </div>
  );
}
