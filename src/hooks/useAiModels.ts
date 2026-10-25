'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { RouteModelCatalogResponse } from '@/types/aiRoutes';
import { aiRoutesClient } from '@/lib/aiRoutesClient';
import type { ModelOption } from '@/types/aiWidgetTypes';

export interface UseAiModelsReturn {
  catalogData: RouteModelCatalogResponse | undefined;
  modelsLoading: boolean;
  modelsError: boolean;
  refetchModels: () => Promise<unknown>;
  availableModels: ModelOption[];
  defaultModel: string;
  aiAuthStatus: { provider: string; is_configured: boolean } | null;
}

export function useAiModels(): UseAiModelsReturn {
  const [aiAuthStatus, setAiAuthStatus] = useState<{ provider: string; is_configured: boolean } | null>(null);

  useEffect(() => {
    fetch('/api/py/ai/status')
      .then((r) => r.json())
      .then((d) => setAiAuthStatus(d))
      .catch(console.error);

    const intv = setInterval(() => {
      fetch('/api/py/ai/status')
        .then((r) => r.json())
        .then((d) => setAiAuthStatus(d))
        .catch(console.error);
    }, 10000);
    return () => clearInterval(intv);
  }, []);

  const {
    data: catalogData,
    isError: modelsError,
    isLoading: modelsLoading,
    refetch: refetchModels,
  } = useQuery<RouteModelCatalogResponse>({
    queryKey: ['ai', 'catalog', 'chat'],
    queryFn: async (): Promise<RouteModelCatalogResponse> => {
      try {
        return await aiRoutesClient.listRouteModels();
      } catch {
        const res = await fetch('/api/py/ai/chat/models');
        if (!res.ok) throw new Error(`Model list unavailable (HTTP ${res.status})`);
        const flat = (await res.json()) as { id: string; label: string }[];
        const groups = new Map<string, { route_id: string; label: string; kind: string; provider: string; models: { id: string; label: string }[] }>();
        for (const m of flat) {
          const mid = /^blm:([^/]+)\/(.+)$/.exec(m.id);
          const routeId = mid ? mid[1] : 'unknown';
          const short = mid ? mid[2] : m.label;
          const bracket = /^\[(.+?)\]\s*(.*)$/.exec(m.label);
          const label = bracket ? bracket[1] : routeId;
          const provider = routeId.includes(':') ? routeId.split(':')[1] : routeId;
          const g = groups.get(routeId) ?? { route_id: routeId, label, kind: 'oauth', provider, models: [] };
          g.models.push({ id: m.id, label: bracket ? bracket[2] || short : short });
          groups.set(routeId, g);
        }
        return { routes: [...groups.values()], warnings: [] };
      }
    },
    retry: 2,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  const availableModels: ModelOption[] = (catalogData?.routes ?? []).flatMap((route) =>
    route.models.map((m) => ({ id: m.id, label: `[${route.label}] ${m.label}` })),
  );

  const defaultModel = (() => {
    const active = (catalogData?.routes ?? []).find((r) => r.route_id === aiAuthStatus?.provider);
    return active?.models[0]?.id ?? availableModels[0]?.id ?? '';
  })();

  return {
    catalogData,
    modelsLoading,
    modelsError,
    refetchModels,
    availableModels,
    defaultModel,
    aiAuthStatus,
  };
}
