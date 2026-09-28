/**
 * BLM Script Lab — Accept/Discard card survival stash.
 *
 * Cards arrive as SSE-only events and are NOT in the persisted chat history
 * (tool_calls_json stores tool names only), so a card attached to an
 * in-flight turn is lost on reload / session switch / remount. This module
 * stashes cards in localStorage keyed by session + script + rev so
 * loadSession can re-attach them, and persists accepted/dismissed stamps.
 */

export interface StashedCard {
  action: 'created' | 'revised';
  script_id: number;
  name: string;
  rev_no: number;
  accepted?: boolean;
  dismissed?: boolean;
  ts: number;
}

export type SessionKey = number | null;

const STORAGE_KEY = 'blm.scriptCards';

type StashShape = Record<string, StashedCard[]>;

function readStash(): StashShape {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as StashShape;
    }
    return {};
  } catch {
    return {};
  }
}

function writeStash(stash: StashShape): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stash));
  } catch {
    /* quota / privacy mode — cards stay session-only */
  }
}

function sessionKeyOf(sessionId: SessionKey): string {
  return sessionId === null ? 'new' : String(sessionId);
}

function cardKey(card: Pick<StashedCard, 'script_id' | 'rev_no'>): string {
  return `${card.script_id}:${card.rev_no}`;
}

/** Upsert a card under its session key (idempotent on script+rev). */
export function stashCard(sessionId: SessionKey, card: StashedCard): void {
  const stash = readStash();
  const key = sessionKeyOf(sessionId);
  const list = Array.isArray(stash[key]) ? stash[key] : [];
  const idx = list.findIndex((c) => cardKey(c) === cardKey(card));
  if (idx >= 0) list[idx] = { ...list[idx], ...card };
  else list.push(card);
  stash[key] = list;
  writeStash(stash);
}

/** All stashed cards for a session, oldest first. */
export function getStashedCards(sessionId: SessionKey): StashedCard[] {
  const stash = readStash();
  const list = stash[sessionKeyOf(sessionId)];
  if (!Array.isArray(list)) return [];
  return [...list].sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0));
}

/** Stamp accepted/dismissed on a stashed card (no-op if absent). */
export function stampStashedCard(
  sessionId: SessionKey,
  card: Pick<StashedCard, 'script_id' | 'rev_no'>,
  patch: Pick<StashedCard, 'accepted' | 'dismissed'>,
): void {
  const stash = readStash();
  const key = sessionKeyOf(sessionId);
  const list = stash[key];
  if (!Array.isArray(list)) return;
  const idx = list.findIndex((c) => cardKey(c) === cardKey(card));
  if (idx < 0) return;
  list[idx] = { ...list[idx], ...patch };
  writeStash(stash);
}

/** Move stashed cards when a scratch session is assigned a real id. */
export function migrateStash(from: SessionKey, to: SessionKey): void {
  if (from === to) return;
  const stash = readStash();
  const fromKey = sessionKeyOf(from);
  const toKey = sessionKeyOf(to);
  const moving = stash[fromKey];
  if (!Array.isArray(moving) || moving.length === 0) return;
  const existing = Array.isArray(stash[toKey]) ? stash[toKey] : [];
  for (const card of moving) {
    const idx = existing.findIndex((c) => cardKey(c) === cardKey(card));
    if (idx >= 0) existing[idx] = { ...existing[idx], ...card };
    else existing.push(card);
  }
  stash[toKey] = existing;
  delete stash[fromKey];
  writeStash(stash);
}

/** Drop all stashed cards for a deleted session. */
export function pruneStashedSession(sessionId: SessionKey): void {
  const stash = readStash();
  delete stash[sessionKeyOf(sessionId)];
  writeStash(stash);
}

/** Drop all stashed cards for a deleted script, across every session. */
export function pruneStashedScript(scriptId: number): void {
  const stash = readStash();
  let touched = false;
  for (const key of Object.keys(stash)) {
    const list = stash[key];
    if (!Array.isArray(list)) continue;
    const kept = list.filter((c) => c.script_id !== scriptId);
    if (kept.length !== list.length) {
      stash[key] = kept;
      touched = true;
    }
  }
  if (touched) writeStash(stash);
}

const SCRIPT_MUTATION_TOOLS = new Set(['create_script', 'revise_script']);

/** Minimal message shape needed for card re-attachment. */
export interface CardCarryingMessage<CardT> {
  role: string;
  toolCalls?: string[];
  card?: CardT;
}

/**
 * Re-attach stashed active (neither accepted nor dismissed) cards onto
 * reloaded turns. Turns that called a script-mutation tool and carry no card
 * yet receive stashed cards oldest-first. Pure — safe to unit test.
 */
export function reattachStashedCards<MessageT extends CardCarryingMessage<StashedCard>>(
  messages: MessageT[],
  stashed: StashedCard[],
): MessageT[] {
  const pending = stashed.filter((c) => !c.accepted && !c.dismissed);
  if (pending.length === 0) return messages;
  let cursor = 0;
  return messages.map((m) => {
    if (cursor >= pending.length) return m;
    if (m.role !== 'assistant' || m.card) return m;
    const calls = m.toolCalls ?? [];
    if (!calls.some((t) => SCRIPT_MUTATION_TOOLS.has(t))) return m;
    const card = pending[cursor++];
    const { ts: _ts, ...rest } = card;
    return { ...m, card: rest };
  });
}
