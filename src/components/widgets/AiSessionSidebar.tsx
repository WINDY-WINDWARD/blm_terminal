'use client';

import React from 'react';
import type { AttachedDocument, SessionSummary } from '@/types/aiWidgetTypes';
import { cn } from '@/lib/utils';

export interface SessionSidebarProps {
  sessions: SessionSummary[];
  libraryDocuments: AttachedDocument[];
  attachedDocumentIds: number[];
  activeKey: number | null;
  streamingKeys: Set<number | null>;
  onSelectSession: (id: number) => void;
  onDeleteSession: (id: number) => void;
  onNewChat: () => void;
  onAttachDocument: (document: AttachedDocument) => void;
  onDeleteDocument: (id: number) => void;
}

export function SessionSidebar({
  sessions,
  libraryDocuments,
  attachedDocumentIds,
  activeKey,
  streamingKeys,
  onSelectSession,
  onDeleteSession,
  onNewChat,
  onAttachDocument,
  onDeleteDocument,
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

      <div className="max-h-56 shrink-0 overflow-y-auto border-t border-[#27272a] p-2 custom-scroll">
        <div className="mb-1.5 text-[10px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
          Document Library
        </div>
        {libraryDocuments.length === 0 ? (
          <div className="px-1 py-3 text-[10px] text-zinc-400 font-mono">No uploaded files</div>
        ) : (
          <div className="space-y-1">
            {libraryDocuments.map((document) => {
              const attached = attachedDocumentIds.includes(document.id);
              return (
                <div
                  key={document.id}
                  className="flex items-center justify-between gap-1 rounded border border-[#27272a] bg-[#121216] px-2 py-1.5"
                >
                  <div className="min-w-0">
                    <div className={cn('text-[10px] font-bold', document.file_type === 'pdf' ? 'text-rose-400' : 'text-emerald-400')}>
                      {document.file_type === 'pdf' ? 'PDF' : 'CSV'}
                    </div>
                    <div className="truncate text-[10px] text-zinc-300" title={document.filename}>
                      {document.filename}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() => onAttachDocument(document)}
                      disabled={attached}
                      className={cn(
                        'rounded border px-1.5 py-0.5 text-[10px] font-mono transition-colors',
                        attached
                          ? 'border-[#27272a] text-zinc-500'
                          : 'border-terminal-amber/40 text-terminal-amber hover:bg-terminal-amber/10',
                      )}
                      title={attached ? 'Already attached' : 'Attach to current chat'}
                    >
                      {attached ? '✓' : '+'}
                    </button>
                    <button
                      onClick={() => onDeleteDocument(document.id)}
                      className="rounded border border-[#27272a] px-1.5 py-0.5 text-[10px] text-zinc-400 transition-colors hover:border-rose-500/40 hover:text-rose-400"
                      title="Delete from library"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
