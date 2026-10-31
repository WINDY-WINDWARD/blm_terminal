import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/msw-server';
import { render, screen, fireEvent } from '../utils/renderWithProviders';
import { AiWorkflowModal } from '@/components/widgets/AiWorkflowModal';
import type { Workflow } from '@/types/aiWorkflowTypes';

function makeWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: 1,
    name: 'Morning Briefing',
    description: 'Watchlist scan',
    prompt: 'Brief me on my watchlist every weekday.',
    schedule_type: 'weekdays',
    cron_expression: '0 10 * * 1-5',
    timezone: 'Asia/Kolkata',
    time_of_day: '10:00',
    days_of_week: null,
    symbols: [],
    watchlist_id: null,
    model: null,
    persona: null,
    mode: 'research',
    allow_write_tools: false,
    is_enabled: true,
    catch_up_enabled: true,
    catch_up_window_hours: 12,
    next_run_at: '2026-11-02T04:30:00',
    last_run_at: null,
    last_success_at: null,
    schedule_label: 'Weekdays at 10:00 IST',
    created_at: '2026-10-31T00:00:00',
    ...overrides,
  };
}

type ModalProps = React.ComponentProps<typeof AiWorkflowModal>;

function renderModal(overrides: Partial<ModalProps> = {}) {
  const props: ModalProps = {
    open: true,
    workflow: null,
    models: [],
    onClose: vi.fn(),
    onAskCopilot: vi.fn(),
    onSaved: vi.fn(),
    ...overrides,
  };
  render(<AiWorkflowModal {...props} />);
  return props;
}

describe('AiWorkflowModal', () => {
  beforeEach(() => {
    server.use(
      http.post('/api/py/ai/workflows/preview', () =>
        HttpResponse.json({
          cron_expression: '0 10 * * 1-5',
          schedule_label: 'Weekdays at 10:00 IST',
          next_runs: ['2026-11-02T04:30:00', '2026-11-03T04:30:00'],
        }),
      ),
    );
  });

  it('renders nothing while closed', () => {
    renderModal({ open: false });
    expect(screen.queryByText('NEW WORKFLOW')).not.toBeInTheDocument();
  });

  it('opens on the copilot tab and sends the description', () => {
    const props = renderModal();

    expect(screen.getByText('ASK COPILOT')).toBeInTheDocument();
    expect(screen.getByText('SET UP MANUALLY')).toBeInTheDocument();

    const create = screen.getByRole('button', { name: 'CREATE WITH AI' });
    expect(create).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText(/Brief my watchlist/), {
      target: { value: 'Brief my watchlist every weekday at 10' },
    });
    expect(create).toBeEnabled();

    fireEvent.click(create);
    expect(props.onAskCopilot).toHaveBeenCalledWith('Brief my watchlist every weekday at 10');
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it('enables SAVE only when name and prompt are filled', () => {
    renderModal();
    fireEvent.click(screen.getByText('SET UP MANUALLY'));

    const save = screen.getByRole('button', { name: 'SAVE' });
    expect(save).toBeDisabled();
    expect(screen.getByText('Add a name and prompt to save')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Opening Bell' } });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Summarise pre-open gaps for my watchlist.' },
    });
    expect(save).toBeEnabled();
    expect(screen.queryByText('Add a name and prompt to save')).not.toBeInTheDocument();
  });

  it('hides the tabs and shows the edit header when editing', () => {
    renderModal({ workflow: makeWorkflow() });

    expect(screen.getByText('EDIT WORKFLOW')).toBeInTheDocument();
    expect(screen.queryByText('ASK COPILOT')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Morning Briefing');
    expect(screen.getByRole('button', { name: 'SAVE' })).toBeEnabled();
  });

  it('closes on Escape', () => {
    const props = renderModal();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });
});
