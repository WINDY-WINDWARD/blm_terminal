'use client';

import { useAtom } from 'jotai';
import { AiProvidersModal } from '@/components/modals/AiProvidersModal';
import { showAiProvidersModalAtom } from '@/store/terminalStore';

export function AiProvidersModalHost() {
  const [isOpen, setIsOpen] = useAtom(showAiProvidersModalAtom);

  return <AiProvidersModal isOpen={isOpen} onClose={() => setIsOpen(false)} />;
}
