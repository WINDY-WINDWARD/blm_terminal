import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { WatchAlertsModal } from '@/components/widgets/WatchWidget';
import { server } from '../mocks/msw-server';
import { render } from '../utils/renderWithProviders';

const ALERTS = [
  {
    id: 1,
    symbol: 'HAPSTMNDS',
    trigger_type: 'BB_UPPER_BREAK',
    message: 'HAPSTMNDS close 335.9 broke above BB upper 332.38',
    triggered_at: '2026-10-19T01:22:23',
    triggered_date: '2026-10-19',
    watchlist_id: 1,
  },
  {
    id: 2,
    symbol: 'HAPSTMNDS',
    trigger_type: 'NEAR_52W_LOW',
    message: 'HAPSTMNDS within 3.0% of 52W low (+1.7%)',
    triggered_at: '2026-10-19T01:22:23',
    triggered_date: '2026-10-19',
    watchlist_id: 1,
  },
];

describe('WatchAlertsModal header', () => {
  it('keeps every action on a single line in a dedicated action row', async () => {
    server.use(
      http.get('/api/py/notifications', () => HttpResponse.json(ALERTS)),
    );

    render(
      <WatchAlertsModal
        symbol="HAPSTMNDS"
        watchlistId={1}
        onClose={vi.fn()}
        onAlertDismissed={vi.fn()}
      />,
    );

    expect(await screen.findByText('ALERTS: HAPSTMNDS')).toBeInTheDocument();
    expect(await screen.findByText('2 UNREAD')).toBeInTheDocument();

    const actions = screen.getByTestId('watch-alerts-actions');
    const buttons = within(actions).getAllByRole('button');
    expect(buttons.map((button) => button.textContent)).toEqual([
      '⚡Load Chart',
      '🏢Company',
      '🤖AI Summarize',
      'Dismiss All',
    ]);
    for (const button of buttons) {
      expect(button).toHaveClass('shrink-0', 'whitespace-nowrap');
    }
    expect(within(actions).getByRole('button', { name: /load chart/i })).toHaveClass('flex');
  });
});
