import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { aiRoutesClient } from '@/lib/aiRoutesClient';

function createJsonResponse(status: number, data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('aiRoutesClient', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('listRoutes calls GET /api/py/ai/routes with credentials', async () => {
    const mockData = { routes: [], active_route_id: 'direct:aistudio' };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockData));

    const res = await aiRoutesClient.listRoutes();
    expect(res).toEqual(mockData);
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes', {
      method: 'GET',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('listRouteModels calls GET /api/py/ai/routes/models with credentials', async () => {
    const mockData = { routes: [], warnings: [] };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockData));

    const res = await aiRoutesClient.listRouteModels();

    expect(res).toEqual(mockData);
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/models', {
      method: 'GET',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('activateRoute calls POST /api/py/ai/routes/:routeId/activate with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'activated', active_route_id: 'oauth:codex' }));

    const res = await aiRoutesClient.activateRoute('oauth:codex');
    expect(res.status).toBe('activated');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/oauth%3Acodex/activate', {
      method: 'POST',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('updateRouteSettings calls PATCH /api/py/ai/routes/settings with json body and credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'updated' }));

    const res = await aiRoutesClient.updateRouteSettings({ strategy: 'priority', session_affinity: true });
    expect(res.status).toBe('updated');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ strategy: 'priority', session_affinity: true }),
    });
  });

  it('startOAuth calls POST /api/py/ai/routes/oauth/start with credentials and json body (browser only)', async () => {
    const mockStart = {
      state: 's-123',
      provider: 'codex',
      callback_mode: 'loopback',
      callback_url: 'http://localhost:51121/oauth-callback',
      expires_in: 900,
      interval: 5,
      status: 'pending',
    };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockStart));

    const res = await aiRoutesClient.startOAuth({ provider: 'codex' });
    expect(res.state).toBe('s-123');
    expect(res.callback_mode).toBe('loopback');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/oauth/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ provider: 'codex' }),
    });
  });

  it('submitOAuthCallback calls POST /api/py/ai/routes/oauth/callback with JSON body', async () => {
    const mockResp = { status: 'completed', account_id: 'acc-1', masked_identity: 'user@example.com' };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockResp));

    const res = await aiRoutesClient.submitOAuthCallback({
      state: 's-123',
      code: 'c-456',
      redirect_url: 'http://localhost:51121/oauth-callback?state=s-123&code=c-456',
    });
    expect(res.status).toBe('completed');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/oauth/callback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        state: 's-123',
        code: 'c-456',
        redirect_url: 'http://localhost:51121/oauth-callback?state=s-123&code=c-456',
      }),
    });
  });

  it('pollOAuth calls GET /api/py/ai/routes/oauth/poll?state=... with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'pending' }));

    const res = await aiRoutesClient.pollOAuth('state-abc-123');
    expect(res.status).toBe('pending');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/oauth/poll?state=state-abc-123', {
      method: 'GET',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('cancelOAuth calls POST /api/py/ai/routes/oauth/cancel with credentials and json body', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'cancelled', state: 's1' }));

    const res = await aiRoutesClient.cancelOAuth('s1');
    expect(res.status).toBe('cancelled');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/oauth/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ state: 's1' }),
    });
  });

  it('getAccount calls GET /api/py/ai/routes/accounts/:id with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { id: 'acc-1', masked_identity: 'u***' }));

    const res = await aiRoutesClient.getAccount('acc-1');
    expect(res.id).toBe('acc-1');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/accounts/acc-1', {
      method: 'GET',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('patchAccount calls PATCH /api/py/ai/routes/accounts/:id with credentials and json body', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { id: 'acc-1', priority: 3 }));

    const res = await aiRoutesClient.patchAccount('acc-1', { priority: 3, weight: 2 });
    expect(res.priority).toBe(3);
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/accounts/acc-1', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ priority: 3, weight: 2 }),
    });
  });

  it('refreshAccount calls POST /api/py/ai/routes/accounts/:id/refresh with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { id: 'acc-1', status: 'active' }));

    const res = await aiRoutesClient.refreshAccount('acc-1');
    expect(res.status).toBe('active');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/accounts/acc-1/refresh', {
      method: 'POST',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('testAccount calls POST /api/py/ai/routes/accounts/:id/test with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'ok', account_id: 'acc-1', latency_ms: 12 }));

    const res = await aiRoutesClient.testAccount('acc-1');
    expect(res.status).toBe('ok');
    expect(res.latency_ms).toBe(12);
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/accounts/acc-1/test', {
      method: 'POST',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('resetAccountCooldown calls POST /api/py/ai/routes/accounts/:id/reset-cooldown with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'ok', account_id: 'acc-1' }));

    const res = await aiRoutesClient.resetAccountCooldown('acc-1');
    expect(res.status).toBe('ok');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/accounts/acc-1/reset-cooldown', {
      method: 'POST',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('removeAccount calls DELETE /api/py/ai/routes/accounts/:id with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'deleted', account_id: 'acc-1' }));

    const res = await aiRoutesClient.removeAccount('acc-1');
    expect(res.status).toBe('deleted');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/accounts/acc-1', {
      method: 'DELETE',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('resetProviderVault calls POST /api/py/ai/routes/vault/reset with credentials', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: 'reset', vault_state: 'available' }));

    const res = await aiRoutesClient.resetProviderVault();
    expect(res.status).toBe('reset');
    expect(fetch).toHaveBeenCalledWith('/api/py/ai/routes/vault/reset', {
      method: 'POST',
      headers: {},
      credentials: 'include',
      body: undefined,
    });
  });

  it('throws descriptive error on HTTP failure with json detail', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(400, { detail: 'Provider vault corrupt' }));

    await expect(aiRoutesClient.listRoutes()).rejects.toThrow('Provider vault corrupt');
  });

  it('throws descriptive error on HTTP failure with error string or fallback', async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(500, { error: 'Internal supervisor failure' }));

    await expect(aiRoutesClient.activateRoute('oauth:devin')).rejects.toThrow('Internal supervisor failure');
  });

  it("createEndpoint calls POST /api/py/ai/routes/endpoints with credentials and body", async () => {
    const mockRoute = { id: "endpoint:ep-1", display_label: "Ollama", kind: "endpoint" };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockRoute));

    const res = await aiRoutesClient.createEndpoint({
      display_label: "Ollama",
      base_url: "http://localhost:11434/v1",
      models: ["llama3"],
    });
    expect(res.id).toBe("endpoint:ep-1");
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        display_label: "Ollama",
        base_url: "http://localhost:11434/v1",
        models: ["llama3"],
      }),
    });
  });

  it("getEndpoint calls GET /api/py/ai/routes/endpoints/:id", async () => {
    const mockRoute = { id: "endpoint:ep-1", display_label: "Ollama" };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockRoute));

    const res = await aiRoutesClient.getEndpoint("endpoint:ep-1");
    expect(res.id).toBe("endpoint:ep-1");
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1", {
      method: "GET",
      headers: {},
      credentials: "include",
      body: undefined,
    });
  });

  it("updateEndpoint calls PATCH /api/py/ai/routes/endpoints/:id with body", async () => {
    const mockRoute = { id: "endpoint:ep-1", display_label: "Ollama Updated" };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockRoute));

    const res = await aiRoutesClient.updateEndpoint("endpoint:ep-1", { display_label: "Ollama Updated" });
    expect(res.display_label).toBe("Ollama Updated");
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ display_label: "Ollama Updated" }),
    });
  });

  it("deleteEndpoint calls DELETE /api/py/ai/routes/endpoints/:id", async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: "deleted", route_id: "endpoint:ep-1" }));

    const res = await aiRoutesClient.deleteEndpoint("endpoint:ep-1");
    expect(res.status).toBe("deleted");
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1", {
      method: "DELETE",
      headers: {},
      credentials: "include",
      body: undefined,
    });
  });

  it("addEndpointKey calls POST /api/py/ai/routes/endpoints/:id/keys with body", async () => {
    const mockKey = { id: "k-1", masked_identity: "sk-...1234", priority: 1, weight: 1 };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockKey));

    const res = await aiRoutesClient.addEndpointKey("endpoint:ep-1", { api_key: "sk-secret1234", priority: 1, weight: 1 });
    expect(res.id).toBe("k-1");
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ api_key: "sk-secret1234", priority: 1, weight: 1 }),
    });
  });

  it("listEndpointKeys calls GET /api/py/ai/routes/endpoints/:id/keys", async () => {
    const mockKeys = [{ id: "k-1", masked_identity: "sk-...1234" }];
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockKeys));

    const res = await aiRoutesClient.listEndpointKeys("endpoint:ep-1");
    expect(res).toEqual(mockKeys);
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1/keys", {
      method: "GET",
      headers: {},
      credentials: "include",
      body: undefined,
    });
  });

  it("patchEndpointKey calls PATCH /api/py/ai/routes/endpoints/:id/keys/:keyId", async () => {
    const mockKey = { id: "k-1", enabled: false };
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, mockKey));

    const res = await aiRoutesClient.patchEndpointKey("endpoint:ep-1", "k-1", { enabled: false });
    expect(res.enabled).toBe(false);
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1/keys/k-1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ enabled: false }),
    });
  });

  it("deleteEndpointKey calls DELETE /api/py/ai/routes/endpoints/:id/keys/:keyId", async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: "deleted", key_id: "k-1" }));

    const res = await aiRoutesClient.deleteEndpointKey("endpoint:ep-1", "k-1");
    expect(res.status).toBe("deleted");
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1/keys/k-1", {
      method: "DELETE",
      headers: {},
      credentials: "include",
      body: undefined,
    });
  });

  it("previewEndpointModels calls POST /api/py/ai/routes/endpoints/models/preview", async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { models: ["llama3", "mistral"] }));

    const res = await aiRoutesClient.previewEndpointModels({ base_url: "http://localhost:11434/v1" });
    expect(res.models).toEqual(["llama3", "mistral"]);
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/models/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ base_url: "http://localhost:11434/v1" }),
    });
  });

  it("refreshEndpointModels calls POST /api/py/ai/routes/endpoints/:id/models/refresh", async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { models: ["llama3.1:70b"] }));

    const res = await aiRoutesClient.refreshEndpointModels("endpoint:ep-1");
    expect(res.models).toEqual(["llama3.1:70b"]);
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1/models/refresh", {
      method: "POST",
      headers: {},
      credentials: "include",
      body: undefined,
    });
  });

  it("testEndpoint calls POST /api/py/ai/routes/endpoints/:id/test", async () => {
    vi.mocked(fetch).mockResolvedValue(createJsonResponse(200, { status: "ok", route_id: "endpoint:ep-1", latency_ms: 45 }));

    const res = await aiRoutesClient.testEndpoint("endpoint:ep-1");
    expect(res.status).toBe("ok");
    expect(res.latency_ms).toBe(45);
    expect(fetch).toHaveBeenCalledWith("/api/py/ai/routes/endpoints/endpoint%3Aep-1/test", {
      method: "POST",
      headers: {},
      credentials: "include",
      body: undefined,
    });
  });
});
