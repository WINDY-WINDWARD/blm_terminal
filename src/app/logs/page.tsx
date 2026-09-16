'use client';

import { useEffect, useRef, useState, useCallback, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { LogViewer } from '@/components/LogViewer';

const MAX_LINES = 2000;

function LogsPageInner() {
  const searchParams = useSearchParams();
  const initialLines = Number(searchParams.get('lines')) || 200;

  const [logLines, setLogLines] = useState<string[]>([]);
  const [logConnected, setLogConnected] = useState(false);
  const logBottomRef = useRef<HTMLDivElement>(null);
  const logEventSourceRef = useRef<EventSource | null>(null);

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    logBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logLines]);

  // Open SSE connection on mount
  useEffect(() => {
    setLogLines([]);
    setLogConnected(false);
    const es = new EventSource(`/api/jobs/logs/stream?lines=${initialLines}`);
    logEventSourceRef.current = es;
    es.onopen = () => setLogConnected(true);
    es.onmessage = (ev: MessageEvent) => {
      const line = ev.data as string;
      setLogLines(prev => {
        const next = [...prev, line];
        return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
      });
    };
    es.onerror = () => {
      setLogConnected(false);
    };
    return () => {
      es.close();
      logEventSourceRef.current = null;
    };
  }, [initialLines]);

  const handleClear = useCallback(() => {
    setLogLines([]);
  }, []);

  const handleClose = useCallback(() => {
    if (typeof window !== 'undefined' && window.opener) {
      window.close();
    }
  }, []);

  const hasOpener = typeof window !== 'undefined' && !!window.opener;

  return (
    <div className="h-screen w-screen bg-[#0a0a0a] text-white overflow-hidden">
      <LogViewer
        lines={logLines}
        connected={logConnected}
        logBottomRef={logBottomRef}
        onClear={handleClear}
        onClose={hasOpener ? handleClose : undefined}
      />
    </div>
  );
}

export default function LogsPage() {
  return (
    <Suspense fallback={
      <div className="h-screen w-screen bg-[#0a0a0a] text-white/30 flex items-center justify-center font-mono text-xs">
        Loading log viewer\u2026
      </div>
    }>
      <LogsPageInner />
    </Suspense>
  );
}
