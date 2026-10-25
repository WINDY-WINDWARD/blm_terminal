'use client';

import { useQuery } from '@tanstack/react-query';
import { aiRoutesClient } from '@/lib/aiRoutesClient';

interface UseRouteModelsOptions {
  enabled?: boolean;
}

export function useRouteModels({ enabled = true }: UseRouteModelsOptions = {}) {
  return useQuery({
    queryKey: ['ai', 'catalog'],
    queryFn: () => aiRoutesClient.listRouteModels(),
    enabled,
    staleTime: 60_000,
    retry: 2,
    refetchOnWindowFocus: true,
  });
}
