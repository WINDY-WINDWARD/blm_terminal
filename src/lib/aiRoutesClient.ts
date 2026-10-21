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

async function handleResponse<T>(res: Response, fallbackError: string): Promise<T> {
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
    const res = await fetch(BASE_URL, {
      method: 'GET',
      credentials: 'include',
    });
    return handleResponse<RoutesListResponse>(res, 'Failed to list AI provider routes');
  },

  async activateRoute(routeId: string): Promise<{ status: string; active_route_id: string }> {
    const res = await fetch(`${BASE_URL}/${encodeURIComponent(routeId)}/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    return handleResponse<{ status: string; active_route_id: string }>(res, 'Failed to activate route');
  },

  async updateRouteSettings(
    settings: RouteSettingsUpdate,
  ): Promise<{ status: string; updated_settings: Record<string, string> }> {
    const res = await fetch(`${BASE_URL}/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    return handleResponse<{ status: string; updated_settings: Record<string, string> }>(
      res,
      'Failed to update routing settings',
    );
  },

  async startOAuth(req: OAuthStartRequest): Promise<OAuthStartResponse> {
    const res = await fetch(`${BASE_URL}/oauth/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    return handleResponse<OAuthStartResponse>(res, 'Failed to initiate OAuth session');
  },

  async pollOAuth(state: string): Promise<OAuthPollResponse> {
    const res = await fetch(`${BASE_URL}/oauth/poll?state=${encodeURIComponent(state)}`, {
      method: 'GET',
    });
    return handleResponse<OAuthPollResponse>(res, 'Failed to poll OAuth status');
  },

  async cancelOAuth(state: string): Promise<{ status: string; state: string }> {
    const res = await fetch(`${BASE_URL}/oauth/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state }),
    });
    return handleResponse<{ status: string; state: string }>(res, 'Failed to cancel OAuth session');
  },

  async getAccount(accountId: string): Promise<CredentialSummary> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}`, {
      method: 'GET',
    });
    return handleResponse<CredentialSummary>(res, 'Failed to fetch account');
  },

  async patchAccount(accountId: string, patch: AccountPatchRequest): Promise<CredentialSummary> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    return handleResponse<CredentialSummary>(res, 'Failed to update account');
  },

  async refreshAccount(accountId: string): Promise<CredentialSummary> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}/refresh`, {
      method: 'POST',
    });
    return handleResponse<CredentialSummary>(res, 'Failed to refresh account');
  },

  async testAccount(accountId: string): Promise<AccountTestResponse> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}/test`, {
      method: 'POST',
    });
    return handleResponse<AccountTestResponse>(res, 'Failed to test account');
  },

  async reauthAccount(accountId: string): Promise<OAuthStartResponse> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}/reauth`, {
      method: 'POST',
    });
    return handleResponse<OAuthStartResponse>(res, 'Failed to start reauthentication');
  },

  async resetAccountCooldown(accountId: string): Promise<{ status: string; account_id: string }> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}/reset-cooldown`, {
      method: 'POST',
    });
    return handleResponse<{ status: string; account_id: string }>(res, 'Failed to reset cooldown');
  },

  async removeAccount(accountId: string): Promise<{ status: string; account_id: string }> {
    const res = await fetch(`${BASE_URL}/accounts/${encodeURIComponent(accountId)}`, {
      method: 'DELETE',
    });
    return handleResponse<{ status: string; account_id: string }>(res, 'Failed to remove account');
  },

  async resetProviderVault(): Promise<VaultResetResponse> {
    const res = await fetch(`${BASE_URL}/vault/reset`, {
      method: 'POST',
    });
    return handleResponse<VaultResetResponse>(res, 'Failed to reset provider vault');
  },
};
