import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/msw-server';
import { render, screen, fireEvent, waitFor, createTestQueryClient } from '../utils/renderWithProviders';
import { QueryClientProvider } from '@tanstack/react-query';
import { CustomEndpointsTab } from '@/components/modals/AiProvidersModal/CustomEndpointsTab';
import { DirectProvidersTab } from '@/components/modals/AiProvidersModal/DirectProvidersTab';
import { EndpointEditorModal } from '@/components/modals/AiProvidersModal/EndpointEditorModal';
import { useInvalidateAiCaches } from '@/hooks/useAiRoutes';
import { SettingsModal } from '@/components/modals/SettingsModal';
import { SavedLayoutsSyncProvider } from '@/components/SavedLayoutsSyncProvider';
import { FirstLaunchModal } from '@/components/modals/FirstLaunchModal';
import { AiWidget } from '@/components/widgets/AiWidget';
import {
  showSettingsModalAtom,
  aiProvidersModalTabAtom,
  onboardingCompletedAtom,
  authAtom,
  advancedScrapingConsentAtom,
} from '@/store/terminalStore';
import type { RouteSummary } from '@/types/aiRoutes';

const mockCustomEndpointRoute: RouteSummary = {
  id: 'endpoint:ep-uuid-1',
  kind: 'endpoint',
  provider: 'custom',
  display_label: 'Local Ollama Gateway',
  proxy_prefix: 'custom-ollama',
  enabled: true,
  is_active: false,
  health: { healthy: true, status: 'configured', key_count: 1 },
  accounts: [],
  keys: [
    {
      id: 'key-1',
      route_id: 'endpoint:ep-uuid-1',
      kind: 'custom_endpoint_key',
      masked_identity: 'sk-...9876',
      priority: 1,
      weight: 2,
      enabled: true,
      status: 'active',
      cooldown: null,
      last_redacted_error: null,
      created_at: '2026-10-21T00:00:00Z',
      updated_at: '2026-10-21T00:00:00Z',
    },
  ],
  config: {
    base_url: 'http://localhost:11434/v1',
    warning_flags: ['localhost_endpoint', 'unencrypted_http'],
    has_headers: true,
    header_names: ['X-Custom-Auth', 'Authorization'],
  },
  models: ['llama3.1:70b', 'qwen2.5:32b'],
  recovery_state: null,
};

const mockDirectRoutes: RouteSummary[] = [
  {
    id: 'direct:aistudio',
    kind: 'direct',
    provider: 'aistudio',
    display_label: 'Google AI Studio',
    proxy_prefix: null,
    enabled: true,
    is_active: true,
    health: { healthy: true, status: 'active' },
    accounts: [],
    keys: [],
    config: { is_configured: true },
    models: ['gemini-2.5-flash', 'gemini-2.5-pro'],
    recovery_state: null,
  },
  {
    id: 'direct:openai',
    kind: 'direct',
    provider: 'openai',
    display_label: 'OpenAI Direct',
    proxy_prefix: null,
    enabled: true,
    is_active: false,
    health: { healthy: false, status: 'unconfigured' },
    accounts: [],
    keys: [],
    config: { is_configured: false },
    models: ['gpt-4o', 'gpt-4o-mini'],
    recovery_state: null,
  },
];

