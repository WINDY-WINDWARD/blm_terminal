import type {
  AccountPatchRequest,
  AccountTestResponse,
  CredentialSummary,
  OAuthPollResponse,
  OAuthStartRequest,
  OAuthStartResponse,
  RouteSettingsUpdate,
  RoutesListResponse,
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

  async activateRoute(routeId: string): Promise<{ status: string; active_route_id: string }> {
    return request<{ status: string; active_route_id: string }>(
      `/${encodeURIComponent(routeId)}/activate`,
      { method: 'POST' },
      'Failed to activate route',
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
};
