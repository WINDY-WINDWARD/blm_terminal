'use client';

import type { CSSProperties, RefObject } from 'react';
import { useIsMac } from '@/lib/usePlatform';
import { cn } from '@/lib/utils';

interface LogViewerProps {
  lines: string[];
  connected: boolean;
  logBottomRef: RefObject<HTMLDivElement | null>;
  onClear: () => void;
  onClose?: () => void;
}

export function LogViewer({ lines, connected, logBottomRef, onClear, onClose }: LogViewerProps) {
  const isMac = useIsMac();

  return (
    <div className="flex flex-col bg-[#0d0d0d] border border-terminal-gray/50 shadow-2xl h-full">
      {/* Header */}
      <div
        className={cn(
          "h-8 flex items-center gap-3 border-b border-terminal-gray/40 flex-shrink-0 select-none",
          isMac ? "pl-20 pr-3" : "pl-3 pr-36"
        )}
        style={{ WebkitAppRegion: 'drag' } as CSSProperties}
      >
        <span className="text-[10px] font-bold uppercase tracking-widest text-white/70">Backend Logs</span>
        <span className={`flex items-center gap-1 text-[10px] ${connected ? 'text-terminal-green' : 'text-terminal-amber'}`}>
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${connected ? 'bg-terminal-green animate-pulse' : 'bg-terminal-amber'}`} />
          {connected ? 'Live' : 'Connecting\u2026'}
        </span>
        <span className="ml-auto text-[10px] text-white/30">{lines.length} lines</span>
        <div className="flex items-center gap-1" style={{ WebkitAppRegion: 'no-drag' } as CSSProperties}>
          <button
            onClick={onClear}
            className="text-[10px] text-white/40 hover:text-white/70 transition-colors px-2 py-0.5 hover:bg-white/10"
            title="Clear log display"
          >
            Clear
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="text-[10px] text-white/40 hover:text-terminal-red transition-colors px-2 py-0.5 hover:bg-white/10"
              title="Close"
            >
              \u2715
            </button>
          )}
        </div>
      </div>

      {/* Log lines */}
      <div className="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed p-3 space-y-0.5">
        {lines.length === 0 ? (
          <div className="text-white/30 text-center pt-8">Waiting for log output\u2026</div>
        ) : (
          lines.map((line, i) => {
            const isError = /\bERROR\b|\bCRITICAL\b/.test(line);
            const isWarn = /\bWARNING\b|\bWARN\b/.test(line);
            const isInfo = /\bINFO\b/.test(line);
            return (
              <div
                key={i}
                className={`whitespace-pre-wrap break-all ${
                  isError ? 'text-terminal-red' :
                  isWarn ? 'text-terminal-amber' :
                  isInfo ? 'text-white/80' :
                  'text-white/50'
                }`}
              >
                {line}
              </div>
            );
          })
        )}
        <div ref={logBottomRef} />
      </div>
    </div>
  );
}
