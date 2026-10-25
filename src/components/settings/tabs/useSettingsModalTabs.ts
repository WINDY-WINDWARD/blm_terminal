'use client';

import { useAtom, useSetAtom } from 'jotai';
import {
  showSettingsModalAtom,
  showAiProvidersModalAtom,
  settingsModalTabAtom,
  type SettingsTabId,
} from '@/store/terminalStore';

export function useSettingsModalTabs({
  controlledIsOpen,
  controlledOnClose,
  initialTab,
}: {
  controlledIsOpen?: boolean;
  controlledOnClose?: () => void;
  initialTab?: SettingsTabId;
}) {
  const [globalIsOpen, setGlobalIsOpen] = useAtom(showSettingsModalAtom);
  const setShowAiProvidersModal = useSetAtom(showAiProvidersModalAtom);
  const [globalTab, setGlobalTab] = useAtom(settingsModalTabAtom);

  const isOpen = controlledIsOpen !== undefined ? controlledIsOpen : globalIsOpen;
  const handleClose = () => {
    if (controlledOnClose) {
      controlledOnClose();
    } else {
      setGlobalIsOpen(false);
    }
  };

  const openManageProviders = () => {
    setGlobalIsOpen(false);
    controlledOnClose?.();
    setShowAiProvidersModal(true);
  };

  return {
    isOpen,
    handleClose,
    globalTab,
    setGlobalTab,
    openManageProviders,
  };
}
