import type {
  AccountPatchRequest,
  AccountTestResponse,
  CreateEndpointRequest,
  CredentialSummary,
  EndpointKeyInput,
  EndpointKeyUpdate,
  EndpointTestResponse,
  ModelPreviewRequest,
  ModelPreviewResponse,
  OAuthCallbackRequest,
  OAuthPollResponse,
  OAuthStartRequest,
  OAuthStartResponse,
  RouteSettingsUpdate,
  RouteModelCatalogResponse,
  RoutesListResponse,
  RouteSummary,
  SetRouteEnabledResponse,
  UpdateEndpointRequest,
  VaultResetResponse,
} from '@/types/aiRoutes';

const BASE_URL = '/api/py/ai/routes';

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
  fallbackError = 'Request failed',
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    ...options.headers,
  };
  let body: string | undefined = undefined;

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  const res = await fetch(url, {
    method: options.method || 'GET',
    headers,
    credentials: 'include',
    body,
  });

  if (!res.ok) {
    let msg = fallbackError;
    try {
      const errJson = await res.json();
      if (errJson?.detail) {
        msg = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } else if (errJson?.error) {
        msg = errJson.error;
      }
    } catch {
      msg = `${fallbackError} (HTTP ${res.status})`;
    }
    throw new Error(msg);
  }

  return res.json() as Promise<T>;
}

