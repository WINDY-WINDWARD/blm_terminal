import { createStore } from 'jotai';
import { describe, expect, it } from 'vitest';
import { showAiDisclaimerAtom } from '@/store/terminalStore';

describe('showAiDisclaimerAtom', () => {
  it('defaults to true so disclaimers stay on', () => {
    const store = createStore();
    expect(store.get(showAiDisclaimerAtom)).toBe(true);
  });

  it('stores the off value when the user hides disclaimers', () => {
    const store = createStore();
    store.set(showAiDisclaimerAtom, false);
    expect(store.get(showAiDisclaimerAtom)).toBe(false);
    expect(window.localStorage.getItem('terminal.showAiDisclaimer')).toBe('false');

    store.set(showAiDisclaimerAtom, true);
    expect(store.get(showAiDisclaimerAtom)).toBe(true);
    expect(window.localStorage.getItem('terminal.showAiDisclaimer')).toBe('true');
  });
});
