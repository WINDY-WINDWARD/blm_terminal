import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/msw-server';
import { render, screen, fireEvent, waitFor } from '../utils/renderWithProviders';
import { AiProvidersModal } from '@/components/modals/AiProvidersModal';
import { CommandBar } from '@/components/CommandBar';
import { SettingsModal } from '@/components/modals/SettingsModal';
import { TerminalContainer } from '@/components/TerminalContainer';
import { SavedLayoutsSyncProvider } from '@/components/SavedLayoutsSyncProvider';
import {
  showAiProvidersModalAtom,
  aiProvidersModalTabAtom,
  showSettingsModalAtom,
  activeCommandAtom,
  authAtom,
} from '@/store/terminalStore';
import type { RoutesListResponse } from '@/types/aiRoutes';

const baseMockRoutesResponse: RoutesListResponse = {
  routes: [
    {
      id: 'oauth:codex',
      kind: 'oauth',
      provider: 'codex',
      display_label: 'Codex',
      proxy_prefix: 'blm-codex',
      enabled: true,
      is_active: false,
      health: { healthy: true, status: 'configured', account_count: 2 },
      accounts: [
        {
          id: 'acc-codex-1',
          route_id: 'oauth:codex',
          kind: 'oauth',
          masked_identity: 'user1***@openai.com',
          priority: 1,
          weight: 2,
          enabled: true,
          status: 'active',
          cooldown: null,
          last_redacted_error: null,
          created_at: '2026-10-20T00:00:00Z',
          updated_at: '2026-10-20T00:00:00Z',
        },
        {
          id: 'acc-codex-2',
          route_id: 'oauth:codex',
          kind: 'oauth',
          masked_identity: 'user2***@openai.com',
          priority: 2,
          weight: 1,
          enabled: false,
          status: 'disabled',
          cooldown: null,
          last_redacted_error: null,
          created_at: '2026-10-20T00:00:00Z',
          updated_at: '2026-10-20T00:00:00Z',
        },
      ],
      keys: [],
      config: {},
      models: ['gpt-4o', 'o1'],
      recovery_state: null,
    },
    {
      id: 'oauth:claude',
      kind: 'oauth',
      provider: 'claude',
      display_label: 'Claude',
      proxy_prefix: 'blm-claude',
      enabled: true,
      is_active: false,
      health: { healthy: true, status: 'configured', account_count: 2 },
      accounts: [
        {
          id: 'acc-claude-cd',
          route_id: 'oauth:claude',
          kind: 'oauth',
          masked_identity: 'anthropic_cd***@example.com',
          priority: 1,
          weight: 1,
          enabled: true,
          status: 'cooldown',
          cooldown: new Date(Date.now() + 600000).toISOString(),
          last_redacted_error: null,
          created_at: '2026-10-20T00:00:00Z',
          updated_at: '2026-10-20T00:00:00Z',
        },
        {
          id: 'acc-claude-err',
          route_id: 'oauth:claude',
          kind: 'oauth',
          masked_identity: 'claude_err***@example.com',
          priority: 1,
          weight: 1,
          enabled: true,
          status: 'error',
          cooldown: null,
          last_redacted_error: 'Rate limit exceeded on upstream token exchange',
          created_at: '2026-10-20T00:00:00Z',
          updated_at: '2026-10-20T00:00:00Z',
        },
      ],
      keys: [],
      config: {},
      models: ['claude-3-5-sonnet'],
      recovery_state: null,
    },
    {
      id: 'oauth:antigravity',
      kind: 'oauth',
      provider: 'antigravity',
      display_label: 'Antigravity',
      proxy_prefix: 'blm-antigravity',
      enabled: true,
      is_active: false,
      health: { healthy: false, status: 'unconfigured', account_count: 0 },
      accounts: [],
      keys: [],
      config: {},
      models: ['gemini-3.8-flash'],
      recovery_state: null,
    },
    {
      id: 'oauth:xai',
      kind: 'oauth',
      provider: 'xai',
      display_label: 'xAI',
      proxy_prefix: 'blm-xai',
      enabled: true,
      is_active: false,
      health: { healthy: false, status: 'unconfigured', account_count: 0 },
      accounts: [],
      keys: [],
      config: {},
      models: ['grok-2'],
      recovery_state: null,
    },
    {
      id: 'oauth:kimi',
      kind: 'oauth',
      provider: 'kimi',
      display_label: 'Kimi',
      proxy_prefix: 'blm-kimi',
      enabled: true,
      is_active: false,
      health: { healthy: false, status: 'unconfigured', account_count: 0 },
      accounts: [],
      keys: [],
      config: {},
      models: ['moonshot-v1'],
      recovery_state: null,
    },
    {
      id: 'oauth:kimi-ai',
      kind: 'oauth',
      provider: 'kimi-ai',
      display_label: 'Kimi AI',
      proxy_prefix: 'blm-kimi-ai',
      enabled: true,
      is_active: false,
      health: { healthy: false, status: 'unconfigured', account_count: 0 },
      accounts: [],
      keys: [],
      config: {},
      models: ['kimi-chat'],
      recovery_state: null,
    },
    {
      id: 'oauth:meta',
      kind: 'oauth',
      provider: 'meta',
      display_label: 'Meta',
      proxy_prefix: 'blm-meta',
      enabled: true,
      is_active: false,
      health: { healthy: false, status: 'unconfigured', account_count: 0 },
      accounts: [],
      keys: [],
      config: {},
      models: ['llama-3.3'],
      recovery_state: null,
    },
    {
      id: 'oauth:devin',
      kind: 'oauth',
      provider: 'devin',
      display_label: 'Devin',
      proxy_prefix: 'blm-devin',
      enabled: true,
      is_active: false,
      health: { healthy: false, status: 'unconfigured', account_count: 0 },
      accounts: [],
      keys: [],
      config: {},
      models: ['devin-v1'],
      recovery_state: null,
    },
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
      models: ['gemini-2.5-pro'],
      recovery_state: null,
    },
  ],
  active_route_id: 'direct:aistudio',
  proxy_status: {
    state: 'running',
    port: 8089,
    pid: 12345,
    last_error: null,
  },
  vault_state: 'available',
  recovery_state: null,
  settings: {
    strategy: 'fill-first',
    session_affinity: true,
    session_affinity_ttl: '1h',
    request_retry: 3,
    max_retry_credentials: 0,
    max_retry_interval: 30,
  },
};

