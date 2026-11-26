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

const hydration = vi.hoisted(() => ({ value: true }));

vi.mock('@/lib/useHydrated', () => ({
  useHydrated: () => hydration.value,
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
    hydration.value = true;
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
    fireEvent.click(screen.getByRole('tab', { name: 'ACTIVE' }));

    expect(screen.getByText('NO ACTIVE PICKS')).toBeInTheDocument();
  });

  it('hides the disclaimer and banner until the client has hydrated', async () => {
    hydration.value = false;
    render(<AiPicksWidget />);

    expect(screen.getByText('LOADING AI PICKS...')).toBeInTheDocument();

    await screen.findByTestId('pick-ticket-1');

    expect(screen.queryByText(/Disclaimer/)).not.toBeInTheDocument();
    expect(screen.queryByText('AI can make mistakes. Verify before taking action.')).not.toBeInTheDocument();
    expect(screen.getByText('Entry')).toBeInTheDocument();
  });

  it('shows the disclaimer and banner once hydrated', async () => {
    render(<AiPicksWidget />);

    await screen.findByTestId('pick-ticket-1');

    expect(screen.getByText(/Disclaimer/)).toBeInTheDocument();
    expect(screen.getByText('AI can make mistakes. Verify before taking action.')).toBeInTheDocument();
  });
});
