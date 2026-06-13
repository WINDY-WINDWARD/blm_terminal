'use client';

import React, { useEffect } from 'react';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import {
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
  openAlgoAvailableAtom,
  panelCountAtom,
  panelSizesAtom,
  wsConnectedAtom,
  selectedPanelsAtom,
  mergedGroupsAtom,
  getMergedGroupForPanel,
  validateMergeSelection,
  cleanupOldLocalStorage,
  savedLayoutsAtom,
  layoutToastAtom,
  layoutConfirmAtom,
} from '@/store/terminalStore';
import type { SavedLayout } from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';

function isTextInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  return (
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    (el as HTMLElement).isContentEditable
  );
}

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
  'ADMIN',
  'PICKS',
];

export function TerminalContainer({ children }: { children: React.ReactNode }) {
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const setActivePanels = useSetAtom(activePanelsAtom);
  const [focusedPanel, setFocusedPanel] = useAtom(focusedPanelAtom);
  const [panelCount, setPanelCount] = useAtom(panelCountAtom);
  const setPanelSizes = useSetAtom(panelSizesAtom);
  const setWsConnected = useSetAtom(wsConnectedAtom);
  const [selectedPanels, setSelectedPanels] = useAtom(selectedPanelsAtom);
  const [mergedGroups, setMergedGroups] = useAtom(mergedGroupsAtom);
  const setOpenAlgoAvailable = useSetAtom(openAlgoAvailableAtom);
  const [savedLayouts, setSavedLayouts] = useAtom(savedLayoutsAtom);
  const setLayoutToast = useSetAtom(layoutToastAtom);
  const setLayoutConfirm = useSetAtom(layoutConfirmAtom);
  const activePanels = useAtomValue(activePanelsAtom);

  // Clean up legacy localStorage keys once on mount
  useEffect(() => {
    cleanupOldLocalStorage();
  }, []);

  // Track market WebSocket connection state
  useEffect(() => {
    const unsub = marketDataService.onConnectionChange((connected) => setWsConnected(connected));
    return () => {
      unsub();
    };
  }, [setWsConnected]);

  // Check OpenAlgo health on mount
  useEffect(() => {
    fetch('/api/openalgo/health')
      .then((r) => r.json())
      .then((data: { available: boolean }) => setOpenAlgoAvailable(data.available))
      .catch(() => setOpenAlgoAvailable(false));
  }, [setOpenAlgoAvailable]);

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
      } else if (e.key === 'm' && !isTextInputFocused()) {
        e.preventDefault();
        if (selectedPanels.length < 2) {
          console.error('Select at least 2 panels (Ctrl+Click) to merge');
          return;
        }
        const validation = validateMergeSelection(
          selectedPanels,
          panelCount,
          mergedGroups,
        );
        if (!validation.valid) {
          console.error(validation.error);
          return;
        }
        // Use the first selected panel as the primary panel
        const sorted = [...selectedPanels].sort((a, b) => {
          const na = parseInt(a.split('-')[1]);
          const nb = parseInt(b.split('-')[1]);
          return na - nb;
        });
        const primary = sorted[0];
        setMergedGroups((prev) => ({
          ...prev,
          [primary]: { panels: sorted, primary },
        }));
        setSelectedPanels([]);
        setFocusedPanel(primary);
      } else if (e.key === 'u' && !isTextInputFocused()) {
        e.preventDefault();
        const group = getMergedGroupForPanel(focusedPanel, mergedGroups);
        if (group) {
          setMergedGroups((prev) => {
            const next = { ...prev };
            delete next[group.primary];
            return next;
          });
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedPanels, panelCount, mergedGroups, focusedPanel, setFocusedPanel, setSelectedPanels, setMergedGroups]);

  useEffect(() => {
    const focusedPanelNumber = Number(focusedPanel.split('-')[1]);
    if (focusedPanelNumber > panelCount) {
      setFocusedPanel('panel-1');
    }
  }, [focusedPanel, panelCount, setFocusedPanel]);

  const openAlgoAvailable = useAtomValue(openAlgoAvailableAtom);

  // Command processor: apply widget command to focused panel
  useEffect(() => {
    if (!activeCommand) return;

    if (activeCommand === 'LOGOUT') {
      fetch('/api/py/auth/logout', { method: 'POST' }).catch(() => {});
      window.dispatchEvent(new Event('auth-expired'));
      setActiveCommand('');
      return;
    }

    // ── Layout save ──────────────────────────────────────────────────────
    if (activeCommand.startsWith('__SAVE_LAYOUT:')) {
      const name = activeCommand.slice('__SAVE_LAYOUT:'.length);
      const layout: SavedLayout = {
        name,
        activePanels: { ...activePanels },
        panelCount,
        mergedGroups: { ...mergedGroups },
        savedAt: Date.now(),
      };
      if (savedLayouts[name]) {
        // Existing layout — show overwrite confirmation
        setLayoutConfirm({ visible: true, layoutName: name, pendingLayout: layout });
      } else {
        setSavedLayouts((prev) => ({ ...prev, [name]: layout }));
        setLayoutToast({ visible: true, message: `Layout "${name}" saved`, type: 'success' });
      }
      setActiveCommand('');
      return;
    }

    // ── Layout load ──────────────────────────────────────────────────────
    if (activeCommand.startsWith('__LOAD_LAYOUT:')) {
      const name = activeCommand.slice('__LOAD_LAYOUT:'.length);
      const layout = savedLayouts[name];
      if (!layout) {
        setLayoutToast({ visible: true, message: `Layout "${name}" not found`, type: 'error' });
        setActiveCommand('');
        return;
      }
      // Apply in order: panelCount → mergedGroups → activePanels
      setPanelCount(layout.panelCount);
      setMergedGroups(layout.mergedGroups);
      setActivePanels(layout.activePanels);
      setPanelSizes(null);
      setFocusedPanel('panel-1');
      setSelectedPanels([]);
      setLayoutToast({ visible: true, message: `Layout "${name}" loaded`, type: 'success' });
      setActiveCommand('');
      return;
    }

    let targetCommand = activeCommand;
    if (activeCommand === 'BREAKOUT') {
      targetCommand = 'BREAKOUTS';
    }

    const openAlgoWidgets = new Set(['ORDER', 'POS']);
    const validWidgets = openAlgoAvailable
      ? VALID_WIDGETS
      : VALID_WIDGETS.filter((w) => !openAlgoWidgets.has(w));

    const isValid = validWidgets.includes(targetCommand);
    if (isValid) {
      setActivePanels((prev) => ({ ...prev, [focusedPanel]: targetCommand }));
    }
    setActiveCommand('');
  }, [activeCommand, focusedPanel, setActivePanels, setActiveCommand, openAlgoAvailable, activePanels, panelCount, mergedGroups, savedLayouts, setSavedLayouts, setLayoutToast, setLayoutConfirm, setPanelCount, setMergedGroups, setPanelSizes, setFocusedPanel, setSelectedPanels]);

  return (
    <main className="flex flex-col h-screen w-screen bg-terminal-bg text-terminal-amber overflow-hidden">
      {children}
    </main>
  );
}
