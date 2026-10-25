'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouteModels } from '@/hooks/useRouteModels';
import { aiRoutesClient } from '@/lib/aiRoutesClient';

export function useIntelligenceRoutes({
  isOpen,
  activeTab,
  isAdmin,
}: {
  isOpen: boolean;
  activeTab: string;
  isAdmin: boolean;
}) {
  const routeModelsQuery = useRouteModels({ enabled: isOpen && activeTab === 'intelligence' });
  const routeModels = routeModelsQuery.data?.routes ?? [];

  const aiRoutesQuery = useQuery({
    queryKey: ['ai', 'routes'],
    queryFn: () => aiRoutesClient.listRoutes(),
    enabled: isOpen && activeTab === 'intelligence' && isAdmin,
    staleTime: 60_000,
  });

  const aiRoutes = aiRoutesQuery.data?.routes ?? [];
  const activeRouteId = aiRoutesQuery.data?.active_route_id;
  const activeRoute = aiRoutes.find((route) => route.id === activeRouteId);
  const oauthAccountCount = aiRoutes
    .filter((route) => route.kind === 'oauth')
    .reduce((count, route) => count + route.accounts.length, 0);
  const customEndpointCount = aiRoutes.filter((route) => route.kind === 'endpoint').length;
  const directKeyCount = aiRoutes
    .filter((route) => route.kind === 'direct')
    .reduce((count, route) => count + route.keys.length, 0);

  return {
    routeModelsQuery,
    routeModels,
    aiRoutesQuery,
    activeRoute,
    activeRouteId,
    oauthAccountCount,
    customEndpointCount,
    directKeyCount,
  };
}
