'use client';

import React, { useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  formatBytes,
  MAX_ATTACHMENTS_PER_TURN,
  type AttachedDocument,
} from '@/types/aiWidgetTypes';
import type { UploadJob } from '@/hooks/useAiDocuments';

export interface AiInputBarProps {
  input: string;
  onChangeInput: (val: string) => void;
  onSend: (forcedInput?: string) => Promise<void>;
  onStop: () => void;
  isStreaming: boolean;
  sessionMode: 'research' | 'script';
  symbol: string;
  exchange: string;
  sessionDocuments: AttachedDocument[];
  uploadJobs: UploadJob[];
  dragActive: boolean;
  onDragOver: (e: React.DragEvent<HTMLDivElement>) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent<HTMLDivElement>) => void;
  onRemoveDocument: (documentId: number) => void;
  onUploadFile: (file: File) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export function AiInputBar({
  input,
  onChangeInput,
  onSend,
  onStop,
  isStreaming,
  sessionMode,
  symbol,
  exchange,
  sessionDocuments,
  uploadJobs,
  dragActive,
  onDragOver,
  onDragLeave,
  onDrop,
  onRemoveDocument,
  onUploadFile,
  inputRef,
}: AiInputBarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void onSend();
    }
  };

  return (
    <div
      className={cn(
        'p-2.5 bg-[#09090b] border-t border-[#27272a] shrink-0 transition-colors',
        dragActive && 'bg-terminal-amber/10 border-terminal-amber/50',
      )}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {(sessionDocuments.length > 0 || uploadJobs.length > 0) && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {sessionDocuments.map((document) => (
            <span
              key={document.id}
              className="inline-flex items-center gap-1.5 rounded border border-[#27272a] bg-[#121216] px-2 py-1 text-[10px] font-mono text-zinc-200"
            >
              <span className={document.file_type === 'pdf' ? 'text-rose-400 font-bold' : 'text-emerald-400 font-bold'}>
                {document.file_type === 'pdf' ? 'PDF' : 'CSV'}
              </span>
              <span className="max-w-[180px] truncate">{document.filename}</span>
              <span className="text-zinc-500">{formatBytes(document.file_size)}</span>
              <button
                onClick={() => onRemoveDocument(document.id)}
                className="text-zinc-400 hover:text-rose-400 transition-colors"
                title="Remove attachment"
              >
                ✕
              </button>
            </span>
          ))}
          {uploadJobs.map((job) => (
            <span
              key={job.tempId}
              className={cn(
                'inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] font-mono',
                job.error
                  ? 'border-rose-500/50 bg-rose-950/20 text-rose-300'
                  : 'border-[#27272a] bg-[#121216] text-zinc-300',
              )}
            >
              {job.error ? <span>⚠ {job.filename}: {job.error}</span> : <><span className="animate-pulse">▲</span><span className="max-w-[160px] truncate">{job.filename}</span><span>{job.progress}%</span></>}
            </span>
          ))}
        </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.csv,.tsv,application/pdf,text/csv"
        multiple
        className="hidden"
        onChange={(event) => {
          Array.from(event.target.files ?? []).forEach((file) => onUploadFile(file));
          event.target.value = '';
        }}
      />
      <div className="flex items-end gap-2 bg-[#121216] border border-[#27272a] focus-within:border-terminal-amber rounded-md p-2 transition-colors">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming || sessionDocuments.length >= MAX_ATTACHMENTS_PER_TURN}
          className="shrink-0 rounded border border-[#27272a] bg-[#0c0c0f] px-2 py-1.5 text-sm text-zinc-300 transition-colors hover:border-terminal-amber hover:text-terminal-amber disabled:cursor-not-allowed disabled:opacity-40"
          title="Attach PDF or CSV"
        >
          📎
        </button>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => onChangeInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder={
            isStreaming
              ? 'AI is reasoning — you can switch sessions while waiting…'
              : sessionMode === 'script'
                ? 'Describe a chart script… e.g. "RSI 14 with 70/30 bands & divergence" (Enter to send)'
                : `Ask about ${symbol ? `${symbol}.${exchange}` : 'NSE stocks'}, peers, valuation, or macro… (Enter to send)`
          }
          rows={1}
          className={cn(
            'flex-1 bg-transparent text-xs text-white placeholder-zinc-500 outline-none resize-none font-mono leading-relaxed min-h-[32px] max-h-[120px] overflow-y-auto',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
          style={{ fieldSizing: 'content' } as React.CSSProperties}
        />
        {isStreaming ? (
          <button
            onClick={onStop}
            className="px-3.5 py-1.5 rounded bg-red-600/90 hover:bg-red-500 text-white font-bold text-xs font-mono transition-colors shrink-0"
          >
            STOP ■
          </button>
        ) : (
          <button
            onClick={() => void onSend()}
            disabled={!input.trim()}
            className={cn(
              'px-3.5 py-1.5 rounded font-bold text-xs font-mono transition-colors shrink-0',
              input.trim()
                ? 'bg-terminal-amber text-black hover:bg-amber-400'
                : 'bg-zinc-800 text-zinc-500 border border-zinc-700 cursor-not-allowed',
            )}
          >
            SEND ↵
          </button>
        )}
      </div>
    </div>
  );
}
