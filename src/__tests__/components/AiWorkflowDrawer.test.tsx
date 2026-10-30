import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/msw-server';
import { render, screen, fireEvent, waitFor } from '../utils/renderWithProviders';
import { AiWorkflowDrawer } from '@/components/widgets/AiWorkflowDrawer';
import type { Workflow, WorkflowRun } from '@/types/aiWorkflowTypes';

function makeWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: 1,
    name: 'Morning Briefing',
    description: 'Watchlist scan',
    prompt: 'Brief me on my watchlist.',
    schedule_type: 'weekdays',
    cron_expression: '0 10 * * 1-5',
    timezone: 'Asia/Kolkata',
    time_of_day: '10:00',
    days_of_week: null,
    symbols: ['RELIANCE'],
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

function makeRun(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: 11,
    workflow_id: 1,
    trigger: 'schedule',
    status: 'succeeded',
    skip_reason: null,
    scheduled_for: '2026-10-31T04:30:00',
    started_at: '2026-10-31T04:30:01',
    finished_at: '2026-10-31T04:30:20',
    duration_ms: 19000,
    session_id: 11,
    output_summary: 'Nifty opened flat, two watchlist names gapped up.',
    error: null,
    attempt: 0,
    is_read: false,
    is_silent: false,
    name_snapshot: 'Morning Briefing',
    created_at: '2026-10-31T04:30:00',
    ...overrides,
  };
}

type DrawerProps = React.ComponentProps<typeof AiWorkflowDrawer>;

function renderDrawer(overrides: Partial<DrawerProps> = {}) {
  const props: DrawerProps = {
    open: true,
    onClose: vi.fn(),
    workflows: [makeWorkflow()],
    runs: [],
    models: [],
    loading: false,
    runsLoading: false,
    onOpenRun: vi.fn(),
    ...overrides,
  };
  render(<AiWorkflowDrawer {...props} />);
  return props;
}

describe('AiWorkflowDrawer', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/py/ai/workflow-runs', () =>
        HttpResponse.json({ items: [makeRun()], total: 1, limit: 20, offset: 0, has_more: false }),
      ),
      http.post('/api/py/ai/workflow-runs/11/read', () => HttpResponse.json({ ok: true })),
      http.post('/api/py/ai/workflow-runs/read-all', () => HttpResponse.json({ ok: true })),
      http.patch('/api/py/ai/workflows/1', () => HttpResponse.json(makeWorkflow({ is_enabled: false }))),
      http.post('/api/py/ai/workflows/1/run', () => HttpResponse.json(makeRun({ id: 12 }))),
    );
  });

  it('renders nothing while closed', () => {
    renderDrawer({ open: false });
    expect(screen.queryByText('WORKFLOWS')).not.toBeInTheDocument();
  });

  it('lists scheduled workflows with their schedule label', async () => {
    renderDrawer();
    expect(screen.getByText('WORKFLOWS')).toBeInTheDocument();
    expect(screen.getByText('SCHEDULED (1)')).toBeInTheDocument();
    expect(screen.getByText('Morning Briefing')).toBeInTheDocument();
    expect(screen.getByText(/Weekdays at 10:00 IST/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('INBOX (1)')).toBeInTheDocument());
  });

  it('shows the empty state when no workflows exist', () => {
    renderDrawer({ workflows: [] });
    expect(screen.getByText('No workflows yet.')).toBeInTheDocument();
    expect(screen.getByText(/brief me on my watchlist every weekday at 10/)).toBeInTheDocument();
  });

  it('opens a run from the inbox and marks it read', async () => {
    const props = renderDrawer();
    let readCalled = false;
    server.use(
      http.post('/api/py/ai/workflow-runs/11/read', () => {
        readCalled = true;
        return HttpResponse.json({ ok: true });
      }),
    );

    fireEvent.click(await screen.findByText('INBOX (1)'));

    expect(await screen.findByText('Nifty opened flat, two watchlist names gapped up.')).toBeInTheDocument();
    expect(screen.getByText('schedule')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'OPEN' }));

    expect(props.onOpenRun).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }));
    await waitFor(() => expect(readCalled).toBe(true));
  });

  it('pauses a workflow from the row actions', async () => {
    let patchedBody: { is_enabled?: boolean } | null = null;
    server.use(
      http.patch('/api/py/ai/workflows/1', async ({ request }) => {
        patchedBody = (await request.json()) as { is_enabled?: boolean };
        return HttpResponse.json(makeWorkflow({ is_enabled: false }));
      }),
    );

    renderDrawer();
    fireEvent.click(screen.getByTitle('Pause'));

    await waitFor(() => expect(patchedBody).not.toBeNull());
    expect(patchedBody).toEqual(expect.objectContaining({ is_enabled: false }));
  });
});
