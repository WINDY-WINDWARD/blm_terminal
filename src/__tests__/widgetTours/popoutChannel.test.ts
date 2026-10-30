import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  POPOUT_REQUEST_KEY,
  POPOUT_ACK_KEY,
  POPOUT_PRESENCE_KEY,
  requestPopoutTour,
} from '@/lib/widgetTours/popoutChannel';

describe('popoutChannel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('exports expected storage key constants', () => {
    expect(POPOUT_REQUEST_KEY).toBe('__blm_widget_tour_request');
    expect(POPOUT_ACK_KEY).toBe('__blm_widget_tour_ack');
    expect(POPOUT_PRESENCE_KEY).toBe('__blm_widget_tour_windows');
  });

  it('requestPopoutTour resolves false on timeout with a stubbed localStorage and no ack', async () => {
    const memoryStore: Record<string, string> = {};
    const mockStorage: Storage = {
      getItem: vi.fn((key: string) => memoryStore[key] ?? null),
      setItem: vi.fn((key: string, value: string) => {
        memoryStore[key] = value;
      }),
      removeItem: vi.fn((key: string) => {
        delete memoryStore[key];
      }),
      clear: vi.fn(() => {
        Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);
      }),
      key: vi.fn((idx: number) => Object.keys(memoryStore)[idx] ?? null),
      length: 0,
    };

    vi.stubGlobal('localStorage', mockStorage);

    // A live popout of CHART is registered, so the request is broadcast.
    memoryStore[POPOUT_PRESENCE_KEY] = JSON.stringify({
      registration: { panelId: 'panel-1', command: 'CHART', ts: Date.now() },
    });

    const promise = requestPopoutTour('CHART');

    expect(mockStorage.setItem).toHaveBeenCalledWith(
      POPOUT_REQUEST_KEY,
      expect.stringContaining('"command":"CHART"')
    );

    // Fast-forward past the 700ms timeout
    vi.advanceTimersByTime(750);

    const result = await promise;
    expect(result).toBe(false);
  });

  it('requestPopoutTour skips the wait when no popout is registered', async () => {
    const memoryStore: Record<string, string> = {};
    const mockStorage: Storage = {
      getItem: vi.fn((key: string) => memoryStore[key] ?? null),
      setItem: vi.fn((key: string, value: string) => {
        memoryStore[key] = value;
      }),
      removeItem: vi.fn((key: string) => {
        delete memoryStore[key];
      }),
      clear: vi.fn(() => {
        Object.keys(memoryStore).forEach((k) => delete memoryStore[k]);
      }),
      key: vi.fn((idx: number) => Object.keys(memoryStore)[idx] ?? null),
      length: 0,
    };

    vi.stubGlobal('localStorage', mockStorage);

    const result = await requestPopoutTour('CHART');

    expect(result).toBe(false);
    expect(mockStorage.setItem).not.toHaveBeenCalled();
  });

  it('source check finds the responder call in the popout page', () => {
    const popoutPagePath = path.resolve(
      process.cwd(),
      'src/app/widget/[widgetType]/page.tsx'
    );
    const content = fs.readFileSync(popoutPagePath, 'utf8');

    expect(content).toContain('usePopoutTourResponder(panelId, widgetTitle)');
  });

  it('source check finds the popout banner in DocsWidget', () => {
    const docsWidgetPath = path.resolve(
      process.cwd(),
      'src/components/widgets/DocsWidget.tsx'
    );
    const content = fs.readFileSync(docsWidgetPath, 'utf8');

    expect(content).toContain('TOUR STARTED IN THE {startedInPopoutCmd} POPOUT');
    expect(content).toContain('OPEN {missingPanelCmd} IN A PANEL OR POPOUT TO REPLAY THIS TOUR');
  });
});
