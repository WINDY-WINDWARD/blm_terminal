import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiRoutesClient } from '@/lib/aiRoutesClient';
import type { AccountPatchRequest, RouteSettingsUpdate } from '@/types/aiRoutes';

export const AI_ROUTES_QUERY_KEY = ['ai', 'routes'] as const;

export function useAiRoutesQuery() {
  return useQuery({
    queryKey: AI_ROUTES_QUERY_KEY,
    queryFn: () => aiRoutesClient.listRoutes(),
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
}

export function useInvalidateAiCaches() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: AI_ROUTES_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ['ai', 'status'] });
    queryClient.invalidateQueries({ queryKey: ['ai', 'catalog'] });
    queryClient.invalidateQueries({ queryKey: ['system-config'] });
  };
}

export function useActivateRouteMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (routeId: string) => aiRoutesClient.activateRoute(routeId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useUpdateRouteSettingsMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (settings: RouteSettingsUpdate) => aiRoutesClient.updateRouteSettings(settings),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function usePatchAccountMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: ({ accountId, patch }: { accountId: string; patch: AccountPatchRequest }) =>
      aiRoutesClient.patchAccount(accountId, patch),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useRefreshAccountMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (accountId: string) => aiRoutesClient.refreshAccount(accountId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useTestAccountMutation() {
  return useMutation({
    mutationFn: (accountId: string) => aiRoutesClient.testAccount(accountId),
  });
}

export function useResetCooldownMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (accountId: string) => aiRoutesClient.resetAccountCooldown(accountId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useRemoveAccountMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (accountId: string) => aiRoutesClient.removeAccount(accountId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useResetVaultMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: () => aiRoutesClient.resetProviderVault(),
    onSuccess: () => {
      invalidate();
    },
  });
}
