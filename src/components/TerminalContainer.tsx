'use client';

import React, { useEffect } from 'react';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import {
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
  panelCountAtom,
  panelSizesAtom,
  selectedPanelsAtom,
  mergedGroupsAtom,
  getMergedGroupForPanel,
  validateMergeSelection,
  savedLayoutsAtom,
  layoutToastAtom,
  layoutConfirmAtom,
  authAtom,
} from '@/store/terminalStore';
import type { SavedLayout, PanelCount } from '@/store/terminalStore';
import {
  enqueueQueueOperation,
  updateAndPersistLayouts,
  normalizeSaveNameWithFlag,
} from '@/lib/layouts';
import { useSavedLayoutsSync } from '@/hooks/useSavedLayoutsSync';

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
  const [selectedPanels, setSelectedPanels] = useAtom(selectedPanelsAtom);
  const [mergedGroups, setMergedGroups] = useAtom(mergedGroupsAtom);
  const [savedLayouts, setSavedLayouts] = useAtom(savedLayoutsAtom);
  const setLayoutToast = useSetAtom(layoutToastAtom);
  const setLayoutConfirm = useSetAtom(layoutConfirmAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  const [auth] = useAtom(authAtom);

  const { processPendingQueue } = useSavedLayoutsSync();

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

  // Command processor: apply widget command to focused panel
  useEffect(() => {
    if (!activeCommand) return;

    if (activeCommand === 'LOGOUT') {
      fetch('/api/py/auth/logout', { method: 'POST' }).catch(() => {});
      window.dispatchEvent(new Event('auth-expired'));
      setActiveCommand('');
      return;
    }

    if (activeCommand === 'CLEAR') {
      setActivePanels((prev) => ({ ...prev, [focusedPanel]: 'EMPTY' }));
      setActiveCommand('');
      return;
    }

    // ── Layout save ──────────────────────────────────────────────────────
    if (activeCommand.startsWith('__SAVE_LAYOUT:')) {
      const rawName = activeCommand.slice('__SAVE_LAYOUT:'.length);
      const { name, wasShortened } = normalizeSaveNameWithFlag(
        rawName,
        Object.keys(savedLayouts)
      );
      const layout: SavedLayout = {
        name,
        activePanels: { ...activePanels },
        panelCount,
        mergedGroups: { ...mergedGroups },
        savedAt: Date.now(),
      };
      
      if (wasShortened) {
        setLayoutToast({
          visible: true,
          message: `Name was shortened to: "${name}"`,
          type: 'success',
        });
      }
      
      if (savedLayouts[name]) {
        // Existing layout — show overwrite confirmation
        setLayoutConfirm({ visible: true, layoutName: name, pendingLayout: layout });
      } else {
        // New layout — update atom and enqueue
        setSavedLayouts((prev) => {
          const next = { ...prev, [name]: layout };
          if (auth?.user?.id) {
            updateAndPersistLayouts(auth.user.id, () => next);
          }
          return next;
        });

        // Enqueue exactly one save operation; processPendingQueue will handle it
        if (auth?.user?.id) {
          const uId = auth.user.id;
          enqueueQueueOperation(uId, { type: 'save', name, payload: layout });
          processPendingQueue(uId);
        }
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

    // ── Layout size change (e.g. LAYOUT 2, LAYOUT 4, LAYOUT 6, LAYOUT 8) ───
    const layoutMatch = activeCommand.match(/^(?:LAYOUT\s+)?([2468])$/i);
    if (activeCommand.toUpperCase().startsWith('LAYOUT') || (layoutMatch && activeCommand.toUpperCase().startsWith('LAYOUT'))) {
      const match = activeCommand.match(/([2468])/);
      if (match) {
        const count = parseInt(match[1], 10) as PanelCount;
        setPanelCount(count);
        setPanelSizes(null);
        setSelectedPanels([]);
        setMergedGroups({});
        setLayoutToast({ visible: true, message: `Window layout set to ${count} panels`, type: 'success' });
        setActiveCommand('');
        return;
      }
      if (activeCommand.trim().toUpperCase() === 'LAYOUT') {
        setActivePanels((prev) => ({ ...prev, [focusedPanel]: 'SETTINGS' }));
        setLayoutToast({ visible: true, message: 'Type LAYOUT 2, 4, 6, or 8 to switch layout directly', type: 'success' });
        setActiveCommand('');
        return;
      }
    }

    let targetCommand = activeCommand;
    if (activeCommand === 'BREAKOUT') {
      targetCommand = 'BREAKOUTS';
    }

    const isValid = VALID_WIDGETS.includes(targetCommand);
    if (isValid) {
      setActivePanels((prev) => ({ ...prev, [focusedPanel]: targetCommand }));
    }
    setActiveCommand('');
  }, [activeCommand, focusedPanel, setActivePanels, setActiveCommand, activePanels, panelCount, mergedGroups, savedLayouts, setSavedLayouts, setLayoutToast, setLayoutConfirm, setPanelCount, setMergedGroups, setPanelSizes, setFocusedPanel, setSelectedPanels, auth, processPendingQueue]);

  // Handle popup widget restore requests from detached windows
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === '__REQUEST_RESTORE' && e.newValue) {
        const parts = e.newValue.split(':');
        if (parts.length < 3) return;
        const originPanelId = parts[0];
        const widgetTitle = parts[1];

        // Check if originPanelId is currently EMPTY
        if (!activePanels[originPanelId] || activePanels[originPanelId] === 'EMPTY') {
          setActivePanels((prev) => ({ ...prev, [originPanelId]: widgetTitle }));
          window.localStorage.setItem('__RESTORE_ACCEPTED', e.newValue);
          return;
        }

        // Otherwise find first slot from panel-1 to panel-<panelCount> that is 'EMPTY'
        let availablePanelId: string | null = null;
        for (let i = 1; i <= panelCount; i++) {
          const pid = `panel-${i}`;
          if (!activePanels[pid] || activePanels[pid] === 'EMPTY') {
            availablePanelId = pid;
            break;
          }
        }

        if (availablePanelId) {
          setActivePanels((prev) => ({ ...prev, [availablePanelId]: widgetTitle }));
          window.localStorage.setItem('__RESTORE_ACCEPTED', e.newValue);
        } else {
          // No empty slot available
          window.localStorage.setItem('__RESTORE_REJECTED', e.newValue);
        }
      }
    };

    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, [activePanels, panelCount, setActivePanels]);

  return (
    <main className="flex flex-col h-screen w-screen bg-terminal-bg text-terminal-amber overflow-hidden">
      {children}
    </main>
  );
}
