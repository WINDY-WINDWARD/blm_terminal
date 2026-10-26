import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiRoutesClient } from '@/lib/aiRoutesClient';
import type {
  AccountPatchRequest,
  CreateEndpointRequest,
  EndpointKeyInput,
  EndpointKeyUpdate,
  ModelPreviewRequest,
  RouteSettingsUpdate,
  UpdateEndpointRequest,
} from '@/types/aiRoutes';

export const AI_ROUTES_QUERY_KEY = ['ai', 'routes'] as const;

export function useAiRoutesQuery() {
  return useQuery({
    queryKey: AI_ROUTES_QUERY_KEY,
    queryFn: () => aiRoutesClient.listRoutes(),
    refetchInterval: 15_000,
    staleTime: 5_000,
    retry: 1,
    retryDelay: 1000,
    refetchOnWindowFocus: false,
  });
}

export function useInvalidateAiCaches() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: AI_ROUTES_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ['ai', 'status'] });
    queryClient.invalidateQueries({ queryKey: ['ai', 'catalog'] });
    queryClient.invalidateQueries({ queryKey: ['system-config'] });
    queryClient.invalidateQueries({ queryKey: ['ai-chat-models'] });
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

export function useSetRouteEnabledMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: ({ routeId, enabled }: { routeId: string; enabled: boolean }) =>
      aiRoutesClient.setRouteEnabled(routeId, enabled),
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

export function useCreateEndpointMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (req: CreateEndpointRequest) => aiRoutesClient.createEndpoint(req),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useUpdateEndpointMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: ({ endpointId, patch }: { endpointId: string; patch: UpdateEndpointRequest }) =>
      aiRoutesClient.updateEndpoint(endpointId, patch),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useDeleteEndpointMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (endpointId: string) => aiRoutesClient.deleteEndpoint(endpointId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useAddEndpointKeyMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: ({ endpointId, key }: { endpointId: string; key: EndpointKeyInput }) =>
      aiRoutesClient.addEndpointKey(endpointId, key),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function usePatchEndpointKeyMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: ({
      endpointId,
      keyId,
      patch,
    }: {
      endpointId: string;
      keyId: string;
      patch: EndpointKeyUpdate;
    }) => aiRoutesClient.patchEndpointKey(endpointId, keyId, patch),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useDeleteEndpointKeyMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: ({ endpointId, keyId }: { endpointId: string; keyId: string }) =>
      aiRoutesClient.deleteEndpointKey(endpointId, keyId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useRefreshEndpointModelsMutation() {
  const invalidate = useInvalidateAiCaches();
  return useMutation({
    mutationFn: (endpointId: string) => aiRoutesClient.refreshEndpointModels(endpointId),
    onSuccess: () => {
      invalidate();
    },
  });
}

export function useTestEndpointMutation() {
  return useMutation({
    mutationFn: (endpointId: string) => aiRoutesClient.testEndpoint(endpointId),
  });
}

export function usePreviewEndpointModelsMutation() {
  return useMutation({
    mutationFn: (req: ModelPreviewRequest) => aiRoutesClient.previewEndpointModels(req),
  });
}
