'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import type {
  Paginated,
  Workflow,
  WorkflowCreateInput,
  WorkflowPreview,
  WorkflowPreviewInput,
  WorkflowRun,
  WorkflowSummary,
  WorkflowUpdateInput,
} from '@/types/aiWorkflowTypes';

async function parseError(res: Response, fallback: string): Promise<Error> {
  try {
    const data = (await res.json()) as { detail?: unknown; error?: unknown };
    const detail =
      typeof data?.detail === 'string'
        ? data.detail
        : typeof data?.error === 'string'
          ? data.error
          : fallback;
    return new Error(detail);
  } catch {
    return new Error(fallback);
  }
}

async function invalidateWorkflowQueries(queryClient: QueryClient): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['ai', 'workflows'] }),
    queryClient.invalidateQueries({ queryKey: ['ai', 'workflow-runs'] }),
  ]);
}

export interface UseWorkflowListOptions {
  enabled?: boolean;
  limit?: number;
  offset?: number;
}

export function useWorkflowList(options: UseWorkflowListOptions = {}) {
  const { enabled, limit = 50, offset = 0 } = options;

  return useQuery<Paginated<Workflow>>({
    queryKey: ['ai', 'workflows', 'list', { enabled, limit, offset }],
    queryFn: async (): Promise<Paginated<Workflow>> => {
      const params = new URLSearchParams();
      if (enabled !== undefined) {
        params.set('enabled', String(enabled));
      }
      params.set('limit', String(limit));
      params.set('offset', String(offset));

      const res = await fetch(`/api/py/ai/workflows?${params.toString()}`);
      if (!res.ok) {
        throw await parseError(res, `Failed to load workflows (HTTP ${res.status})`);
      }
      return (await res.json()) as Paginated<Workflow>;
    },
    staleTime: 10_000,
  });
}

export interface UseWorkflowSummaryOptions {
  active?: boolean;
}

export function useWorkflowSummary(options: UseWorkflowSummaryOptions = {}) {
  const { active = false } = options;

  return useQuery<WorkflowSummary>({
    queryKey: ['ai', 'workflows', 'summary'],
    queryFn: async (): Promise<WorkflowSummary> => {
      const res = await fetch('/api/py/ai/workflows/summary');
      if (!res.ok) {
        throw await parseError(res, `Failed to load workflow summary (HTTP ${res.status})`);
      }
      return (await res.json()) as WorkflowSummary;
    },
    refetchInterval: active ? 15_000 : 60_000,
    refetchOnWindowFocus: true,
  });
}

export interface UseWorkflowRunsOptions {
  workflowId?: number;
  unread?: boolean;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}

export function useWorkflowRuns(options: UseWorkflowRunsOptions = {}) {
  const { workflowId, unread, limit = 20, offset = 0, enabled = true } = options;

  return useQuery<Paginated<WorkflowRun>>({
    queryKey: ['ai', 'workflow-runs', 'list', { workflowId, unread, limit, offset }],
    enabled,
    queryFn: async (): Promise<Paginated<WorkflowRun>> => {
      const params = new URLSearchParams();
      if (workflowId !== undefined) {
        params.set('workflow_id', String(workflowId));
      }
      if (unread !== undefined) {
        params.set('unread', String(unread));
      }
      params.set('limit', String(limit));
      params.set('offset', String(offset));

      const res = await fetch(`/api/py/ai/workflow-runs?${params.toString()}`);
      if (!res.ok) {
        throw await parseError(res, `Failed to load workflow runs (HTTP ${res.status})`);
      }
      return (await res.json()) as Paginated<WorkflowRun>;
    },
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      const isRunning = items?.some(
        (run) => run.status === 'queued' || run.status === 'running',
      );
      return isRunning ? 15_000 : false;
    },
  });
}

export function useWorkflowPreview() {
  return useMutation<WorkflowPreview, Error, WorkflowPreviewInput>({
    mutationFn: async (payload: WorkflowPreviewInput): Promise<WorkflowPreview> => {
      const res = await fetch('/api/py/ai/workflows/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to preview workflow schedule (HTTP ${res.status})`);
      }
      return (await res.json()) as WorkflowPreview;
    },
  });
}

export function useCreateWorkflow() {
  const queryClient = useQueryClient();

  return useMutation<Workflow, Error, WorkflowCreateInput>({
    mutationFn: async (payload: WorkflowCreateInput): Promise<Workflow> => {
      const res = await fetch('/api/py/ai/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to create workflow (HTTP ${res.status})`);
      }
      return (await res.json()) as Workflow;
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}

export interface UpdateWorkflowArgs {
  id: number;
  data: WorkflowUpdateInput;
}

export function useUpdateWorkflow() {
  const queryClient = useQueryClient();

  return useMutation<Workflow, Error, UpdateWorkflowArgs>({
    mutationFn: async ({ id, data }: UpdateWorkflowArgs): Promise<Workflow> => {
      const res = await fetch(`/api/py/ai/workflows/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to update workflow (HTTP ${res.status})`);
      }
      return (await res.json()) as Workflow;
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}

export function useDeleteWorkflow() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, number>({
    mutationFn: async (id: number): Promise<void> => {
      const res = await fetch(`/api/py/ai/workflows/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to delete workflow (HTTP ${res.status})`);
      }
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}

export function useRunWorkflowNow() {
  const queryClient = useQueryClient();

  return useMutation<WorkflowRun, Error, number>({
    mutationFn: async (id: number): Promise<WorkflowRun> => {
      const res = await fetch(`/api/py/ai/workflows/${id}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (res.status === 409) {
        throw new Error('A run is already in progress');
      }
      if (!res.ok) {
        throw await parseError(res, `Failed to run workflow (HTTP ${res.status})`);
      }
      return (await res.json()) as WorkflowRun;
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}

export interface ToggleWorkflowArgs {
  id: number;
  is_enabled: boolean;
}

export function useToggleWorkflow() {
  const queryClient = useQueryClient();

  return useMutation<Workflow, Error, ToggleWorkflowArgs>({
    mutationFn: async ({ id, is_enabled }: ToggleWorkflowArgs): Promise<Workflow> => {
      const res = await fetch(`/api/py/ai/workflows/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enabled }),
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to toggle workflow (HTTP ${res.status})`);
      }
      return (await res.json()) as Workflow;
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}

export function useMarkRunRead() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, number>({
    mutationFn: async (id: number): Promise<void> => {
      const res = await fetch(`/api/py/ai/workflow-runs/${id}/read`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to mark run as read (HTTP ${res.status})`);
      }
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}

export function useMarkAllRunsRead() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, void>({
    mutationFn: async (): Promise<void> => {
      const res = await fetch('/api/py/ai/workflow-runs/read-all', {
        method: 'POST',
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to mark all runs as read (HTTP ${res.status})`);
      }
    },
    onSuccess: async () => {
      await invalidateWorkflowQueries(queryClient);
    },
  });
}
