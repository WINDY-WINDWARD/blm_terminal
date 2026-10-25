import React from 'react';
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { render, screen, fireEvent, waitFor, act, within } from '../utils/renderWithProviders';
import { Provider as JotaiProvider, createStore } from 'jotai';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '../utils/renderWithProviders';
import { server } from '../mocks/msw-server';
import { TerminalContainer } from '@/components/TerminalContainer';
import { SavedLayoutsSyncProvider } from '@/components/SavedLayoutsSyncProvider';
import { SettingsModal } from '@/components/modals/SettingsModal';
import {
  showSettingsModalAtom,
  settingsModalTabAtom,
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
  authAtom,
  openAlgoAvailableAtom,
} from '@/store/terminalStore';
import { useAtomValue } from 'jotai';

function StatusWatcher() {
  const isSettingsOpen = useAtomValue(showSettingsModalAtom);
  const activeTab = useAtomValue(settingsModalTabAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  return (
    <div>
      <div data-testid="is-settings-open">{String(isSettingsOpen)}</div>
      <div data-testid="active-settings-tab">{activeTab}</div>
      <div data-testid="panel-1-widget">{activePanels['panel-1']}</div>
    </div>
  );
}

describe('SettingsModal rendering via TerminalContainer', () => {
  it('does not render modal when showSettingsModalAtom is false', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
          ],
        },
      }
    );

    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    expect(screen.queryByText(/TERMINAL SETTINGS/i)).not.toBeInTheDocument();
  });

  it('renders modal when showSettingsModalAtom is true and displays all tabs', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByText(/TERMINAL SETTINGS/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^WORKSPACE$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^CONNECTIONS$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^INTELLIGENCE$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^AUTOMATION$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^SYSTEM$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\[CLOSE\]/i })).toBeInTheDocument();
  });

  it('closes modal via [CLOSE] button', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    const closeBtn = screen.getByRole('button', { name: /\[CLOSE\]/i });
    fireEvent.click(closeBtn);
    expect(screen.getByTestId('is-settings-open').textContent).toBe('false');
  });

  it('closes modal via [X] button', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    const xBtn = screen.getByRole('button', { name: /close settings/i });
    fireEvent.click(xBtn);
    expect(screen.getByTestId('is-settings-open').textContent).toBe('false');
  });

  it('closes modal via Escape key', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.getByTestId('is-settings-open').textContent).toBe('false');
  });

  it('submitting SETTINGS command opens modal and does not populate focused panel', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
            [focusedPanelAtom, 'panel-1'],
            [activePanelsAtom, { 'panel-1': 'CHART' }],
            [activeCommandAtom, 'SETTINGS'],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    expect(screen.getByTestId('panel-1-widget').textContent).toBe('CHART');
  });

  it('submitting bare LAYOUT command opens Settings modal on workspace tab', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
            [settingsModalTabAtom, 'system'],
            [focusedPanelAtom, 'panel-1'],
            [activePanelsAtom, { 'panel-1': 'CHART' }],
            [activeCommandAtom, 'LAYOUT'],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    expect(screen.getByTestId('active-settings-tab').textContent).toBe('workspace');
    expect(screen.getByTestId('panel-1-widget').textContent).toBe('CHART');
  });

  it('keeps AI provider setup in the manager and OpenAlgo configuration in Connections', async () => {
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/system-config', () => HttpResponse.json({ 'openalgo.url': 'https://saved-openalgo.example:5000' })),
      http.get('/api/py/ai/routes', () => HttpResponse.json({
        routes: [
          {
            id: 'oauth:antigravity',
            kind: 'oauth',
            provider: 'antigravity',
            display_label: 'Google Pro',
            proxy_prefix: 'antigravity',
            enabled: true,
            is_active: true,
            health: { healthy: true, status: 'active', proxy_status: 'running', account_count: 1 },
            accounts: [{ id: 'google-account', route_id: 'oauth:antigravity', kind: 'oauth', masked_identity: 'g***@example.com', priority: 1, weight: 1, enabled: true, status: 'active', cooldown: null, last_redacted_error: null, created_at: null, updated_at: null }],
            keys: [],
            config: {},
            models: [],
            recovery_state: null,
          },
          {
            id: 'endpoint:custom-1',
            kind: 'endpoint',
            provider: 'custom',
            display_label: 'Custom Endpoint',
            proxy_prefix: 'custom',
            enabled: true,
            is_active: false,
            health: { healthy: false, status: 'configured', proxy_status: 'running', key_count: 0 },
            accounts: [],
            keys: [],
            config: {},
            models: [],
            recovery_state: null,
          },
          {
            id: 'direct:openai',
            kind: 'direct',
            provider: 'openai',
            display_label: 'OpenAI',
            proxy_prefix: 'blm-56d7965a0cfb0ee5',
            enabled: true,
            is_active: false,
            health: { healthy: true, status: 'configured', proxy_status: 'running', key_count: 1, transport: 'proxy' },
            accounts: [],
            keys: [{ id: 'openai-key', route_id: 'direct:openai', kind: 'direct', masked_identity: 'sk-***', priority: 1, weight: 1, enabled: true, status: 'active', cooldown: null, last_redacted_error: null, created_at: null, updated_at: null }],
            config: { is_configured: true, transport: 'proxy' },
            models: [],
            recovery_state: null,
          },
        ],
        active_route_id: 'oauth:antigravity',
        proxy_status: { state: 'running', pid: 123, port: 4567, uptime_seconds: 60, restart_count: 0 },
        vault_state: 'available',
        recovery_state: null,
        settings: { strategy: 'priority', session_affinity: false, session_affinity_ttl: '1h', request_retry: 0, max_retry_credentials: 1, max_retry_interval: 0 },
      })),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json({ routes: [], warnings: [] })),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] })),
    );

    render(
      <SavedLayoutsSyncProvider>
        <SettingsModal isOpen />
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [settingsModalTabAtom, 'intelligence'],
            [authAtom, { user: { id: 1, username: 'admin', is_admin: true } }],
            [openAlgoAvailableAtom, true],
          ],
        },
      }
    );

    expect(screen.getByRole('button', { name: /MANAGE PROVIDERS/i })).toBeInTheDocument();
    expect(await screen.findByText('Google Pro')).toBeInTheDocument();
    expect(screen.getByText('CONNECTED')).toBeInTheDocument();
    expect(screen.getByText('oauth:antigravity')).toBeInTheDocument();
    expect(screen.getByText('OAuth accounts: 1')).toBeInTheDocument();
    expect(screen.getByText('Custom endpoints: 1')).toBeInTheDocument();
    expect(screen.getByText('Direct keys: 1')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /^Provider:?$/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/API Key/i)).not.toBeInTheDocument();
    expect(screen.queryByText('OpenAlgo Configuration')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^CONNECTIONS$/i }));

    expect(screen.getByText('OpenAlgo Configuration')).toBeInTheDocument();
    expect(screen.getByLabelText(/OpenAlgo URL/i)).toBeInTheDocument();
    expect(await screen.findByText('OpenAlgo URL: https://saved-openalgo.example:5000')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /MANAGE PROVIDERS/i })).not.toBeInTheDocument();
  });
});


