'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  CustomPrompt,
  Paginated,
  PromptCreateInput,
  PromptUpdateInput,
} from '@/types/aiWorkflowTypes';

export const PROMPTS_PAGE_SIZE = 4;

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

export interface UseCustomPromptsOptions {
  mode?: string;
  limit?: number;
  offset?: number;
}

export function useCustomPrompts(options: UseCustomPromptsOptions = {}) {
  const { mode, limit = PROMPTS_PAGE_SIZE, offset = 0 } = options;

  return useQuery<Paginated<CustomPrompt>>({
    queryKey: ['ai', 'prompts', { mode, limit, offset }],
    queryFn: async (): Promise<Paginated<CustomPrompt>> => {
      const params = new URLSearchParams();
      if (mode) {
        params.set('mode', mode);
      }
      params.set('limit', String(limit));
      params.set('offset', String(offset));

      const res = await fetch(`/api/py/ai/prompts?${params.toString()}`);
      if (!res.ok) {
        throw await parseError(res, `Failed to load custom prompts (HTTP ${res.status})`);
      }
      return (await res.json()) as Paginated<CustomPrompt>;
    },
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
}

export function useCreatePrompt() {
  const queryClient = useQueryClient();

  return useMutation<CustomPrompt, Error, PromptCreateInput>({
    mutationFn: async (payload: PromptCreateInput): Promise<CustomPrompt> => {
      const res = await fetch('/api/py/ai/prompts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to create prompt (HTTP ${res.status})`);
      }
      return (await res.json()) as CustomPrompt;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai', 'prompts'] });
    },
  });
}

export interface UpdatePromptArgs {
  id: number;
  data: PromptUpdateInput;
}

export function useUpdatePrompt() {
  const queryClient = useQueryClient();

  return useMutation<CustomPrompt, Error, UpdatePromptArgs>({
    mutationFn: async ({ id, data }: UpdatePromptArgs): Promise<CustomPrompt> => {
      const res = await fetch(`/api/py/ai/prompts/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to update prompt (HTTP ${res.status})`);
      }
      return (await res.json()) as CustomPrompt;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai', 'prompts'] });
    },
  });
}

export function useDeletePrompt() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, number>({
    mutationFn: async (id: number): Promise<void> => {
      const res = await fetch(`/api/py/ai/prompts/${id}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to delete prompt (HTTP ${res.status})`);
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai', 'prompts'] });
    },
  });
}

export interface MarkPromptUsedResult {
  use_count: number;
  last_used_at: string;
}

export function useMarkPromptUsed() {
  const queryClient = useQueryClient();

  return useMutation<MarkPromptUsedResult, Error, number>({
    mutationFn: async (id: number): Promise<MarkPromptUsedResult> => {
      const res = await fetch(`/api/py/ai/prompts/${id}/used`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw await parseError(res, `Failed to mark prompt as used (HTTP ${res.status})`);
      }
      return (await res.json()) as MarkPromptUsedResult;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai', 'prompts'] });
    },
  });
}
