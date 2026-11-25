'use client';

import React, { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import type { Workflow } from '@/types/aiWorkflowTypes';
import type { ModelOption } from '@/types/aiWidgetTypes';
import { AiWorkflowEditor } from '@/components/widgets/AiWorkflowEditor';

export interface AiWorkflowModalProps {
  open: boolean;
  workflow?: Workflow | null;
  models: ModelOption[];
  onClose: () => void;
  onAskCopilot: (description: string) => void;
  onSaved: () => void;
}

export function AiWorkflowModal({
  open,
  workflow,
  models,
  onClose,
  onAskCopilot,
  onSaved,
}: AiWorkflowModalProps) {
  const isEditing = Boolean(workflow?.id);
  const [tab, setTab] = useState<'copilot' | 'manual'>('copilot');
  const [copilotText, setCopilotText] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setTab('copilot');
      setCopilotText('');
    }
  }

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleCreateWithAi = () => {
    const trimmed = copilotText.trim();
    if (trimmed) {
      onAskCopilot(trimmed);
      onClose();
    }
  };

  return (
    <div
      className="absolute inset-0 z-[60] flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.72)' }}
      role="dialog"
      aria-modal="true"
      aria-label={isEditing ? 'Edit workflow' : 'New workflow'}
      onClick={handleOverlayClick}
    >
      <div
        className="w-full max-w-xl max-h-[85vh] flex flex-col overflow-hidden rounded-lg border border-[#27272a] bg-[#0c0c0f] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-[#27272a]">
          <div className="text-[10px] font-mono uppercase tracking-widest text-zinc-400">
            {isEditing ? 'EDIT WORKFLOW' : 'NEW WORKFLOW'}
          </div>
          <button
            type="button"
            onClick={onClose}
            title="Close"
            className="text-zinc-400 hover:text-zinc-200 transition-colors p-1 leading-none text-xs"
          >
            ✕
          </button>
        </div>

        {/* Tabs (create mode only) */}
        {!isEditing && (
          <div className="flex items-center border-b border-[#27272a]">
            <button
              type="button"
              onClick={() => setTab('copilot')}
              className={cn(
                'px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider border-b-2 transition-colors',
                tab === 'copilot'
                  ? 'text-terminal-amber font-bold border-terminal-amber'
                  : 'text-white/60 hover:text-terminal-amber border-transparent',
              )}
            >
              ASK COPILOT
            </button>
            <button
              type="button"
              onClick={() => setTab('manual')}
              className={cn(
                'px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider border-b-2 transition-colors',
                tab === 'manual'
                  ? 'text-terminal-amber font-bold border-terminal-amber'
                  : 'text-white/60 hover:text-terminal-amber border-transparent',
              )}
            >
              SET UP MANUALLY
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scroll">
          {!isEditing && tab === 'copilot' ? (
            <div className="p-3 flex flex-col gap-3">
              <textarea
                value={copilotText}
                onChange={(e) => setCopilotText(e.target.value)}
                autoFocus
                placeholder="Brief my watchlist every weekday at 10 and flag anything gapping more than 2%."
                className="w-full min-h-[110px] bg-[#121216] border border-[#27272a] focus:border-terminal-amber/60 rounded-md p-2 text-xs font-mono text-zinc-200 outline-none resize-y leading-relaxed"
              />
              <div className="text-[10px] font-mono text-zinc-500">
                Name, schedule, and scope are inferred from this.
              </div>
              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  onClick={handleCreateWithAi}
                  disabled={!copilotText.trim()}
                  className="py-1.5 px-3 bg-terminal-amber hover:bg-terminal-amber/80 text-black font-mono font-bold text-xs rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  CREATE WITH AI
                </button>
              </div>
            </div>
          ) : (
            <AiWorkflowEditor
              workflow={workflow}
              models={models}
              onCancel={onClose}
              onSaved={onSaved}
            />
          )}
        </div>
      </div>
    </div>
  );
}