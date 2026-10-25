/**
 * Type definitions for AI Provider Routes, Credentials, Routing Settings, and OAuth flows.
 * Aligns with backend schemas in app/schemas/ai_provider.py.
 */

export interface CredentialSummary {
  id: string;
  route_id: string;
  kind: 'oauth' | 'custom' | 'direct' | string;
  masked_identity: string;
  priority: number;
  weight: number;
  enabled: boolean;
  status: 'active' | 'cooldown' | 'error' | 'disabled' | string;
  cooldown: string | null;
  last_redacted_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RouteHealth {
  healthy: boolean;
  status: 'active' | 'configured' | 'unconfigured' | string;
  proxy_status?: string;
  account_count?: number;
  key_count?: number;
  transport?: 'proxy' | 'direct' | string;
}

export interface RouteConfigSummary {
  base_url?: string;
  warning_flags?: string[];
  has_headers?: boolean;
  header_names?: string[];
  is_configured?: boolean;
  transport?: 'proxy' | 'direct' | string;
  [key: string]: unknown;
}

export interface RouteSummary {
  id: string;
  kind: 'oauth' | 'endpoint' | 'direct';
  provider: string;
  display_label: string;
  proxy_prefix: string | null;
  enabled: boolean;
  is_active: boolean;
  health: RouteHealth;
  accounts: CredentialSummary[];
  keys: CredentialSummary[];
  config: RouteConfigSummary;
  models: string[];
  recovery_state: string | null;
}

export interface ProxyStatus {
  state: 'running' | 'stopped' | 'starting' | 'crashed' | 'disabled' | string;
  pid?: number | null;
  port?: number | null;
  uptime_seconds?: number;
  last_error?: string | null;
  restart_count?: number;
}

export type RoutingStrategy = 'fill-first' | 'round-robin' | 'priority';

export interface RouteSettings {
  strategy: RoutingStrategy | string;
  session_affinity: boolean;
  session_affinity_ttl: string;
  request_retry: number;
  max_retry_credentials: number;
  max_retry_interval: number;
}

export interface RouteSettingsUpdate {
  strategy?: string;
  session_affinity?: boolean;
  session_affinity_ttl?: string;
  request_retry?: number;
  max_retry_credentials?: number;
  max_retry_interval?: number;
}

export interface RoutesListResponse {
  routes: RouteSummary[];
  active_route_id: string;
  proxy_status: ProxyStatus;
  vault_state: 'available' | 'keyring_unavailable' | 'vault_corrupt' | string;
  recovery_state: string | null;
  settings: RouteSettings;
}

export interface RouteModelCatalogModel {
  id: string;
  label: string;
}

export interface RouteModelCatalogEntry {
  route_id: string;
  label: string;
  kind: string;
  provider: string;
  models: RouteModelCatalogModel[];
}

export interface RouteModelCatalogWarning {
  route_id: string;
  code: string;
  message: string;
}

export interface RouteModelCatalogResponse {
  routes: RouteModelCatalogEntry[];
  warnings: RouteModelCatalogWarning[];
}

export type OAuthCallbackMode = 'loopback' | 'manual';

export interface OAuthStartRequest {
  provider: string;
  flow?: 'browser';
  replace_account_id?: string | null;
}

export interface OAuthStartResponse {
  state: string;
  provider: string;
  flow?: 'browser';
  callback_mode: OAuthCallbackMode;
  callback_url: string | null;
  auth_url?: string | null;
  user_code?: string | null;
  verification_uri?: string | null;
  expires_in: number;
  interval: number;
  status: string;
}

export interface OAuthCallbackRequest {
  state: string;
  code?: string | null;
  redirect_url?: string | null;
}

export interface OAuthPollResponse {
  status: 'pending' | 'reconciling' | 'completed' | 'expired' | 'cancelled' | 'failed' | string;
  message?: string;
  account_id?: string;
  route_id?: string;
  masked_identity?: string;
  notice?: string | null;
  error?: string | null;
  provider?: string;
}

export interface AccountPatchRequest {
  priority?: number;
  weight?: number;
  enabled?: boolean;
  status?: string;
}

export interface AccountTestResponse {
  status: 'ok' | 'error' | string;
  account_id: string;
  masked_identity?: string;
  proxy_status?: string;
  latency_ms: number;
  error?: string;
}

export interface VaultResetResponse {
  status: string;
  vault_state: string;
  active_route_id: string;
}
export interface EndpointKeyInput {
  api_key: string;
  label?: string;
  priority?: number;
  weight?: number;
}

export interface EndpointKeyUpdate {
  priority?: number;
  weight?: number;
  enabled?: boolean;
  status?: string;
}

export interface CreateEndpointRequest {
  display_label: string;
  base_url: string;
  headers?: Record<string, string>;
  models?: string[];
  keys?: EndpointKeyInput[];
}

export interface UpdateEndpointRequest {
  display_label?: string;
  base_url?: string;
  headers?: Record<string, string>;
  models?: string[];
  enabled?: boolean;
}

export interface ModelPreviewRequest {
  base_url: string;
  headers?: Record<string, string>;
  api_key?: string;
}

export interface ModelPreviewResponse {
  models: string[];
  notice?: string;
}

export interface EndpointTestResponse {
  status: 'ok' | 'error' | string;
  route_id: string;
  status_code?: number;
  latency_ms: number;
  error?: string;
}
