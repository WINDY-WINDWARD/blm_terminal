import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/msw-server';
import { render, screen, fireEvent, waitFor, createTestQueryClient } from '../utils/renderWithProviders';
import { QueryClientProvider } from '@tanstack/react-query';
import { VaultResetModal } from '@/components/modals/AiProvidersModal/VaultResetModal';
import { OAuthAccountCard } from '@/components/modals/AiProvidersModal/OAuthAccountCard';
import { useUpdateRouteSettingsMutation } from '@/hooks/useAiRoutes';
import { AiProvidersModal } from '@/components/modals/AiProvidersModal';
import { AiProvidersModalHost } from '@/components/modals/AiProvidersModalHost';
import { CustomEndpointsTab } from '@/components/modals/AiProvidersModal/CustomEndpointsTab';
import { EndpointEditorModal } from '@/components/modals/AiProvidersModal/EndpointEditorModal';
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
import type { RoutesListResponse, CredentialSummary, RouteSummary } from '@/types/aiRoutes';


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
      proxy_prefix: 'blm-303883bf0c4964ae',
      enabled: true,
      is_active: true,
      health: { healthy: true, status: 'active', transport: 'proxy' },
      accounts: [],
      keys: [],
      config: { is_configured: true, transport: 'proxy' },
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



describe('AiProvidersStaleBanner', () => {
  beforeEach(() => {
    window.open = vi.fn();
    server.use(http.get('/api/py/ai/routes', () => HttpResponse.json(baseMockRoutesResponse)));
  });

  it('shows cached data without failure banner on initial load', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });
    expect(await screen.findByTestId('active-route-display')).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load provider routes/i)).not.toBeInTheDocument();
  });

  it('hides failure banner when background refetch fails but cached data exists', async () => {
    render(<AiProvidersModal isOpen={true} onClose={vi.fn()} />);
    await screen.findByRole('tab', { name: /OAUTH ACCOUNTS/i });
    expect(await screen.findByTestId('active-route-display')).toBeInTheDocument();
  });
});