describe('Task 7: Custom Endpoints, Direct Providers & Model Selectors', () => {
  beforeEach(() => {
    server.resetHandlers();
  });

  // ── 1. Custom Endpoints Tab & Editor ──────────────────────────────────────────

  describe('CustomEndpointsTab and EndpointEditorModal', () => {
    it('renders empty state when no custom endpoints are registered', () => {
      render(<CustomEndpointsTab routes={[]} activeRouteId="direct:aistudio" />);
      expect(screen.getByText('No Custom Endpoints Registered')).toBeInTheDocument();
      expect(screen.getByTestId('empty-add-endpoint-btn')).toBeInTheDocument();
    });

    it('renders existing custom endpoint cards with masked keys, warnings, and headers', () => {
      render(
        <CustomEndpointsTab
          routes={[mockCustomEndpointRoute]}
          activeRouteId="direct:aistudio"
        />,
      );

      expect(screen.getByText('Local Ollama Gateway')).toBeInTheDocument();
      expect(screen.getByText('http://localhost:11434/v1')).toBeInTheDocument();
      expect(screen.getByText('llama3.1:70b')).toBeInTheDocument();
      expect(screen.getByText('qwen2.5:32b')).toBeInTheDocument();
      expect(screen.getByText('Secret Headers: X-Custom-Auth, Authorization')).toBeInTheDocument();
      expect(screen.getByText('localhost_endpoint')).toBeInTheDocument();
      expect(screen.getByText('sk-...9876')).toBeInTheDocument();
      expect(screen.getByText('P:1')).toBeInTheDocument();
      expect(screen.getByText('W:2')).toBeInTheDocument();
    });

    it('validates URL in EndpointEditorModal showing errors and warnings in real-time', () => {
      render(<EndpointEditorModal isOpen={true} onClose={vi.fn()} />);

      const urlInput = screen.getByTestId('endpoint-url-input');

      // Invalid scheme
      fireEvent.change(urlInput, { target: { value: 'ftp://files.example.com' } });
      expect(screen.getByTestId('url-validation-error')).toHaveTextContent("Only http: and https: are allowed");

      // Valid HTTP with unencrypted warning and localhost warning
      fireEvent.change(urlInput, { target: { value: 'http://localhost:8000/v1' } });
      expect(screen.queryByTestId('url-validation-error')).not.toBeInTheDocument();
      const warnings = screen.getByTestId('url-validation-warnings');
      expect(warnings).toHaveTextContent('Unencrypted HTTP connection');
      expect(warnings).toHaveTextContent('Local loopback target (localhost)');
    });

    it('fetches live models and allows manual fallback in EndpointEditorModal', async () => {
      server.use(
        http.post('/api/py/ai/routes/endpoints/models/preview', () => {
          return HttpResponse.json({
            models: ['deepseek-coder-v2', 'mistral-large'],
          });
        }),
      );

      render(<EndpointEditorModal isOpen={true} onClose={vi.fn()} />);

      const labelInput = screen.getByTestId('endpoint-label-input');
      const urlInput = screen.getByTestId('endpoint-url-input');

      fireEvent.change(labelInput, { target: { value: 'My vLLM Gateway' } });
      fireEvent.change(urlInput, { target: { value: 'https://vllm.internal.net/v1' } });

      // Click Fetch Models Live
      const fetchBtn = screen.getByText('Fetch Models Live');
      fireEvent.click(fetchBtn);

      await waitFor(() => {
        expect(screen.getByText('deepseek-coder-v2')).toBeInTheDocument();
        expect(screen.getByText('mistral-large')).toBeInTheDocument();
      });

      // Manual model fallback addition
      const manualInput = screen.getByPlaceholderText(/Manual model fallback/i);
      fireEvent.change(manualInput, { target: { value: 'custom-model:extra' } });
      fireEvent.click(screen.getByText('+ Add Model'));

      expect(screen.getByText('custom-model:extra')).toBeInTheDocument();
    });

    it('submits new endpoint creation with headers, keys, and models', async () => {
      let createdPayload: unknown = null;
      server.use(
        http.post('/api/py/ai/routes/endpoints', async ({ request }) => {
          createdPayload = await request.json();
          return HttpResponse.json({
            id: 'endpoint:created-1',
            display_label: 'Enterprise Gateway',
            kind: 'endpoint',
            proxy_prefix: 'custom-enterprise',
            models: ['gpt-enterprise-1'],
          });
        }),
      );

      const onClose = vi.fn();
      render(<EndpointEditorModal isOpen={true} onClose={onClose} />);

      fireEvent.change(screen.getByTestId('endpoint-label-input'), {
        target: { value: 'Enterprise Gateway' },
      });
      fireEvent.change(screen.getByTestId('endpoint-url-input'), {
        target: { value: 'https://gateway.enterprise.com/v1' },
      });

      // Add a header
      fireEvent.click(screen.getByText('Add Header'));
      const headerNameInput = screen.getByPlaceholderText(/Header Name/i);
      const headerValInput = screen.getByPlaceholderText(/Header Value/i);
      fireEvent.change(headerNameInput, { target: { value: 'X-Tenant-ID' } });
      fireEvent.change(headerValInput, { target: { value: 'tenant-123' } });

      // Add a key
      fireEvent.click(screen.getByText('Add Key'));
      const keyInput = screen.getByPlaceholderText(/API Key \(e\.g\. sk-\.\.\.\)/i);
      fireEvent.change(keyInput, { target: { value: 'sk-secret-token-123' } });

      // Save
      fireEvent.click(screen.getByTestId('save-endpoint-btn'));

      await waitFor(() => {
        expect(createdPayload).toEqual(
          expect.objectContaining({
            display_label: 'Enterprise Gateway',
            base_url: 'https://gateway.enterprise.com/v1',
            headers: { 'X-Tenant-ID': 'tenant-123' },
            keys: expect.arrayContaining([
              expect.objectContaining({ api_key: 'sk-secret-token-123', priority: 1, weight: 1 }),
            ]),
          }),
        );
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('tests an existing endpoint and displays latency feedback', async () => {
      server.use(
        http.post('/api/py/ai/routes/endpoints/endpoint%3Aep-uuid-1/test', () => {
          return HttpResponse.json({
            status: 'ok',
            route_id: 'endpoint:ep-uuid-1',
            status_code: 200,
            latency_ms: 34.2,
          });
        }),
      );

      render(
        <CustomEndpointsTab
          routes={[mockCustomEndpointRoute]}
          activeRouteId="direct:aistudio"
        />,
      );

      const testBtn = screen.getByTestId('test-endpoint-endpoint:ep-uuid-1');
      fireEvent.click(testBtn);

      await waitFor(() => {
        expect(screen.getByTestId('test-result-endpoint:ep-uuid-1')).toHaveTextContent(
          'Connected successfully (34.2ms)',
        );
      });
    });

    it('activates custom endpoint route and calls activate endpoint', async () => {
      let activatedRouteId = '';
      server.use(
        http.post('/api/py/ai/routes/endpoint%3Aep-uuid-1/activate', () => {
          activatedRouteId = 'endpoint:ep-uuid-1';
          return HttpResponse.json({ status: 'activated', active_route_id: 'endpoint:ep-uuid-1' });
        }),
      );

      render(
        <CustomEndpointsTab
          routes={[mockCustomEndpointRoute]}
          activeRouteId="direct:aistudio"
        />,
      );

      const activateBtn = screen.getByTestId('activate-endpoint-endpoint:ep-uuid-1');
      fireEvent.click(activateBtn);

      await waitFor(() => {
        expect(activatedRouteId).toBe('endpoint:ep-uuid-1');
      });
    });

    it('supports key operations: add key, toggle enable/disable, test key, and delete key', async () => {
      let patchedBody: unknown = null;
      let deletedKey = false;
      let testedKey = false;

      server.use(
        http.post('/api/py/ai/routes/endpoints/endpoint%3Aep-uuid-1/keys', () => {
          return HttpResponse.json({
            id: 'key-2',
            route_id: 'endpoint:ep-uuid-1',
            masked_identity: 'sk-...4321',
            priority: 2,
            weight: 1,
            enabled: true,
          });
        }),
        http.patch('/api/py/ai/routes/endpoints/endpoint%3Aep-uuid-1/keys/key-1', async ({ request }) => {
          patchedBody = await request.json();
          return HttpResponse.json({ id: 'key-1', enabled: false });
        }),
        http.post('/api/py/ai/routes/accounts/key-1/test', () => {
          testedKey = true;
          return HttpResponse.json({ status: 'ok', latency_ms: 18.5 });
        }),
        http.delete('/api/py/ai/routes/endpoints/endpoint%3Aep-uuid-1/keys/key-1', () => {
          deletedKey = true;
          return HttpResponse.json({ status: 'deleted', key_id: 'key-1' });
        }),
      );

      render(
        <CustomEndpointsTab
          routes={[mockCustomEndpointRoute]}
          activeRouteId="direct:aistudio"
        />,
      );

      // Toggle disable on existing key
      const toggleBtn = screen.getByTestId('toggle-key-key-1');
      expect(toggleBtn).toHaveTextContent('Disable');
      fireEvent.click(toggleBtn);

      await waitFor(() => {
        expect(patchedBody).toEqual({ enabled: false });
      });

      // Test key
      const testKeyBtn = screen.getByTestId('test-key-key-1');
      fireEvent.click(testKeyBtn);

      await waitFor(() => {
        expect(testedKey).toBe(true);
        expect(screen.getByTestId('key-test-result-key-1')).toHaveTextContent('✓ 18.5ms');
      });

      // Delete key
      const deleteKeyBtn = screen.getByTestId('delete-key-key-1');
      fireEvent.click(deleteKeyBtn);

      await waitFor(() => {
        expect(deletedKey).toBe(true);
      });
    });
    it('displays error banner when endpoint deletion or key addition fails', async () => {
      server.use(
        http.delete('/api/py/ai/routes/endpoints/:id', () => {
          return new HttpResponse(JSON.stringify({ detail: 'Endpoint is locked by active session' }), {
            status: 400,
            headers: { 'Content-Type': 'application/json' },
          });
        }),
      );

      render(
        <CustomEndpointsTab
          routes={[mockCustomEndpointRoute]}
          activeRouteId="direct:aistudio"
        />,
      );

      // Click delete button on endpoint card
      const delBtn = screen.getByTestId('delete-endpoint-endpoint:ep-uuid-1');
      fireEvent.click(delBtn);

      // Confirm delete
      const confirmBtn = screen.getByTestId('confirm-delete-btn-endpoint:ep-uuid-1');
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        const errorBanner = screen.getByTestId('custom-endpoints-error-banner');
        expect(errorBanner).toHaveTextContent('Endpoint is locked by active session');
      });
    });

    it('EndpointEditorModal sends empty headers object on edit when all headers are removed', async () => {
      let patchedBody: any = null;
      server.use(
        http.patch('/api/py/ai/routes/endpoints/:id', async ({ request }) => {
          patchedBody = await request.json();
          return HttpResponse.json({ status: 'ok', route: mockCustomEndpointRoute });
        }),
      );

      render(
        <EndpointEditorModal
          isOpen={true}
          onClose={vi.fn()}
          route={mockCustomEndpointRoute}
        />,
      );

      const saveBtn = screen.getByTestId('save-endpoint-btn');
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(patchedBody).not.toBeNull();
        expect(patchedBody.headers).toEqual({});
      });
    });
  });

  // ── 2. Direct Providers Tab ──────────────────────────────────────────────────

  describe('DirectProvidersTab', () => {
    it('renders direct providers with instructions, configured indicator, and replace key flow', async () => {
      render(
        <DirectProvidersTab
          routes={mockDirectRoutes}
          activeRouteId="direct:aistudio"
        />,
      );

      // Google AI Studio is active and configured
      expect(screen.getAllByText('Google AI Studio')[0]).toBeInTheDocument();
      expect(screen.getByText('ACTIVE ROUTE')).toBeInTheDocument();
      expect(screen.getByTestId('configured-key-indicator')).toBeInTheDocument();
      expect(screen.getByText('●●●●●●●●●●●●●●●●')).toBeInTheDocument();
      // Ensure no raw key is present in DOM
      expect(screen.queryByDisplayValue('AIza')).not.toBeInTheDocument();

      // Click Replace Key
      const replaceBtn = screen.getByTestId('replace-key-btn');
      fireEvent.click(replaceBtn);

      expect(screen.getByTestId('direct-key-input')).toBeInTheDocument();
      expect(screen.getByTestId('save-direct-key-btn')).toBeInTheDocument();

      // Cancel button reverts
      fireEvent.click(screen.getByText('Cancel'));
      expect(screen.getByTestId('configured-key-indicator')).toBeInTheDocument();
    });

    it('saves a direct API key to system_config and triggers cache invalidation', async () => {
      let savedKeyDbSlot = '';
      let savedKeyValue = '';

      server.use(
        http.put('/api/py/system-config/:key', async ({ params, request }) => {
          savedKeyDbSlot = params.key as string;
          const body = (await request.json()) as { value: string };
          savedKeyValue = body.value;
          return HttpResponse.json({ status: 'ok' });
        }),
      );

      render(
        <DirectProvidersTab
          routes={mockDirectRoutes}
          activeRouteId="direct:aistudio"
        />,
      );

      // Select OpenAI Direct (unconfigured)
      fireEvent.click(screen.getByTestId('direct-provider-item-openai'));

      const input = screen.getByTestId('direct-key-input');
      fireEvent.change(input, { target: { value: 'sk-my-fresh-openai-key' } });

      const saveBtn = screen.getByTestId('save-direct-key-btn');
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(savedKeyDbSlot).toBe('ai.openai_api_key');
        expect(savedKeyValue).toBe('sk-my-fresh-openai-key');
        expect(screen.getByText('API Key saved successfully!')).toBeInTheDocument();
      });
    });

    it('fetches direct provider models dynamically', async () => {
      server.use(
        http.post('/api/py/ai/provider-models', () => {
          return HttpResponse.json([
            { id: 'gemini-3.8-flash-high', label: 'Gemini 3.8 Flash High' },
            { id: 'gemini-3.8-flash-low', label: 'Gemini 3.8 Flash Low' },
          ]);
        }),
      );

      render(
        <DirectProvidersTab
          routes={mockDirectRoutes}
          activeRouteId="direct:aistudio"
        />,
      );

      const fetchBtn = screen.getByTestId('fetch-direct-models-btn');
      fireEvent.click(fetchBtn);

      await waitFor(() => {
        expect(screen.getByText('Live Catalog (2 models fetched):')).toBeInTheDocument();
        expect(screen.getByText('Gemini 3.8 Flash High')).toBeInTheDocument();
        expect(screen.getByText('Gemini 3.8 Flash Low')).toBeInTheDocument();
      });
    });
  });

  // ── 3. Cache Invalidation ────────────────────────────────────────────────────

  describe('Cache Invalidation', () => {
    it('useInvalidateAiCaches invalidates all relevant query keys including ai-chat-models', () => {
      const queryClient = createTestQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

      function TestCacheComponent() {
        const invalidate = useInvalidateAiCaches();
        return <button onClick={invalidate}>Invalidate</button>;
      }

      render(
        <QueryClientProvider client={queryClient}>
          <TestCacheComponent />
        </QueryClientProvider>,
      );

      fireEvent.click(screen.getByText('Invalidate'));

      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['ai', 'routes'] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['ai', 'status'] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['ai', 'catalog'] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['system-config'] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['ai-chat-models'] });
    });
  });

  // ── 4. SettingsModal & FirstLaunchModal Integration ──────────────────────────

  describe('SettingsModal & FirstLaunchModal Integration', () => {
    it('SettingsModal does not call dead /api/py/auth/codex/... routes on mount or sign in', async () => {
      const codexStatusCalled = vi.fn();
      server.use(
        http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ status: 'ok', layouts: [], tombstones: [] })),
        http.get('/api/watchlists', () => HttpResponse.json([])),
        http.get('/api/py/system_config/browser-status', () => HttpResponse.json({ available: false })),
        http.get('/api/py/system_config/consent', () => HttpResponse.json({ status: 'ok' })),
        http.get('/api/py/auth/codex/status', () => {
          codexStatusCalled();
          return HttpResponse.json({ logged_in: false });
        }),
        http.get('/api/py/system-config', () => {
          return HttpResponse.json({
            'ai.provider': 'codex',
          });
        }),
        http.get('/api/py/ai/status', () => {
          return HttpResponse.json({
            provider: 'codex',
            is_configured: true,
          });
        }),
        http.get('/api/py/ai/chat/models', () => {
          return HttpResponse.json([
            { id: 'oauth:codex/gpt-4o', label: '[Codex] gpt-4o' },
          ]);
        }),
      );

      render(
        <SavedLayoutsSyncProvider>
          <SettingsModal />
        </SavedLayoutsSyncProvider>,
        {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
            [authAtom, { user: { id: 'admin', is_admin: true } }],
          ],
        },
      });

      // Switch to AI tab
      await waitFor(() => {
        const aiTab = screen.getByRole('button', { name: /INTELLIGENCE/i });
        fireEvent.click(aiTab);
      });

      // Wait a tick and verify /api/py/auth/codex/status was never called
      await new Promise((r) => setTimeout(r, 100));
      expect(codexStatusCalled).not.toHaveBeenCalled();
    });

    it('SettingsModal renders OAuthSessionDialog when sign in with ChatGPT is clicked', async () => {
      server.use(
        http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ status: 'ok', layouts: [], tombstones: [] })),
        http.get('/api/watchlists', () => HttpResponse.json([])),
        http.get('/api/py/system_config/browser-status', () => HttpResponse.json({ available: false })),
        http.get('/api/py/system_config/consent', () => HttpResponse.json({ status: 'ok' })),
        http.get('/api/py/system-config', () => {
          return HttpResponse.json({
            'ai.provider': 'codex',
          });
        }),
        http.get('/api/py/ai/status', () => {
          return HttpResponse.json({
            provider: 'codex',
            is_configured: false,
          });
        }),
        http.get('/api/py/ai/chat/models', () => {
          return HttpResponse.json([]);
        }),
        http.post('/api/py/ai/routes/oauth/start', () => {
          return HttpResponse.json({
            session_id: 'sess-123',
            provider: 'codex',
            flow: 'device',
            user_code: 'ABCD-EFGH',
            verification_uri: 'https://auth0.openai.com/activate',
            expires_in: 900,
            interval: 5,
          });
        }),
      );

      render(
        <SavedLayoutsSyncProvider>
          <SettingsModal />
        </SavedLayoutsSyncProvider>,
        {
          wrapperProps: {
            initialAtomValues: [
              [showSettingsModalAtom, true],
              [authAtom, { user: { id: 'admin', is_admin: true } }],
            ],
          },
        },
      );

      // Switch to AI tab
      await waitFor(() => {
        const aiTab = screen.getByRole('button', { name: /INTELLIGENCE/i });
        fireEvent.click(aiTab);
      });


      // Find and click "Sign in with ChatGPT"
      const signInBtn = await screen.findByRole('button', { name: /Sign in with ChatGPT/i });
      fireEvent.click(signInBtn);

      // OAuthSessionDialog must render in the DOM
      await waitFor(() => {
        expect(screen.getByTestId('oauth-session-dialog')).toBeInTheDocument();
        expect(screen.getByText(/Connect OpenAI Codex \(ChatGPT\)/i)).toBeInTheDocument();
      });
    });

    it('FirstLaunchModal advances to models step, loads route-qualified catalog, and remaps stale worker models', async () => {
      let savedHunter = '';
      let savedVerifier = '';

      server.use(
        http.get('/api/py/first-boot', () =>
          HttpResponse.json({ reachable: true, onboardingCompleted: false }),
        ),
        http.get('/api/py/eula', () => HttpResponse.json({ accepted: true })),
        http.get('/api/py/eula-status', () =>
          HttpResponse.json({ accepted: true, reachable: true, version: 'eula-v1' }),
        ),
        http.get('/api/py/auth/setup-status', () =>
          HttpResponse.json({ database_ready: true, admin_created: true, needs_setup: false }),
        ),
        http.get('/api/py/system-config', () => {
          return HttpResponse.json({
            'ai.provider': 'aistudio',
          });
        }),
        http.get('/api/py/ai/status', () =>
          HttpResponse.json({ provider: 'aistudio', is_configured: true, isConfigured: true }),
        ),
        http.get('/api/py/ai/chat/models', () => {
          return HttpResponse.json([
            { id: 'blm:direct:aistudio/gemini-3.8-flash-high', label: 'Gemini 3.8 Flash High' },
            { id: 'blm:direct:aistudio/gemini-3.8-flash-low', label: 'Gemini 3.8 Flash Low' },
          ]);
        }),
        http.put('/api/py/system-config/:key', async ({ params, request }) => {
          const body = (await request.json()) as { value: string };
          if (params.key === 'ai.hunter_model') savedHunter = body.value;
          if (params.key === 'ai.verifier_model') savedVerifier = body.value;
          return HttpResponse.json({ status: 'ok' });
        }),
      );

      render(<FirstLaunchModal />, {
        wrapperProps: {
          initialAtomValues: [
            [onboardingCompletedAtom, false],
            [authAtom, { user: { id: 'admin', username: 'admin', is_admin: true } }],
            [advancedScrapingConsentAtom, true],
          ],
        },
      });

      // 1. Wizard loads at 'welcome' step (EULA is pre-agreed)
      expect(await screen.findByText('Welcome to BLM Terminal.')).toBeInTheDocument();

      // Click Continue to step 2: 'backend'
      fireEvent.click(screen.getByRole('button', { name: /continue/i }));

      // Wait for backend health check to succeed, then click Continue to step 3: 'admin'
      await waitFor(() => {
        expect(screen.getByText('Checking engine status')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByRole('button', { name: /continue/i }));

      // Admin is already signed in via authAtom, click Continue to step 4: 'consent'
      await waitFor(() => {
        expect(screen.getByText(/Signed in as admin/i)).toBeInTheDocument();
      });
      fireEvent.click(screen.getByRole('button', { name: /continue/i }));

      // Consent is agreed via atom, click Continue to step 5: 'ai'
      await waitFor(() => {
        expect(screen.getByText(/Data extraction & privacy/i)).toBeInTheDocument();
      });
      fireEvent.click(screen.getByRole('button', { name: /continue/i }));

      // On 'ai' step, click Continue to step 6: 'models'
      await waitFor(() => {
        expect(screen.getByText(/AI assistant \(optional\)/i)).toBeInTheDocument();
      });
      fireEvent.click(screen.getByRole('button', { name: /continue/i }));

      // 2. Now on the 'models' step: verify worker models section renders
      await waitFor(() => {
        expect(screen.getByText('HUNTER MODEL')).toBeInTheDocument();
        expect(screen.getByText('VERIFIER MODEL')).toBeInTheDocument();
      });

      // 3. Verify automatic remapping to first valid route-qualified model and saved values
      await waitFor(() => {
        expect(savedHunter).toBe('blm:direct:aistudio/gemini-3.8-flash-high');
        expect(savedVerifier).toBe('blm:direct:aistudio/gemini-3.8-flash-high');
      });

      // 4. Verify ModelCombobox displays route-qualified labels
      expect(screen.getAllByText('Gemini 3.8 Flash High').length).toBeGreaterThan(0);
    });

    it('FirstLaunchModal renders OAuthSessionDialog when Google Gemini login is clicked', async () => {
      server.use(
        http.get('/api/py/first-boot', () =>
          HttpResponse.json({ reachable: true, onboardingCompleted: false }),
        ),
        http.get('/api/py/eula-status', () =>
          HttpResponse.json({ accepted: true, reachable: true, version: 'eula-v1' }),
        ),
        http.get('/api/py/ai/status', () =>
          HttpResponse.json({ provider: 'gemini', is_configured: false }),
        ),
        http.get('/api/py/system-config', () => {
          return HttpResponse.json({ 'ai.provider': 'gemini' });
        }),
        http.post('/api/py/ai/routes/oauth/start', () => {
          return HttpResponse.json({
            session_id: 'sess-gemini-1',
            provider: 'antigravity',
            flow: 'browser',
            auth_url: 'https://accounts.google.com/o/oauth2/auth?...',
            expires_in: 600,
            interval: 5,
          });
        }),
      );

      render(<FirstLaunchModal initialStep="ai" />, {
        wrapperProps: {
          initialAtomValues: [
            [onboardingCompletedAtom, false],
            [authAtom, { user: { id: 'admin', username: 'admin', is_admin: true } }],
          ],
        },
      });

      // Wait for first boot probe to settle past 'Reading setup state...'
      await waitFor(() => {
        expect(screen.queryByText(/Reading setup state/i)).not.toBeInTheDocument();
      });

      // Switch to Gemini provider
      const select = await screen.findByRole('combobox');
      fireEvent.change(select, { target: { value: 'gemini' } });

      // Click "Login with Google (Gemini)"
      const loginBtn = await screen.findByRole('button', { name: /Login with Google \(Gemini\)/i });
      fireEvent.click(loginBtn);

      // OAuthSessionDialog must render in the DOM
      await waitFor(() => {
        expect(screen.getByTestId('oauth-session-dialog')).toBeInTheDocument();
        expect(screen.getByText(/Connect Google Pro \(Gemini\)/i)).toBeInTheDocument();
      });
    });
  });
  // ── 5. AiWidget Model Selection & Stale Remapping ────────────────────────────

  describe('AiWidget & Model Selector Integration', () => {
    it('automatically remaps stale model selection when route models catalog changes', async () => {
      let currentModels = [
        { id: 'direct:aistudio/gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
        { id: 'direct:aistudio/gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
      ];

      server.use(
        http.get('/api/py/ai/status', () => {
          return HttpResponse.json({
            provider: 'aistudio',
            is_configured: true,
          });
        }),
        http.get('/api/py/ai/chat/models', () => {
          return HttpResponse.json(currentModels);
        }),
      );

      const queryClient = createTestQueryClient();

      render(
        <QueryClientProvider client={queryClient}>
          <AiWidget />
        </QueryClientProvider>,
      );

      // Initially shows the first valid model from the current catalog
      await waitFor(() => {
        expect(screen.getByText('Gemini 2.5 Flash')).toBeInTheDocument();
      });

      // Now route changes, changing the model catalog to a custom endpoint
      currentModels = [
        { id: 'endpoint:ep-1/llama3.1:70b', label: 'llama3.1:70b' },
        { id: 'endpoint:ep-1/qwen2.5:32b', label: 'qwen2.5:32b' },
      ];

      // Invalidate the cache as happens on route activation
      queryClient.invalidateQueries({ queryKey: ['ai-chat-models'] });

      // Stale model (gemini-2.5-flash) must be automatically remapped to new route default (llama3.1:70b)
      await waitFor(() => {
        expect(screen.getByText('llama3.1:70b')).toBeInTheDocument();
        expect(screen.queryByText('Gemini 2.5 Flash')).not.toBeInTheDocument();
      });
    });
  });
});
