import { atom } from 'jotai';

export const activeCommandAtom = atom<string>('');

export const activePanelsAtom = atom<{ [id: string]: string }>({
    'panel-1': 'CHART',
    'panel-2': 'WATCH',
    'panel-3': 'TOP',
    'panel-4': 'POS'
});

export const focusedPanelAtom = atom<string>('panel-1');
