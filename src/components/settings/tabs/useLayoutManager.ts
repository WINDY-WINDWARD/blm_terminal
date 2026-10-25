'use client';

import { useAtom, useSetAtom } from 'jotai';
import {
  panelSizesAtom,
  selectedPanelsAtom,
  mergedGroupsAtom,
  savedLayoutsAtom,
  authAtom,
  layoutToastAtom,
  type PanelCount,
  type SavedLayout,
} from '@/store/terminalStore';
import {
  enqueueQueueOperation,
  updateAndPersistLayouts,
  normalizeRenameNameWithFlag,
} from '@/lib/layouts';
import { useSavedLayoutsSync } from '@/hooks/useSavedLayoutsSync';

export function useLayoutManager({
  setPanelCount,
}: {
  setPanelCount: (count: PanelCount) => void;
}) {
  const [auth] = useAtom(authAtom);
  const [, setPanelSizes] = useAtom(panelSizesAtom);
  const [, setSelectedPanels] = useAtom(selectedPanelsAtom);
  const [, setMergedGroups] = useAtom(mergedGroupsAtom);
  const [savedLayouts, setSavedLayouts] = useAtom(savedLayoutsAtom);
  const setLayoutToast = useSetAtom(layoutToastAtom);
  const { processPendingQueue } = useSavedLayoutsSync();

  const handlePanelCountChange = (count: PanelCount) => {
    setPanelCount(count);
    setPanelSizes(null);
    setSelectedPanels([]);
    setMergedGroups({});
  };

  const handleDeleteLayout = (name: string) => {
    if (!confirm(`Delete layout "${name}"?`)) return;
    setSavedLayouts((prev) => {
      const next = { ...prev };
      delete next[name];
      if (auth?.user?.id) updateAndPersistLayouts(auth.user.id, () => next);
      return next;
    });

    if (auth?.user?.id) {
      const uId = auth.user.id;
      enqueueQueueOperation(uId, { type: 'delete', name });
      processPendingQueue(uId);
    }
  };

  const handleRenameLayout = (oldName: string, rawNewNameInput: string) => {
    const rawNewName = rawNewNameInput.trim();
    const { name: newName, wasShortened } = normalizeRenameNameWithFlag(
      rawNewName,
      Object.keys(savedLayouts),
      oldName,
    );

    if (!newName || newName === oldName || newName === 'save') return;

    if (wasShortened) {
      setLayoutToast({
        visible: true,
        message: `Name was shortened to: "${newName}"`,
        type: 'success',
      });
    }

    if (savedLayouts[newName]) {
      setLayoutToast({
        visible: true,
        message: `Layout "${newName}" already exists.`,
        type: 'error',
      });
      return;
    }

    const originalLayout = savedLayouts[oldName];
    if (!originalLayout) return;

    setSavedLayouts((prev) => {
      const next = { ...prev };
      const layout = next[oldName];
      if (!layout) return prev;
      delete next[oldName];
      next[newName] = { ...layout, name: newName };
      if (auth?.user?.id) updateAndPersistLayouts(auth.user.id, () => next);
      return next;
    });

    if (auth?.user?.id) {
      const uId = auth.user.id;
      enqueueQueueOperation(uId, {
        type: 'rename',
        name: oldName,
        oldName,
        newName,
        payload: originalLayout,
      });
      processPendingQueue(uId);
    }
  };

  return {
    savedLayouts,
    handlePanelCountChange,
    handleDeleteLayout,
    handleRenameLayout,
  };
}