const mockAiRoutesForHydration = {
  routes: [
    {
      id: 'oauth:antigravity',
      kind: 'oauth',
      provider: 'antigravity',
      display_label: 'Google Pro',
      proxy_prefix: 'antigravity',
      enabled: true,
      is_active: true,
      health: { healthy: true, status: 'active', proxy_status: 'running', account_count: 1 },
      accounts: [{ id: 'google-account', route_id: 'oauth:antigravity', kind: 'oauth', masked_identity: 'g***@example.com', priority: 1, weight: 1, enabled: true, status: 'active', cooldown: null, last_redacted_error: null, created_at: null, updated_at: null }],
      keys: [],
      config: {},
      models: [
        { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', route_id: 'oauth:antigravity', provider: 'antigravity' },
        { id: 'claude-3-haiku', label: 'Claude 3 Haiku', route_id: 'oauth:antigravity', provider: 'antigravity' },
        { id: 'gpt-4o-mini', label: 'GPT-4o Mini', route_id: 'oauth:antigravity', provider: 'antigravity' },
      ],
      recovery_state: null,
    },
  ],
  active_route_id: 'oauth:antigravity',
  proxy_status: { state: 'running', pid: 123, port: 4567, uptime_seconds: 60, restart_count: 0 },
  vault_state: 'available',
  recovery_state: null,
  settings: { strategy: 'priority', session_affinity: false, session_affinity_ttl: '1h', request_retry: 0, max_retry_credentials: 1, max_retry_interval: 0 },
};

const mockAiCatalogForHydration = {
  routes: [
    {
      route_id: 'oauth:antigravity',
      provider: 'antigravity',
      label: 'Google Pro',
      kind: 'oauth',
      enabled: true,
      models: [
        { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
        { id: 'claude-3-haiku', label: 'Claude 3 Haiku' },
        { id: 'gpt-4o-mini', label: 'GPT-4o Mini' },
      ],
    },
  ],
  warnings: [],
};

describe('SettingsModal system-config hydration and model persistence', () => {
  it('does not fetch system configuration while Settings is closed', async () => {
    let fetchCount = 0;
    server.use(
      http.get('/api/py/system-config', () => {
        fetchCount++;
        return HttpResponse.json({});
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
            [authAtom, { user: { id: 1, username: 'admin', is_admin: true } }],
          ],
        },
      }
    );

    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 100));
    expect(fetchCount).toBe(0);
  });

  it('does not fetch system configuration when Settings is open but auth is not available', async () => {
    let fetchCount = 0;
    server.use(
      http.get('/api/py/system-config', () => {
        fetchCount++;
        return HttpResponse.json({});
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    render(
      <SavedLayoutsSyncProvider>
        <SettingsModal isOpen={true} />
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [authAtom, null],
          ],
        },
      }
    );

    await new Promise((r) => setTimeout(r, 100));
    expect(fetchCount).toBe(0);
  });

  it('hydrates Hunter and Verifier models on open when authenticated', async () => {
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/ai/routes', () => HttpResponse.json(mockAiRoutesForHydration)),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json(mockAiCatalogForHydration)),
      http.get('/api/py/system-config', () =>
        HttpResponse.json({
          'ai.hunter_model': 'gemini-2.5-flash',
          'ai.verifier_model': 'claude-3-haiku',
        })
      ),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    render(
      <SavedLayoutsSyncProvider>
        <SettingsModal isOpen={true} />
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [settingsModalTabAtom, 'intelligence'],
            [authAtom, { user: { id: 1, username: 'admin', is_admin: true } }],
          ],
        },
      }
    );

    const hunterSelect = (await screen.findByLabelText(/Hunter Model/i)) as HTMLSelectElement;
    const verifierSelect = (await screen.findByLabelText(/Verifier Model/i)) as HTMLSelectElement;

    await waitFor(() => {
      expect(hunterSelect.value).toBe('gemini-2.5-flash');
      expect(verifierSelect.value).toBe('claude-3-haiku');
    });
  });

  it('refetches system configuration when modal is closed and reopened', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/ai/routes', () => HttpResponse.json(mockAiRoutesForHydration)),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json(mockAiCatalogForHydration)),
      http.get('/api/py/system-config', () => {
        callCount++;
        if (callCount === 1) {
          return HttpResponse.json({
            'ai.hunter_model': 'gemini-2.5-flash',
            'ai.verifier_model': 'claude-3-haiku',
          });
        }
        return HttpResponse.json({
          'ai.hunter_model': 'gpt-4o-mini',
          'ai.verifier_model': 'gemini-2.5-flash',
        });
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    const testStore = createStore();
    testStore.set(showSettingsModalAtom, true);
    testStore.set(settingsModalTabAtom, 'intelligence');
    testStore.set(authAtom, { user: { id: 1, username: 'admin', is_admin: true } });

    render(
      <JotaiProvider store={testStore}>
        <QueryClientProvider client={createTestQueryClient()}>
          <SavedLayoutsSyncProvider>
            <SettingsModal />
          </SavedLayoutsSyncProvider>
        </QueryClientProvider>
      </JotaiProvider>
    );

    const hunterSelect = (await screen.findByLabelText(/Hunter Model/i)) as HTMLSelectElement;
    await waitFor(() => {
      expect(hunterSelect.value).toBe('gemini-2.5-flash');
    });
    expect(callCount).toBe(1);

    // Close settings modal
    act(() => {
      testStore.set(showSettingsModalAtom, false);
    });

    // Reopen settings modal
    act(() => {
      testStore.set(showSettingsModalAtom, true);
    });

    await waitFor(() => {
      expect(callCount).toBe(2);
      const liveHunterSelect = screen.getByLabelText(/Hunter Model/i) as HTMLSelectElement;
      expect(liveHunterSelect.value).toBe('gpt-4o-mini');
    });
  });

  it('ignores an earlier system-config response after Settings closes and reopens', async () => {
    let callCount = 0;
    let resolveFirstResponse: (response: Response) => void = () => {};
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/ai/routes', () => HttpResponse.json(mockAiRoutesForHydration)),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json(mockAiCatalogForHydration)),
      http.get('/api/py/system-config', () => {
        callCount++;
        if (callCount === 1) {
          return new Promise<Response>((resolve) => {
            resolveFirstResponse = resolve;
          });
        }
        return HttpResponse.json({
          'ai.hunter_model': 'gpt-4o-mini',
          'ai.verifier_model': 'gemini-2.5-flash',
        });
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    const testStore = createStore();
    testStore.set(showSettingsModalAtom, true);
    testStore.set(settingsModalTabAtom, 'intelligence');
    testStore.set(authAtom, { user: { id: 1, username: 'admin', is_admin: true } });

    render(
      <JotaiProvider store={testStore}>
        <QueryClientProvider client={createTestQueryClient()}>
          <SavedLayoutsSyncProvider>
            <SettingsModal />
          </SavedLayoutsSyncProvider>
        </QueryClientProvider>
      </JotaiProvider>
    );

    const hunterSelect = (await screen.findByLabelText(/Hunter Model/i)) as HTMLSelectElement;
    await waitFor(() => expect(callCount).toBe(1));

    act(() => testStore.set(showSettingsModalAtom, false));
    act(() => testStore.set(showSettingsModalAtom, true));
    await waitFor(() => expect(callCount).toBe(2));
    const reopenedHunterSelect = screen.getByLabelText(/Hunter Model/i) as HTMLSelectElement;
    await waitFor(() => expect(reopenedHunterSelect.value).toBe('gpt-4o-mini'));

    await act(async () => {
      resolveFirstResponse(HttpResponse.json({
        'ai.hunter_model': 'gemini-2.5-flash',
        'ai.verifier_model': 'claude-3-haiku',
      }));
    });
    await waitFor(() => expect(reopenedHunterSelect.value).toBe('gpt-4o-mini'));
  });

  it('recovers and fetches system config when authenticated state becomes available after unauthenticated/401 state', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/ai/routes', () => HttpResponse.json(mockAiRoutesForHydration)),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json(mockAiCatalogForHydration)),
      http.get('/api/py/system-config', () => {
        callCount++;
        return HttpResponse.json({
          'ai.hunter_model': 'gemini-2.5-flash',
          'ai.verifier_model': 'claude-3-haiku',
        });
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    const testStore = createStore();
    testStore.set(showSettingsModalAtom, true);
    testStore.set(settingsModalTabAtom, 'intelligence');
    testStore.set(authAtom, null);

    render(
      <JotaiProvider store={testStore}>
        <QueryClientProvider client={createTestQueryClient()}>
          <SavedLayoutsSyncProvider>
            <SettingsModal />
          </SavedLayoutsSyncProvider>
        </QueryClientProvider>
      </JotaiProvider>
    );

    await new Promise((r) => setTimeout(r, 100));
    expect(callCount).toBe(0);

    // Authenticated state becomes available
    act(() => {
      testStore.set(authAtom, { user: { id: 1, username: 'admin', is_admin: true } });
    });

    const hunterSelect = (await screen.findByLabelText(/Hunter Model/i)) as HTMLSelectElement;
    await waitFor(() => {
      expect(callCount).toBe(1);
      expect(hunterSelect.value).toBe('gemini-2.5-flash');
    });
  });

  it('preserves current model values, exposes error and visible retry button on load failure, and recovers on retry', async () => {
    let shouldFail = true;
    let callCount = 0;
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/ai/routes', () => HttpResponse.json(mockAiRoutesForHydration)),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json(mockAiCatalogForHydration)),
      http.get('/api/py/system-config', () => {
        callCount++;
        if (shouldFail) {
          return new HttpResponse(JSON.stringify({ detail: 'Internal server error' }), { status: 500 });
        }
        return HttpResponse.json({
          'ai.hunter_model': 'gemini-2.5-flash',
          'ai.verifier_model': 'claude-3-haiku',
        });
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    render(
      <SavedLayoutsSyncProvider>
        <SettingsModal isOpen={true} />
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [settingsModalTabAtom, 'intelligence'],
            [authAtom, { user: { id: 1, username: 'admin', is_admin: true } }],
          ],
        },
      }
    );

    // Error and retry button should be visible
    const alerts = await screen.findAllByRole('alert');
    expect(alerts.length).toBeGreaterThan(0);
    const bannerAlert = alerts.find((el) => el.textContent?.includes('Failed to load system configuration')) || alerts[0];
    expect(bannerAlert).toBeInTheDocument();
    const retryBtn = within(bannerAlert).getByRole('button', { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();

    // Verify current model value was not wiped to empty
    const hunterSelect = screen.getByLabelText(/Hunter Model/i) as HTMLSelectElement;
    expect(hunterSelect).toBeInTheDocument();

    // Now resolve the failure and click retry
    shouldFail = false;
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(callCount).toBeGreaterThanOrEqual(2);
      expect(hunterSelect.value).toBe('gemini-2.5-flash');
    });
  });

  it('does not report Saved when update fails, but reports Saved on success', async () => {
    let putStatus = 500;
    server.use(
      http.get('/api/py/ai/status', () => HttpResponse.json({ provider: 'antigravity', is_configured: true })),
      http.get('/api/py/ai/routes', () => HttpResponse.json(mockAiRoutesForHydration)),
      http.get('/api/py/ai/routes/models', () => HttpResponse.json(mockAiCatalogForHydration)),
      http.get('/api/py/system-config', () =>
        HttpResponse.json({
          'ai.hunter_model': 'gemini-2.5-flash',
          'ai.verifier_model': 'claude-3-haiku',
        })
      ),
      http.put('/api/py/system-config/:key', () => {
        if (putStatus >= 400) {
          return new HttpResponse(JSON.stringify({ detail: 'Save failed' }), { status: putStatus });
        }
        return HttpResponse.json({ status: 'ok' });
      }),
      http.get('/api/watchlists', () => HttpResponse.json([])),
      http.post('/api/py/layouts/bulk-sync', () => HttpResponse.json({ layouts: [], tombstones: [] }))
    );

    render(
      <SavedLayoutsSyncProvider>
        <SettingsModal isOpen={true} />
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [settingsModalTabAtom, 'intelligence'],
            [authAtom, { user: { id: 1, username: 'admin', is_admin: true } }],
          ],
        },
      }
    );

    const hunterSelect = (await screen.findByLabelText(/Hunter Model/i)) as HTMLSelectElement;
    await waitFor(() => expect(hunterSelect.value).toBe('gemini-2.5-flash'));

    // Trigger change when PUT returns 500
    fireEvent.change(hunterSelect, { target: { value: 'gpt-4o-mini' } });

    // Wait for the debounce (500ms) + fetch response
    await new Promise((r) => setTimeout(r, 700));

    // Must NOT report Saved on failed update
    expect(screen.queryByText(/^Saved$/i)).not.toBeInTheDocument();

    // Now set PUT to succeed (200 OK)
    putStatus = 200;
    fireEvent.change(hunterSelect, { target: { value: 'claude-3-haiku' } });

    // Wait for the debounce + fetch response
    await waitFor(() => {
      expect(screen.getByText(/^Saved$/i)).toBeInTheDocument();
    }, { timeout: 2000 });
  });
});
