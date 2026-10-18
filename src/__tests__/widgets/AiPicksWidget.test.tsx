import { fireEvent, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AiPicksWidget } from '@/components/widgets/AiPicksWidget';
import { server } from '../mocks/msw-server';
import { render } from '../utils/renderWithProviders';

vi.mock('@/lib/marketWs', () => ({
  marketWsService: {
    requestSymbolData: vi.fn(),
    onSymbolData: vi.fn(() => () => {}),
  },
}));

const picks = [{
  id: 1,
  symbol: 'SUNFLAG',
  direction: 'LONG',
  entry_price: 432,
  take_profit: 475,
  stop_loss: 415,
  status: 'NEW',
  notes: [],
  created_at: '2026-10-18T17:20:00Z',
  updated_at: '2026-10-18T17:20:00Z',
  status_updated_at: '2026-10-18T17:20:00Z',
}];

describe('AiPicksWidget', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/py/ai/picks', () => HttpResponse.json(picks)),
      http.get('/api/py/jobs/job.ai_picks_morning', () => HttpResponse.json({ status: 'idle' })),
      http.get('/api/py/jobs/job.ai_picks_evening', () => HttpResponse.json({ status: 'idle' })),
    );
  });

  it('presents each pick as a readable trade ticket with grouped levels', async () => {
    render(<AiPicksWidget />);

    const ticket = await screen.findByTestId('pick-ticket-1');
    expect(ticket).toHaveClass('rounded-md');
    expect(screen.getByTestId('pick-ticket-levels-1')).toHaveClass('grid-cols-3');
    expect(screen.getByText('Entry')).toBeInTheDocument();
    expect(screen.getByText('432')).toBeInTheDocument();
    expect(screen.getByText('475')).toBeInTheDocument();
    expect(screen.getByText('415')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /details/i })).toBeInTheDocument();
  });

  it('uses a single-column ticket header on narrow panels', async () => {
    render(<AiPicksWidget />);

    const ticket = await screen.findByTestId('pick-ticket-1');
    expect(ticket).toHaveClass('grid-cols-1');
    expect(screen.getByTestId('pick-ticket-levels-1')).toHaveClass('grid-cols-3');
  });

  it('keeps row actions and status tabs available', async () => {
    render(<AiPicksWidget />);

    await screen.findByTestId('pick-ticket-1');
    fireEvent.click(screen.getByRole('button', { name: 'ACTIVE' }));

    expect(screen.getByText('NO ACTIVE PICKS')).toBeInTheDocument();
  });
});
