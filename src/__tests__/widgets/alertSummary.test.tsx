import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { render } from '@/__tests__/utils/renderWithProviders';
import { AlertSummaryModal } from '@/components/widgets/AlertSummaryModal';
import {
  alertSummariesCacheAtom,
  isAlertSummaryValid,
  getAlertsSnapshotFingerprint,
  getTodayLocalDateString,
  type AlertSummarySourceItem,
  type CachedAlertSummary,
} from '@/store/terminalStore';

const mockAlerts: AlertSummarySourceItem[] = [
  {
    id: 101,
    trigger_type: 'volume_surge',
    message: 'RELIANCE traded 2.4x average volume.',
    triggered_at: '2026-10-18T09:30:00Z',
    triggered_date: '2026-10-18',
  },
  {
    id: 102,
    trigger_type: 'rsi_overbought',
    message: 'RSI crossed 71.2 near resistance.',
    triggered_at: '2026-10-18T10:00:00Z',
    triggered_date: '2026-10-18',
  },
];

describe('Alert Summary Cache Logic', () => {
  const today = getTodayLocalDateString();
  const fingerprint = getAlertsSnapshotFingerprint(mockAlerts);

  const validCache: CachedAlertSummary = {
    symbol: 'RELIANCE',
    summary: 'Reliance shows strong volume breakout with near-term overbought conditions.',
    cachedAt: Date.now() - 60000,
    localDate: today,
    alertCount: 2,
    latestAlertFingerprint: fingerprint,
  };

  it('validates cache for the same day and exact alert fingerprint', () => {
    expect(isAlertSummaryValid(validCache, mockAlerts, today)).toBe(true);
  });

  it('expires cache if date has changed (next day)', () => {
    const yesterday = '2026-10-17';
    const staleCache: CachedAlertSummary = {
      ...validCache,
      localDate: yesterday,
    };
    expect(isAlertSummaryValid(staleCache, mockAlerts, today)).toBe(false);
  });

  it('expires cache if a new alert arrives (fingerprint changes)', () => {
    const newAlerts: AlertSummarySourceItem[] = [
      ...mockAlerts,
      {
        id: 103,
        trigger_type: 'block_deal',
        message: 'Block deal of 1M shares executed at market price.',
        triggered_at: '2026-10-18T11:00:00Z',
        triggered_date: '2026-10-18',
      },
    ];
    expect(isAlertSummaryValid(validCache, newAlerts, today)).toBe(false);
  });

  it('returns false for empty or missing cache/alerts', () => {
    expect(isAlertSummaryValid(null, mockAlerts, today)).toBe(false);
    expect(isAlertSummaryValid(undefined, mockAlerts, today)).toBe(false);
    expect(isAlertSummaryValid(validCache, [], today)).toBe(false);
  });

  it('generates consistent fingerprints for identical alerts', () => {
    const fp1 = getAlertsSnapshotFingerprint(mockAlerts);
    const fp2 = getAlertsSnapshotFingerprint([...mockAlerts]);
    expect(fp1).toBe(fp2);
    expect(fp1).toContain('102');
  });
});

describe('AlertSummaryModal Component', () => {
  const onClose = vi.fn();
  const today = getTodayLocalDateString();
  const fingerprint = getAlertsSnapshotFingerprint(mockAlerts);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders cached summary immediately without triggering API fetch', async () => {
    const cachedEntry: CachedAlertSummary = {
      symbol: 'RELIANCE',
      summary: 'Cached summary for Reliance indicating strong momentum.',
      cachedAt: 1729245600000,
      localDate: today,
      alertCount: 2,
      latestAlertFingerprint: fingerprint,
    };

    const fetchSpy = vi.spyOn(global, 'fetch');

    render(
      <AlertSummaryModal symbol="RELIANCE" alerts={mockAlerts} onClose={onClose} />,
      {
        wrapperProps: {
          initialAtomValues: [[alertSummariesCacheAtom, { RELIANCE: cachedEntry }]],
        },
      }
    );

    expect(screen.getByText('AI ALERT DIGEST: RELIANCE')).toBeInTheDocument();
    expect(screen.getByText('CACHED')).toBeInTheDocument();
    expect(
      screen.getByText('Cached summary for Reliance indicating strong momentum.')
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('calls API and renders newly generated summary when cache is missing', async () => {
    const mockApiResponse = {
      summary: 'Newly synthesized alert paragraph from OpenAI.',
      input_tokens: 80,
      output_tokens: 30,
      model: 'gpt-4o-mini',
    };

    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => mockApiResponse,
    } as Response);

    render(
      <AlertSummaryModal symbol="RELIANCE" alerts={mockAlerts} onClose={onClose} />,
      {
        wrapperProps: {
          initialAtomValues: [[alertSummariesCacheAtom, {}]],
        },
      }
    );

    await waitFor(() => {
      expect(
        screen.getByText('Newly synthesized alert paragraph from OpenAI.')
      ).toBeInTheDocument();
    });

    expect(screen.getByText('GENERATED')).toBeInTheDocument();
  });

  it('handles 503 unconfigured error with clear instructions', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'AI API key is not configured.' }),
    } as Response);

    render(
      <AlertSummaryModal symbol="RELIANCE" alerts={mockAlerts} onClose={onClose} />,
      {
        wrapperProps: {
          initialAtomValues: [[alertSummariesCacheAtom, {}]],
        },
      }
    );

    await waitFor(() => {
      expect(screen.getByText(/Please set an API key in Settings → AI/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('copies summary text to clipboard when COPY is clicked', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true,
    });

    const cachedEntry: CachedAlertSummary = {
      symbol: 'RELIANCE',
      summary: 'Summary to copy.',
      cachedAt: Date.now(),
      localDate: today,
      alertCount: 2,
      latestAlertFingerprint: fingerprint,
    };

    render(
      <AlertSummaryModal symbol="RELIANCE" alerts={mockAlerts} onClose={onClose} />,
      {
        wrapperProps: {
          initialAtomValues: [[alertSummariesCacheAtom, { RELIANCE: cachedEntry }]],
        },
      }
    );

    const copyBtn = screen.getByRole('button', { name: /COPY/i });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith('Summary to copy.');
    await waitFor(() => {
      expect(screen.getByText('COPIED')).toBeInTheDocument();
    });
  });

  it('closes modal on Escape key press or close button click', async () => {
    const cachedEntry: CachedAlertSummary = {
      symbol: 'RELIANCE',
      summary: 'Some summary.',
      cachedAt: Date.now(),
      localDate: today,
      alertCount: 2,
      latestAlertFingerprint: fingerprint,
    };

    render(
      <AlertSummaryModal symbol="RELIANCE" alerts={mockAlerts} onClose={onClose} />,
      {
        wrapperProps: {
          initialAtomValues: [[alertSummariesCacheAtom, { RELIANCE: cachedEntry }]],
        },
      }
    );

    const closeBtn = screen.getByRole('button', { name: 'Close' });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

