'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useAtom } from 'jotai';
import ReactDOM from 'react-dom';
import {
  layoutToastAtom,
  layoutConfirmAtom,
  savedLayoutsAtom,
} from '@/store/terminalStore';

const AUTO_DISMISS_MS = 3_000;

export function LayoutToast() {
  const [toast, setToast] = useAtom(layoutToastAtom);
  const [confirm, setConfirm] = useAtom(layoutConfirmAtom);
  const [, setSavedLayouts] = useAtom(savedLayoutsAtom);
  const progressRef = useRef(100);

  // ── Toast auto-dismiss ────────────────────────────────────────────────────
  useEffect(() => {
    if (!toast.visible) return;

    progressRef.current = 100;
    const startTime = Date.now();

    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, 100 - (elapsed / AUTO_DISMISS_MS) * 100);
      progressRef.current = remaining;
      const bar = document.getElementById('layout-toast-progress');
      if (bar) bar.style.width = `${remaining}%`;
    }, 50);

    const timeout = setTimeout(() => {
      setToast((prev) => ({ ...prev, visible: false }));
    }, AUTO_DISMISS_MS);

    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [toast.visible, toast.message, setToast]);

  // ── Confirm modal: Escape to cancel ───────────────────────────────────────
  useEffect(() => {
    if (!confirm.visible) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setConfirm({ visible: false, layoutName: '', pendingLayout: null });
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [confirm.visible, setConfirm]);

  const handleConfirmOverwrite = useCallback(() => {
    if (!confirm.pendingLayout) return;
    setSavedLayouts((prev) => ({
      ...prev,
      [confirm.layoutName]: confirm.pendingLayout!,
    }));
    setConfirm({ visible: false, layoutName: '', pendingLayout: null });
    setToast({ visible: true, message: `Layout "${confirm.layoutName}" saved`, type: 'success' });
  }, [confirm, setSavedLayouts, setConfirm, setToast]);

  const handleCancelOverwrite = useCallback(() => {
    setConfirm({ visible: false, layoutName: '', pendingLayout: null });
  }, [setConfirm]);

  if (typeof window === 'undefined') return null;

  return ReactDOM.createPortal(
    <>
      {/* ── Toast Notification ──────────────────────────────────────────── */}
      {toast.visible && (
        <div className="fixed inset-0 z-[9998] pointer-events-none">
          <div className="absolute top-4 right-4 sm:right-6 pointer-events-auto max-w-sm w-full">
            <div
              onClick={() => setToast((prev) => ({ ...prev, visible: false }))}
              className={`bg-zinc-900 border-2 rounded-lg shadow-2xl cursor-pointer transition-colors overflow-hidden ${
                toast.type === 'success'
                  ? 'border-terminal-green/80 hover:border-terminal-green'
                  : 'border-terminal-red/80 hover:border-terminal-red'
              }`}
            >
              <div className="px-4 py-3 flex items-center gap-3">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-black font-bold text-sm shrink-0 ${
                    toast.type === 'success' ? 'bg-terminal-green' : 'bg-terminal-red'
                  }`}
                >
                  {toast.type === 'success' ? '✓' : '✕'}
                </div>
                <div className="flex-1 min-w-0">
                  <div
                    className={`font-bold text-xs uppercase ${
                      toast.type === 'success' ? 'text-terminal-green' : 'text-terminal-red'
                    }`}
                  >
                    {toast.type === 'success' ? 'Layout' : 'Error'}
                  </div>
                  <div className="text-white/80 text-[11px] mt-0.5">{toast.message}</div>
                </div>
              </div>
              <div className="h-0.5 bg-zinc-800">
                <div
                  id="layout-toast-progress"
                  className={`h-full transition-none ${
                    toast.type === 'success' ? 'bg-terminal-green' : 'bg-terminal-red'
                  }`}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Overwrite Confirmation Modal ────────────────────────────────── */}
      {confirm.visible && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          onClick={handleCancelOverwrite}
        >
          <div className="absolute inset-0 bg-black/60" />
          <div
            className="relative bg-zinc-900 border-2 border-terminal-amber/80 rounded-lg shadow-2xl max-w-sm w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-4">
              <div className="text-terminal-amber font-bold text-xs uppercase tracking-widest mb-3">
                Overwrite Layout
              </div>
              <div className="text-white/90 text-xs font-mono mb-4">
                Layout &quot;<span className="text-terminal-amber">{confirm.layoutName}</span>&quot; already
                exists. Overwrite?
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={handleCancelOverwrite}
                  className="border border-terminal-gray text-white/70 hover:text-white hover:border-white/50 px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmOverwrite}
                  className="border border-terminal-amber bg-terminal-amber text-black hover:bg-terminal-amber/90 px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest transition-colors"
                >
                  Overwrite
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>,
    document.body,
  );
}
