import { beforeEach, describe, expect, it } from 'vitest';
import {
  getStashedCards,
  migrateStash,
  pruneStashedSession,
  reattachStashedCards,
  stampStashedCard,
  stashCard,
  type StashedCard,
} from './cardStash';

function installStorageStub(): void {
  const store = new Map<string, string>();
  (globalThis as Record<string, unknown>).window = {
    localStorage: {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => {
        store.set(k, v);
      },
      removeItem: (k: string) => {
        store.delete(k);
      },
    },
  };
}

const card = (over: Partial<StashedCard> = {}): StashedCard => ({
  action: 'created',
  script_id: 7,
  name: 'SMA Cross',
  rev_no: 1,
  ts: 1000,
  ...over,
});

describe('cardStash', () => {
  beforeEach(() => {
    installStorageStub();
  });

  it('round-trips a stashed card per session', () => {
    expect(getStashedCards(77)).toEqual([]);
    stashCard(77, card());
    const got = getStashedCards(77);
    expect(got).toHaveLength(1);
    expect(got[0].script_id).toBe(7);
    // Other sessions are isolated.
    expect(getStashedCards(78)).toEqual([]);
  });

  it('upserts on script+rev (no duplicates)', () => {
    stashCard(77, card({ ts: 1 }));
    stashCard(77, card({ ts: 2, name: 'Renamed' }));
    const got = getStashedCards(77);
    expect(got).toHaveLength(1);
    expect(got[0].name).toBe('Renamed');
  });

  it('stamps accepted/dismissed through', () => {
    stashCard(77, card());
    stampStashedCard(77, { script_id: 7, rev_no: 1 }, { dismissed: true });
    expect(getStashedCards(77)[0].dismissed).toBe(true);
    // Unknown card is a no-op.
    stampStashedCard(77, { script_id: 9, rev_no: 1 }, { accepted: true });
    expect(getStashedCards(77)).toHaveLength(1);
  });

  it('migrates scratch-session stash to the assigned id', () => {
    stashCard(null, card());
    migrateStash(null, 77);
    expect(getStashedCards(null)).toEqual([]);
    expect(getStashedCards(77)).toHaveLength(1);
  });

  it('prunes a deleted session', () => {
    stashCard(77, card());
    pruneStashedSession(77);
    expect(getStashedCards(77)).toEqual([]);
  });
});

interface Msg {
  role: string;
  content: string;
  toolCalls?: string[];
  card?: StashedCard;
}

describe('reattachStashedCards', () => {
  it('attaches a pending card to the mutation turn', () => {
    const messages: Msg[] = [
      { role: 'user', content: 'make me an sma' },
      { role: 'assistant', content: 'done', toolCalls: ['create_script'] },
    ];
    const out = reattachStashedCards(messages, [card()]);
    expect(out[1].card?.script_id).toBe(7);
    expect(out[1].card).not.toHaveProperty('ts');
  });

  it('skips turns without mutation calls, accepted/dismissed, and filled turns', () => {
    const messages: Msg[] = [
      { role: 'assistant', content: 'chatter', toolCalls: ['list_scripts'] },
      {
        role: 'assistant',
        content: 'old',
        toolCalls: ['create_script'],
        card: { action: 'created', script_id: 1, name: 'Old', rev_no: 1, ts: 5 },
      },
      { role: 'assistant', content: 'new', toolCalls: ['revise_script'] },
    ];
    const stashed = [
      card({ script_id: 7, rev_no: 1, accepted: true }),
      card({ script_id: 8, rev_no: 2, dismissed: true }),
      card({ script_id: 9, rev_no: 3 }),
    ];
    const out = reattachStashedCards(messages, stashed);
    expect(out[0].card).toBeUndefined();
    expect(out[1].card?.script_id).toBe(1);
    expect(out[2].card?.script_id).toBe(9);
  });

  it('returns messages untouched when nothing is pending', () => {
    const messages: Msg[] = [{ role: 'assistant', content: 'hi' }];
    expect(reattachStashedCards(messages, [])).toBe(messages);
  });
});
