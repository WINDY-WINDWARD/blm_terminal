import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const requestWidgetTour = vi.fn();

vi.mock('@/components/widgetTour/WidgetTourController', () => ({
  requestWidgetTour: (request: { panelId: string; command: string; mode: string }) =>
    requestWidgetTour(request),
}));

import {
  findPopoutTarget,
  POPOUT_ACK_KEY,
  POPOUT_PRESENCE_KEY,
  POPOUT_REQUEST_KEY,
  requestPopoutTour,
  respondToPopoutRequest,
} from '@/lib/widgetTours/popoutChannel';

function writePresence(entries: Record<string, { panelId: string; command: string; ts: number }>) {
  window.localStorage.setItem(POPOUT_PRESENCE_KEY, JSON.stringify(entries));
}

function readRequest(): { id: string; command: string; target: string } {
  return JSON.parse(window.localStorage.getItem(POPOUT_REQUEST_KEY) ?? '{}');
}

function dispatchAck(id: string, command: string) {
  window.dispatchEvent(
    new StorageEvent('storage', {
      key: POPOUT_ACK_KEY,
      newValue: JSON.stringify({ id, command }),
    }),
  );
}

describe('findPopoutTarget', () => {
  beforeEach(() => window.localStorage.clear());

  it('returns the newest live instance for the command', () => {
    writePresence({
      old: { panelId: 'popout_1', command: 'CHART', ts: Date.now() - 60_000 },
      newer: { panelId: 'popout_2', command: 'CHART', ts: Date.now() },
      other: { panelId: 'popout_3', command: 'ORDER', ts: Date.now() },
    });

    expect(findPopoutTarget('CHART', window.localStorage)).toBe('newer');
  });

  it('ignores entries older than the 12 hour window and malformed payloads', () => {
    const staleTs = Date.now() - 13 * 60 * 60 * 1000;
    writePresence({ stale: { panelId: 'p', command: 'CHART', ts: staleTs } });
    expect(findPopoutTarget('CHART', window.localStorage)).toBeNull();

    window.localStorage.setItem(POPOUT_PRESENCE_KEY, JSON.stringify({ broken: { command: 1 } }));
    expect(findPopoutTarget('CHART', window.localStorage)).toBeNull();

    window.localStorage.setItem(POPOUT_PRESENCE_KEY, 'not json');
    expect(findPopoutTarget('CHART', window.localStorage)).toBeNull();
  });
});

describe('requestPopoutTour', () => {
  beforeEach(() => {
    window.localStorage.clear();
    requestWidgetTour.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('resolves false without writing a request when no popout is registered', async () => {
    await expect(requestPopoutTour('CHART')).resolves.toBe(false);
    expect(window.localStorage.getItem(POPOUT_REQUEST_KEY)).toBeNull();
  });

  it('targets one instance and resolves true only after its matching ack', async () => {
    writePresence({
      a: { panelId: 'popout_1', command: 'CHART', ts: Date.now() - 10_000 },
      b: { panelId: 'popout_2', command: 'CHART', ts: Date.now() },
    });

    const pending = requestPopoutTour('CHART');
    const request = readRequest();
    expect(request.command).toBe('CHART');
    expect(request.target).toBe('b');

    dispatchAck(request.id, 'ORDER');
    dispatchAck('unrelated', 'CHART');

    const resolvedEarly = await Promise.race([
      pending.then(() => 'resolved' as const),
      Promise.resolve('pending' as const),
    ]);
    expect(resolvedEarly).toBe('pending');

    dispatchAck(request.id, 'CHART');
    await expect(pending).resolves.toBe(true);
  });

  it('resolves false when the ack never arrives', async () => {
    vi.useFakeTimers();
    writePresence({ a: { panelId: 'popout_1', command: 'CHART', ts: Date.now() } });

    const pending = requestPopoutTour('CHART');
    await vi.advanceTimersByTimeAsync(800);
    await expect(pending).resolves.toBe(false);
  });
});

describe('respondToPopoutRequest', () => {
  beforeEach(() => {
    window.localStorage.clear();
    requestWidgetTour.mockClear();
  });

  it('starts the tour and acknowledges only the targeted instance', () => {
    const raw = JSON.stringify({ id: 'req_1', command: 'CHART', target: 'b' });

    expect(respondToPopoutRequest(window.localStorage, 'a', 'popout_1', 'CHART', raw)).toBe(false);
    expect(requestWidgetTour).not.toHaveBeenCalled();

    expect(respondToPopoutRequest(window.localStorage, 'b', 'popout_2', 'CHART', raw)).toBe(true);
    expect(requestWidgetTour).toHaveBeenCalledWith({
      panelId: 'popout_2',
      command: 'CHART',
      mode: 'replay',
    });
    expect(JSON.parse(window.localStorage.getItem(POPOUT_ACK_KEY) ?? '{}')).toEqual({
      id: 'req_1',
      command: 'CHART',
    });
  });

  it('ignores legacy payloads with no target, wrong commands, and malformed input', () => {
    const legacy = JSON.stringify({ id: 'req_2', command: 'CHART' });
    expect(respondToPopoutRequest(window.localStorage, 'a', 'p', 'CHART', legacy)).toBe(false);

    const wrong = JSON.stringify({ id: 'req_3', command: 'ORDER', target: 'a' });
    expect(respondToPopoutRequest(window.localStorage, 'a', 'p', 'CHART', wrong)).toBe(false);

    expect(respondToPopoutRequest(window.localStorage, 'a', 'p', 'CHART', '[]')).toBe(false);
    expect(respondToPopoutRequest(window.localStorage, 'a', 'p', 'CHART', null)).toBe(false);

    expect(requestWidgetTour).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(POPOUT_ACK_KEY)).toBeNull();
  });
});