export const aiRoutesClient = {
  async listRoutes(): Promise<RoutesListResponse> {
    return request<RoutesListResponse>('', { method: 'GET' }, 'Failed to list AI provider routes');
  },

  async listRouteModels(): Promise<RouteModelCatalogResponse> {
    return request<RouteModelCatalogResponse>('/models', { method: 'GET' }, 'Failed to list route models');
  },

  async activateRoute(routeId: string): Promise<{ status: string; active_route_id: string }> {
    return request<{ status: string; active_route_id: string }>(
      `/${encodeURIComponent(routeId)}/activate`,
      { method: 'POST' },
      'Failed to activate route',
    );
  },

  async setRouteEnabled(routeId: string, enabled: boolean): Promise<SetRouteEnabledResponse> {
    return request<SetRouteEnabledResponse>(
      `/${encodeURIComponent(routeId)}/enabled`,
      { method: 'PATCH', body: { enabled } },
      'Failed to set route enabled status',
    );
  },

  async updateRouteSettings(
    settings: RouteSettingsUpdate,
  ): Promise<{ status: string; updated_settings: Record<string, string> }> {
    return request<{ status: string; updated_settings: Record<string, string> }>(
      '/settings',
      { method: 'PATCH', body: settings },
      'Failed to update routing settings',
    );
  },

  async startOAuth(req: OAuthStartRequest): Promise<OAuthStartResponse> {
    return request<OAuthStartResponse>(
      '/oauth/start',
      { method: 'POST', body: req },
      'Failed to initiate OAuth session',
    );
  },

  async pollOAuth(state: string): Promise<OAuthPollResponse> {
    return request<OAuthPollResponse>(
      `/oauth/poll?state=${encodeURIComponent(state)}`,
      { method: 'GET' },
      'Failed to poll OAuth status',
    );
  },

  async cancelOAuth(state: string): Promise<{ status: string; state: string }> {
    return request<{ status: string; state: string }>(
      '/oauth/cancel',
      { method: 'POST', body: { state } },
      'Failed to cancel OAuth session',
    );
  },

  async submitOAuthCallback(req: OAuthCallbackRequest): Promise<OAuthPollResponse> {
    return request<OAuthPollResponse>(
      '/oauth/callback',
      { method: 'POST', body: req },
      'Failed to submit OAuth callback',
    );
  },

  async getAccount(accountId: string): Promise<CredentialSummary> {
    return request<CredentialSummary>(
      `/accounts/${encodeURIComponent(accountId)}`,
      { method: 'GET' },
      'Failed to fetch account',
    );
  },

  async patchAccount(accountId: string, patch: AccountPatchRequest): Promise<CredentialSummary> {
    return request<CredentialSummary>(
      `/accounts/${encodeURIComponent(accountId)}`,
      { method: 'PATCH', body: patch },
      'Failed to update account',
    );
  },

  async refreshAccount(accountId: string): Promise<CredentialSummary> {
    return request<CredentialSummary>(
      `/accounts/${encodeURIComponent(accountId)}/refresh`,
      { method: 'POST' },
      'Failed to refresh account',
    );
  },

  async testAccount(accountId: string): Promise<AccountTestResponse> {
    return request<AccountTestResponse>(
      `/accounts/${encodeURIComponent(accountId)}/test`,
      { method: 'POST' },
      'Failed to test account',
    );
  },

  async resetAccountCooldown(accountId: string): Promise<{ status: string; account_id: string }> {
    return request<{ status: string; account_id: string }>(
      `/accounts/${encodeURIComponent(accountId)}/reset-cooldown`,
      { method: 'POST' },
      'Failed to reset cooldown',
    );
  },

  async removeAccount(accountId: string): Promise<{ status: string; account_id: string }> {
    return request<{ status: string; account_id: string }>(
      `/accounts/${encodeURIComponent(accountId)}`,
      { method: 'DELETE' },
      'Failed to remove account',
    );
  },

  async resetProviderVault(): Promise<VaultResetResponse> {
    return request<VaultResetResponse>(
      '/vault/reset',
      { method: 'POST' },
      'Failed to reset provider vault',
    );
  },

  async createEndpoint(req: CreateEndpointRequest): Promise<RouteSummary> {
    return request<RouteSummary>(
      '/endpoints',
      { method: 'POST', body: req },
      'Failed to create custom endpoint',
    );
  },

  async getEndpoint(endpointId: string): Promise<RouteSummary> {
    return request<RouteSummary>(
      `/endpoints/${encodeURIComponent(endpointId)}`,
      { method: 'GET' },
      'Failed to fetch endpoint',
    );
  },

  async updateEndpoint(endpointId: string, patch: UpdateEndpointRequest): Promise<RouteSummary> {
    return request<RouteSummary>(
      `/endpoints/${encodeURIComponent(endpointId)}`,
      { method: 'PATCH', body: patch },
      'Failed to update endpoint',
    );
  },

  async deleteEndpoint(endpointId: string): Promise<{ status: string; route_id: string }> {
    return request<{ status: string; route_id: string }>(
      `/endpoints/${encodeURIComponent(endpointId)}`,
      { method: 'DELETE' },
      'Failed to delete endpoint',
    );
  },

  async addEndpointKey(endpointId: string, key: EndpointKeyInput): Promise<CredentialSummary> {
    return request<CredentialSummary>(
      `/endpoints/${encodeURIComponent(endpointId)}/keys`,
      { method: 'POST', body: key },
      'Failed to add endpoint key',
    );
  },

  async listEndpointKeys(endpointId: string): Promise<CredentialSummary[]> {
    return request<CredentialSummary[]>(
      `/endpoints/${encodeURIComponent(endpointId)}/keys`,
      { method: 'GET' },
      'Failed to list endpoint keys',
    );
  },

  async patchEndpointKey(
    endpointId: string,
    keyId: string,
    patch: EndpointKeyUpdate,
  ): Promise<CredentialSummary> {
    return request<CredentialSummary>(
      `/endpoints/${encodeURIComponent(endpointId)}/keys/${encodeURIComponent(keyId)}`,
      { method: 'PATCH', body: patch },
      'Failed to update endpoint key',
    );
  },

  async deleteEndpointKey(
    endpointId: string,
    keyId: string,
  ): Promise<{ status: string; key_id: string }> {
    return request<{ status: string; key_id: string }>(
      `/endpoints/${encodeURIComponent(endpointId)}/keys/${encodeURIComponent(keyId)}`,
      { method: 'DELETE' },
      'Failed to delete endpoint key',
    );
  },

  async previewEndpointModels(req: ModelPreviewRequest): Promise<ModelPreviewResponse> {
    return request<ModelPreviewResponse>(
      '/endpoints/models/preview',
      { method: 'POST', body: req },
      'Failed to preview endpoint models',
    );
  },

  async refreshEndpointModels(endpointId: string): Promise<{ models: string[] }> {
    return request<{ models: string[] }>(
      `/endpoints/${encodeURIComponent(endpointId)}/models/refresh`,
      { method: 'POST' },
      'Failed to refresh endpoint models',
    );
  },

  async testEndpoint(endpointId: string): Promise<EndpointTestResponse> {
    return request<EndpointTestResponse>(
      `/endpoints/${encodeURIComponent(endpointId)}/test`,
      { method: 'POST' },
      'Failed to test endpoint',
    );
  },
};
