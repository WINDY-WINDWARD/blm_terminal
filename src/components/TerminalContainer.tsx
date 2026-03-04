'use client';

import React, { useEffect } from 'react';
import { useAtom, useSetAtom } from 'jotai';
import {
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
  wsConnectedAtom,
} from '@/store/terminalStore';
import { wsService } from '@/lib/socket';

const VALID_WIDGETS = ['TOP', 'POS', 'ORDER', 'CHART', 'WATCH', 'SETTINGS'];

export function TerminalContainer({ children }: { children: React.ReactNode }) {
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const [activePanels, setActivePanels] = useAtom(activePanelsAtom);
  const [focusedPanel] = useAtom(focusedPanelAtom);
  const setWsConnected = useSetAtom(wsConnectedAtom);

  // Connect WebSocket on mount and track connection state
  useEffect(() => {
    wsService.connect();
    const unsub = wsService.onConnectionChange((connected) => setWsConnected(connected));
    return () => {
      unsub();
      wsService.disconnect();
    };
  }, [setWsConnected]);

  // Focus command bar on Escape or '/'
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === '/') {
        e.preventDefault();
        const input = document.getElementById('terminal-command-input');
        if (input) input.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Command processor: apply widget command to focused panel
  useEffect(() => {
    if (!activeCommand) return;
    if (VALID_WIDGETS.includes(activeCommand)) {
      setActivePanels((prev) => ({ ...prev, [focusedPanel]: activeCommand }));
    }
    setActiveCommand('');
  }, [activeCommand, focusedPanel, setActivePanels, setActiveCommand]);

  return (
    <main className="flex flex-col h-screen w-screen bg-terminal-bg text-terminal-amber overflow-hidden">
      {children}
    </main>
  );
}
