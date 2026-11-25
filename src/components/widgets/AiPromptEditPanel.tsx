'use client';

import React, { useState } from 'react';
import type { CustomPrompt } from '@/types/aiWorkflowTypes';
import { AiPromptTextEditor } from '@/components/widgets/AiPromptTextEditor';

export interface AiPromptEditPanelProps {
  prompt: CustomPrompt;
  onSave: (next: CustomPrompt) => void;
  onCancel: () => void;
}

export function AiPromptEditPanel({ prompt, onSave, onCancel }: AiPromptEditPanelProps) {
  const [title, setTitle] = useState(prompt.title);
  const [text, setText] = useState(prompt.prompt);

  const trimmedTitle = title.trim();
  const canSave = trimmedTitle.length > 0 && text.trim().length > 0 && text.length <= 4000;

  const handleSave = () => {
    if (!canSave) return;
    onSave({ ...prompt, title: trimmedTitle, prompt: text });
  };

  return (
    <div className="col-span-full rounded-lg bg-[#0c0c0f] border border-terminal-amber/40 p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-zinc-400">
          EDIT PROMPT
        </span>
        <button
          type="button"
          onClick={onCancel}
          className="text-[10px] font-mono text-zinc-500 hover:text-white transition-colors cursor-pointer"
          aria-label="Close editor"
        >
          ✕
        </button>
      </div>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        maxLength={80}
        placeholder="Title"
        className="bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md text-xs font-mono text-zinc-200 px-2 py-1 w-full outline-none"
      />
      <AiPromptTextEditor
        value={text}
        onChange={setText}
        onSave={handleSave}
        onCancel={onCancel}
      />
    </div>
  );
}
