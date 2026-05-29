'use client';

import React, { useEffect } from 'react';
import { useAtom, useSetAtom } from 'jotai';
import {
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
  panelCountAtom,
  wsConnectedAtom,
  cleanupOldLocalStorage,
} from '@/store/terminalStore';
import { marketWsService } from '@/lib/marketWs';

const VALID_WIDGETS = [
  'TOP',
  'POS',
  'ORDER',
  'CHART',
  'WATCH',
  'SETTINGS',
  'FDM',
  'DEALS',
  'LARGEDEALS',
  'BREAKOUTS',
  'NEWS',
  'ANALYSIS',
  'NOTIF',
  'ANNC',
  'SCAN',
  'SCREENER',
  'DOCS',
  'AI',
  'PORTFOLIO',
];

export function TerminalContainer({ children }: { children: React.ReactNode }) {
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const setActivePanels = useSetAtom(activePanelsAtom);
  const [focusedPanel, setFocusedPanel] = useAtom(focusedPanelAtom);
  const [panelCount] = useAtom(panelCountAtom);
  const setWsConnected = useSetAtom(wsConnectedAtom);

  // Clean up legacy localStorage keys once on mount
  useEffect(() => {
    cleanupOldLocalStorage();
  }, []);

  // Track market WebSocket connection state
  useEffect(() => {
    const unsub = marketWsService.onConnectionChange((connected) => setWsConnected(connected));
    return () => {
      unsub();
    };
  }, [setWsConnected]);

  // Focus command bar on Escape or '/'.
  // For '/', if the input is not already focused, focus it and seed the '/'
  // character so symbol-search mode activates immediately.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const input = document.getElementById('terminal-command-input') as HTMLInputElement | null;
      const inputFocused = input === document.activeElement;

      if (e.key === 'Escape') {
        e.preventDefault();
        if (input) input.focus();
      } else if (e.key === '/') {
        if (!inputFocused) {
          // Prevent the default so the '/' doesn't land twice, then manually
          // focus and set the value so the React state picks it up via an
          // input event.
          e.preventDefault();
          if (input) {
            input.focus();
            // Dispatch a native input event with '/' so React's onChange fires
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,
              'value'
            )?.set;
            if (nativeInputValueSetter) {
              nativeInputValueSetter.call(input, '/');
              input.dispatchEvent(new Event('input', { bubbles: true }));
            }
          }
        }
        // If already focused, let the keystroke fall through normally so the
        // user can type '/' freely.
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    const focusedPanelNumber = Number(focusedPanel.split('-')[1]);
    if (focusedPanelNumber > panelCount) {
      setFocusedPanel('panel-1');
    }
  }, [focusedPanel, panelCount, setFocusedPanel]);

  // Command processor: apply widget command to focused panel
  useEffect(() => {
    if (!activeCommand) return;

    let targetCommand = activeCommand;
    if (activeCommand === 'BREAKOUT') {
      targetCommand = 'BREAKOUTS';
    }

    const isValid = VALID_WIDGETS.includes(targetCommand);
    if (isValid) {
      setActivePanels((prev) => ({ ...prev, [focusedPanel]: targetCommand }));
    }
    setActiveCommand('');
  }, [activeCommand, focusedPanel, setActivePanels, setActiveCommand]);

  return (
    <main className="flex flex-col h-screen w-screen bg-terminal-bg text-terminal-amber overflow-hidden">
      {children}
    </main>
  );
}