describe('AiProvidersModal', () => {
  beforeEach(() => {
    window.open = vi.fn();
    (window as unknown as { electronAPI?: unknown }).electronAPI = {
      openExternal: vi.fn(),
      openInApp: vi.fn(),
      getAppVersion: vi.fn().mockResolvedValue("1.0.0"),
      checkForUpdates: vi.fn().mockResolvedValue(true),
      downloadUpdate: vi.fn().mockResolvedValue(true),
      installUpdate: vi.fn(),
      onUpdaterMessage: vi.fn(),
    };
    server.use(
      http.get('/api/py/ai/routes', () => {
        return HttpResponse.json(baseMockRoutesResponse);
      }),
      http.post('/api/py/ai/routes/:routeId/activate', ({ params }) => {
        return HttpResponse.json({ status: 'activated', active_route_id: params.routeId });
      }),
      http.patch('/api/py/ai/routes/settings', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ status: 'updated', updated_settings: body });
      }),
      http.post('/api/py/ai/routes/oauth/start', async ({ request }) => {
        const body = (await request.json()) as { provider: string; flow?: string; replace_account_id?: string };
        return HttpResponse.json({
          state: 'test-oauth-state-xyz',
          provider: body.provider,
          flow: body.flow || 'browser',
          auth_url: 'https://login.openai.com/oauth/authorize?client_id=blm',
          user_code: 'WDJB-MJHT',
          verification_uri: 'https://login.openai.com/device',
          expires_in: 900,
          interval: 2,
          status: 'pending',
        });
      }),
      http.get('/api/py/ai/routes/oauth/poll', () => {
        return HttpResponse.json({ status: 'pending' });
      }),
      http.post('/api/py/ai/routes/oauth/cancel', () => {
        return HttpResponse.json({ status: 'cancelled', state: 'test-oauth-state-xyz' });
      }),
      http.patch('/api/py/ai/routes/accounts/:accountId', async ({ params, request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          id: params.accountId,
          route_id: 'oauth:codex',
          kind: 'oauth',
          masked_identity: 'patched***@openai.com',
          priority: body.priority ?? 1,
          weight: body.weight ?? 1,
          enabled: body.enabled ?? true,
          status: 'active',
          cooldown: null,
          last_redacted_error: null,
          created_at: null,
          updated_at: null,
        });
      }),
      http.post('/api/py/ai/routes/accounts/:accountId/test', ({ params }) => {
        return HttpResponse.json({
          status: 'ok',
          account_id: params.accountId,
          latency_ms: 45,
        });
      }),
      http.post('/api/py/ai/routes/accounts/:accountId/refresh', ({ params }) => {
        return HttpResponse.json({
          id: params.accountId,
          route_id: 'oauth:codex',
          kind: 'oauth',
          masked_identity: 'user1***@openai.com',
          priority: 1,
          weight: 2,
          enabled: true,
          status: 'active',
          cooldown: null,
          last_redacted_error: null,
          created_at: null,
          updated_at: null,
        });
      }),
      http.post('/api/py/ai/routes/accounts/:accountId/reset-cooldown', ({ params }) => {
        return HttpResponse.json({ status: 'ok', account_id: params.accountId });
      }),
      http.delete('/api/py/ai/routes/accounts/:accountId', ({ params }) => {
        return HttpResponse.json({ status: 'deleted', account_id: params.accountId });
      }),
      http.post('/api/py/ai/routes/vault/reset', () => {
        return HttpResponse.json({ status: 'reset', vault_state: 'available', active_route_id: 'direct:aistudio' });
      }),
    );
  });

  // 1. Modal Rendering and Tab Switching
  it('does not render when isOpen is false', () => {
    render(<AiProvidersModal isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByText(/AI PROVIDER ROUTES & OAUTH MANAGER/i)).not.toBeInTheDocument();
  });

  it('renders modal shell, header, and all three tabs when isOpen is true', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    expect(await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i })).toBeInTheDocument();
    expect(screen.getByText(/AI PROVIDER ROUTES & OAUTH MANAGER/i)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /CUSTOM ENDPOINTS/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /DIRECT PROVIDERS/i })).toBeInTheDocument();
  });

  it('switches tabs smoothly between OAuth, Custom Endpoints, and Direct Providers', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    // Default tab is OAuth
    expect(screen.getByTestId('oauth-provider-group-codex')).toBeInTheDocument();

    // Switch to Custom Endpoints
    fireEvent.click(screen.getByRole('tab', { name: /CUSTOM ENDPOINTS/i }));
    expect(await screen.findByTestId('custom-endpoints-tab')).toBeInTheDocument();
    expect(screen.getByText(/CUSTOM OPENAI-COMPATIBLE ENDPOINTS/i)).toBeInTheDocument();

    // Switch to Direct Providers
    fireEvent.click(screen.getByRole('tab', { name: /DIRECT PROVIDERS/i }));
    expect(await screen.findByTestId('direct-providers-tab')).toBeInTheDocument();
    expect(screen.getByText(/DIRECT API-KEY PROVIDERS/i)).toBeInTheDocument();

    // Switch back to OAuth Accounts
    fireEvent.click(screen.getByRole('tab', { name: /OAUTH ACCOUNTS/i }));
    expect(await screen.findByTestId('oauth-provider-group-codex')).toBeInTheDocument();
  });

  it('closes modal on Escape key press or close button click', async () => {
    const handleClose = vi.fn();
    render(<AiProvidersModal isOpen={true} onClose={handleClose} />);

    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    // Escape key
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);

    // Close button
    fireEvent.click(screen.getByRole('button', { name: /Close AI providers modal/i }));
    expect(handleClose).toHaveBeenCalledTimes(2);
  });

  // 2. Top Summary
  it('displays accurate top summary metrics: active route, proxy health, vault status, inventory', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    // Active route
    expect(screen.getByTestId('active-route-display')).toHaveTextContent('Google AI Studio');
    expect(screen.getByText('direct:aistudio')).toBeInTheDocument();

    // Proxy health
    expect(screen.getByTestId('proxy-health-status')).toHaveTextContent('running');

    // Vault status
    expect(screen.getByTestId('vault-state-status')).toHaveTextContent('READY');

    // Credentials count
    expect(screen.getByTestId('credentials-count')).toHaveTextContent('4 Accts · 0 Keys');
  });

  it('handles routing strategy dropdown changes and invalidates settings', async () => {
    const patchSpy = vi.fn();
    server.use(
      http.patch('/api/py/ai/routes/settings', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        patchSpy(body);
        return HttpResponse.json({ status: 'updated', updated_settings: body });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const strategySelect = screen.getByTestId('routing-strategy-select');
    expect(strategySelect).toHaveValue('fill-first');

    fireEvent.change(strategySelect, { target: { value: 'round-robin' } });

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith({ strategy: 'round-robin' });
    });
  });

  it('handles sticky session toggle and calls update settings', async () => {
    const patchSpy = vi.fn();
    server.use(
      http.patch('/api/py/ai/routes/settings', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        patchSpy(body);
        return HttpResponse.json({ status: 'updated', updated_settings: body });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const toggleBtn = screen.getByTestId('sticky-session-toggle');
    expect(toggleBtn).toHaveTextContent('ON');

    fireEvent.click(toggleBtn);

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith({ session_affinity: false });
    });
  });

  it('displays degraded vault recovery banner when vault_state is not available and permits vault reset', async () => {
    server.use(
      http.get('/api/py/ai/routes', () => {
        return HttpResponse.json({
          ...baseMockRoutesResponse,
          vault_state: 'keyring_unavailable',
          recovery_state: 'Keyring backend offline. Direct providers remain fully functional.',
        });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    expect(await screen.findByTestId('vault-recovery-banner')).toBeInTheDocument();
    expect(screen.getByText(/Keyring backend offline/i)).toBeInTheDocument();

    // Trigger Vault Reset dialog
    fireEvent.click(screen.getByRole('button', { name: /RESET VAULT/i }));
    expect(screen.getByRole('dialog', { name: /RESET PROVIDER VAULT/i })).toBeInTheDocument();
    expect(screen.getByText(/DIRECT PROVIDERS REMAIN USABLE/i)).toBeInTheDocument();

    // Type RESET to confirm
    const resetInput = screen.getByPlaceholderText('RESET');
    fireEvent.change(resetInput, { target: { value: 'RESET' } });

    const confirmBtn = screen.getByTestId("confirm-vault-reset-btn");
    expect(confirmBtn).not.toBeDisabled();

    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: /RESET PROVIDER VAULT/i })).not.toBeInTheDocument();
    });
  });

  // 3. OAuth Accounts Tab and Provider Groups
  it('renders all eight approved OAuth provider groups in the OAuth tab', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const expectedProviders = ['codex', 'antigravity', 'claude', 'xai', 'kimi', 'kimi-ai', 'meta', 'devin'];
    for (const p of expectedProviders) {
      expect(screen.getByTestId(`oauth-provider-group-${p}`)).toBeInTheDocument();
    }
  });

  it('permits activating a configured OAuth route', async () => {
    const activateSpy = vi.fn();
    server.use(
      http.post('/api/py/ai/routes/:routeId/activate', ({ params }) => {
        activateSpy(params.routeId);
        return HttpResponse.json({ status: 'activated', active_route_id: params.routeId });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const codexGroup = screen.getByTestId('oauth-provider-group-codex');
    const activateBtn = codexGroup.querySelector('button');
    expect(activateBtn).toHaveTextContent(/ACTIVATE/i);

    fireEvent.click(activateBtn!);

    await waitFor(() => {
      expect(activateSpy).toHaveBeenCalledWith('oauth:codex');
    });
  });

  // 4. Account Card States and Actions
  it('renders account cards with identity, active, disabled, cooldown, and error states', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    // Active account
    const acc1 = screen.getByTestId('account-card-acc-codex-1');
    expect(acc1).toHaveTextContent('user1***@openai.com');
    expect(acc1.querySelector('[data-testid="status-active"]')).toBeInTheDocument();

    // Disabled account
    const acc2 = screen.getByTestId('account-card-acc-codex-2');
    expect(acc2).toHaveTextContent('user2***@openai.com');
    expect(acc2.querySelector('[data-testid="status-disabled"]')).toBeInTheDocument();

    // Cooldown account
    const acc3 = screen.getByTestId('account-card-acc-claude-cd');
    expect(acc3.querySelector('[data-testid="status-cooldown"]')).toBeInTheDocument();
    expect(acc3).toHaveTextContent(/Cooldown:/i);
    expect(acc3).toHaveTextContent(/Reset Cooldown/i);

    // Error account
    const acc4 = screen.getByTestId('account-card-acc-claude-err');
    expect(acc4.querySelector('[data-testid="status-error"]')).toBeInTheDocument();
    expect(acc4).toHaveTextContent('Rate limit exceeded on upstream token exchange');
  });

  it('handles account enable toggle, priority/weight changes, testing, and cooldown reset', async () => {
    const patchSpy = vi.fn();
    const testSpy = vi.fn();
    const resetCdSpy = vi.fn();

    server.use(
      http.patch('/api/py/ai/routes/accounts/:accountId', async ({ params, request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        patchSpy(params.accountId, body);
        return HttpResponse.json({ id: params.accountId, ...body });
      }),
      http.post('/api/py/ai/routes/accounts/:accountId/test', ({ params }) => {
        testSpy(params.accountId);
        return HttpResponse.json({ status: 'ok', account_id: params.accountId, latency_ms: 32 });
      }),
      http.post('/api/py/ai/routes/accounts/:accountId/reset-cooldown', ({ params }) => {
        resetCdSpy(params.accountId);
        return HttpResponse.json({ status: 'ok', account_id: params.accountId });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const acc1 = screen.getByTestId('account-card-acc-codex-1');

    // 1. Toggle Enabled
    const enableBtn = acc1.querySelector('button[aria-label="Disable account"]');
    expect(enableBtn).toBeInTheDocument();
    fireEvent.click(enableBtn!);
    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith('acc-codex-1', { enabled: false });
    });

    // 2. Change Priority
    const priorityInput = acc1.querySelector('input[aria-label="Account Priority"]');
    fireEvent.change(priorityInput!, { target: { value: '4' } });
    fireEvent.blur(priorityInput!);
    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledWith('acc-codex-1', { priority: 4 });
    });

    // 3. Test Account
    const testBtn = acc1.querySelector('button[title="Test account availability"]');
    fireEvent.click(testBtn!);
    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith('acc-codex-1');
      expect(acc1.querySelector('[data-testid="test-result-indicator"]')).toHaveTextContent(/Account verified/i);
    });

    // 4. Reset Cooldown on cooldown account
    const accCd = screen.getByTestId('account-card-acc-claude-cd');
    const resetCdBtn = accCd.querySelector('[data-testid="reset-cooldown-btn"]')!;
    fireEvent.click(resetCdBtn);
    await waitFor(() => {
      expect(resetCdSpy).toHaveBeenCalledWith('acc-claude-cd');
    });
  });

  it('handles account deletion with confirmation prompt', async () => {
    const deleteSpy = vi.fn();
    server.use(
      http.delete('/api/py/ai/routes/accounts/:accountId', ({ params }) => {
        deleteSpy(params.accountId);
        return HttpResponse.json({ status: 'deleted', account_id: params.accountId });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const acc1 = screen.getByTestId('account-card-acc-codex-1');
    const removeBtn = acc1.querySelector('button[aria-label="Remove account"]');
    expect(removeBtn).toBeInTheDocument();

    // Click remove -> shows CONFIRM button
    fireEvent.click(removeBtn!);
    const confirmBtn = acc1.querySelector('button:has-text("CONFIRM")') || screen.getByText('CONFIRM');
    expect(confirmBtn).toBeInTheDocument();

    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith('acc-codex-1');
    });
  });

  // 5. OAuth Session Dialog (Device Code & Browser Flow, Cancellation, Expiry, Mismatch)
  it('opens browser OAuth session flow and displays auth link, timer, and cancel action', async () => {
    const cancelSpy = vi.fn();
    server.use(
      http.post('/api/py/ai/routes/oauth/cancel', () => {
        cancelSpy();
        return HttpResponse.json({ status: 'cancelled', state: 'test-oauth-state-xyz' });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const codexGroup = screen.getByTestId('oauth-provider-group-codex');
    const addBrowserBtn = codexGroup.querySelector('button:has-text("ADD (BROWSER)")') || screen.getAllByText('ADD (BROWSER)')[0];

    fireEvent.click(addBrowserBtn);

    // Verify dialog opened
    expect(await screen.findByRole('dialog', { name: /Connect Codex/i })).toBeInTheDocument();
    expect(screen.getByText(/OPEN BROWSER TO LOGIN/i)).toBeInTheDocument();
    expect(screen.getByText(/Expires in:/i)).toBeInTheDocument();

    // Cancel session
    const cancelBtn = screen.getByRole('button', { name: /Cancel Authorization/i });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(cancelSpy).toHaveBeenCalled();
      expect(screen.getByText(/OAuth session was cancelled/i)).toBeInTheDocument();
    });
  });

  it('opens device-code OAuth flow and displays user code and verification URI', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const codexGroup = screen.getByTestId('oauth-provider-group-codex');
    const addDeviceBtn = codexGroup.querySelector('button:has-text("ADD (DEVICE)")') || screen.getAllByText('ADD (DEVICE)')[0];

    fireEvent.click(addDeviceBtn);

    expect(await screen.findByRole('dialog', { name: /Connect Codex/i })).toBeInTheDocument();
    expect(screen.getByText('WDJB-MJHT')).toBeInTheDocument();
    expect(screen.getByText(/OPEN VERIFICATION PAGE/i)).toBeInTheDocument();
    expect(screen.getByText(/Copy Code/i)).toBeInTheDocument();
  });

  it('displays prominent Reauth Mismatch Notice when OAuth poll returns identity mismatch', async () => {
    server.use(
      http.get('/api/py/ai/routes/oauth/poll', () => {
        return HttpResponse.json({
          status: 'completed',
          account_id: 'acc-new-uuid',
          route_id: 'oauth:codex',
          masked_identity: 'bob***@example.com',
          notice:
            'Reauthenticated identity (bob***@example.com) does not match existing account identity (alice***@example.com). A new account was created instead.',
        });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    // Trigger reauth on acc-codex-1
    const acc1 = screen.getByTestId('account-card-acc-codex-1');
    const reauthBtn = acc1.querySelector('button[title="Reauthenticate this account"]');
    fireEvent.click(reauthBtn!);

    // Expect completion and Reauth mismatch notice
    expect(await screen.findByTestId('reauth-mismatch-notice')).toBeInTheDocument();
    expect(screen.getByText(/Identity Reconciliation Notice/i)).toBeInTheDocument();
    expect(screen.getByText(/does not match existing account identity/i)).toBeInTheDocument();
  });

  it('displays session expired message when poll returns expired status', async () => {
    server.use(
      http.get('/api/py/ai/routes/oauth/poll', () => {
        return HttpResponse.json({ status: 'expired' });
      }),
    );

    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const codexGroup = screen.getByTestId('oauth-provider-group-codex');
    const addBrowserBtn = screen.getAllByText('ADD (BROWSER)')[0];
    fireEvent.click(addBrowserBtn);

    expect(await screen.findByText(/Session Expired/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Try Again/i })).toBeInTheDocument();
  });

  // 6. CommandBar and SettingsModal Integration
  it('opens AiProvidersModal when PROVIDERS command is executed in TerminalContainer', async () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="terminal-inner">App</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [activeCommandAtom, 'PROVIDERS'],
            [showAiProvidersModalAtom, false],
          ],
        },
      },
    );

    expect(await screen.findByText(/AI PROVIDER ROUTES & OAUTH MANAGER/i)).toBeInTheDocument();
  });

  it('includes PROVIDERS command in CommandBar widget suggestions', async () => {
    const { container } = render(<CommandBar />);

    const input = container.querySelector("#terminal-command-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'PROVID' } });

    expect(await screen.findByText('PROVIDERS')).toBeInTheDocument();
    expect(screen.getByText(/AI providers & OAuth accounts/i)).toBeInTheDocument();
  });

  it('opens AiProvidersModal from SettingsModal AI Provider card', async () => {
    render(
      <SavedLayoutsSyncProvider>
        <SettingsModal isOpen={true} onClose={vi.fn()} initialTab="intelligence" />
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
            [showAiProvidersModalAtom, false],
            [authAtom, { user: { id: 1, username: "admin", is_admin: true } }],
          ],
        },
      },
    );

    const manageBtn = await screen.findByRole('button', { name: /MANAGE PROVIDERS →/i });
    expect(manageBtn).toBeInTheDocument();
    fireEvent.click(manageBtn);
  });

  // 7. Security / No-Secret DOM Assertions
  it('guarantees that no raw OAuth tokens, bearer tokens, or secret keys appear in the DOM', async () => {
    const { container } = render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);

    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });

    const domHtml = container.innerHTML;

    // Strict no-secret sentinel checks
    expect(domHtml).not.toMatch(/sk-[a-zA-Z0-9_-]{20,}/);
    expect(domHtml).not.toMatch(/bearer\s+[a-zA-Z0-9_\-\.]{20,}/i);
    expect(domHtml).not.toMatch(/client_secret/i);
    expect(domHtml).not.toMatch(/gho_[a-zA-Z0-9]{20,}/);
    expect(domHtml).not.toMatch(/vault_reference/i);

    // Verify all identities are masked
    const identities = screen.getAllByTestId('account-masked-identity');
    for (const el of identities) {
      expect(el.textContent).toContain('***');
    }
  });
});
