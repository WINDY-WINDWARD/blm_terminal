'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';

export interface AiPromptTextEditorProps {
  value: string;
  onChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving?: boolean;
  label?: string;
}

export function AiPromptTextEditor({
  value,
  onChange,
  onSave,
  onCancel,
  saving = false,
  label = 'Prompt',
}: AiPromptTextEditorProps) {
  const [initialValue] = useState(value);
  const isUnchanged = value === initialValue;
  const isEmpty = value.trim().length === 0;
  const isOverMax = value.length > 4000;
  const isSaveDisabled = isUnchanged || isEmpty || isOverMax || Boolean(saving);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      if (!isSaveDisabled) {
        e.preventDefault();
        onSave();
      }
    }
  };

  return (
    <div className="flex flex-col gap-1 w-full">
      <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400">
        <span className="truncate">{label}</span>
        <span className={cn(value.length > 3800 ? 'text-terminal-amber' : 'text-zinc-500')}>
          {value.length}/4000
        </span>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={saving}
        className="w-full bg-[#121216] border border-[#27272a] focus-within:border-terminal-amber/60 focus:border-terminal-amber/60 rounded-md p-2 text-xs font-mono text-zinc-200 leading-relaxed resize-y min-h-[96px] max-h-[40vh] outline-none"
      />
      <div className="flex items-center gap-2 mt-1">
        <button
          type="button"
          onClick={onSave}
          disabled={isSaveDisabled}
          className={cn(
            'text-xs font-mono font-bold px-2.5 py-1 bg-terminal-amber text-black rounded transition-colors shadow-sm',
            isSaveDisabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-terminal-amber/80',
          )}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="text-xs font-mono px-2 py-1 border border-[#27272a] text-zinc-300 hover:text-white hover:border-zinc-500 disabled:opacity-50 disabled:cursor-not-allowed rounded transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
