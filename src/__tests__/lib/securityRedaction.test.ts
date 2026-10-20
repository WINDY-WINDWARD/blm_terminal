import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getBackendForwardHeaders, getServerInternalHeaders } from '@/lib/backendUrl';
import { GET as catchAllGet, POST as catchAllPost } from '@/app/api/py/[...path]/route';
import { GET as healthGet } from '@/app/api/openalgo/health/route';
import { GET as wsTokenGet } from '@/app/api/openalgo/ws-token/route';

const SENTINEL_INTERNAL_TOKEN = 'sentinel_internal_server_token_xyz_9988';
const SENTINEL_CLIENT_TOKEN = 'sentinel_malicious_browser_internal_token_1122';
const SENTINEL_OPENALGO_KEY = 'sentinel_openalgo_api_key_secret_556677';

describe('Security Redaction & Internal Token Boundary', () => {
  beforeEach(() => {
    process.env.PYTHON_BACKEND_URL = 'http://127.0.0.1:4455';
    process.env.BLM_INTERNAL_TOKEN = SENTINEL_INTERNAL_TOKEN;
    delete process.env.BLM_LOCAL_TOKEN;
  });

  afterEach(() => {
    delete process.env.PYTHON_BACKEND_URL;
    delete process.env.BLM_INTERNAL_TOKEN;
    delete process.env.BLM_LOCAL_TOKEN;
    vi.unstubAllGlobals();
  });

  describe('getBackendForwardHeaders', () => {
    it('never forwards client-supplied x-blm-internal-token or x-blm-server-token', () => {
      const req = new NextRequest('http://localhost/api/test', {
        headers: {
          'x-blm-internal-token': SENTINEL_CLIENT_TOKEN,
          'x-blm-server-token': SENTINEL_CLIENT_TOKEN,
          authorization: 'Bearer valid_user_jwt',
        },
      });

      const forwarded = getBackendForwardHeaders(req);

      expect(forwarded.has('x-blm-internal-token')).toBe(false);
      expect(forwarded.has('x-blm-server-token')).toBe(false);
      expect(forwarded.get('authorization')).toBe('Bearer valid_user_jwt');
      // Assert sentinel client token is completely absent from all header values
      for (const [, val] of forwarded.entries()) {
        expect(val).not.toContain(SENTINEL_CLIENT_TOKEN);
      }
    });

    it('forwards desktop Electron x-blm-token when present on request', () => {
      const req = new NextRequest('http://localhost/api/test', {
        headers: {
          'x-blm-token': 'desktop-launch-token-123',
        },
      });

      const forwarded = getBackendForwardHeaders(req);
      expect(forwarded.get('x-blm-token')).toBe('desktop-launch-token-123');
    });

    it('falls back to BLM_LOCAL_TOKEN if request has no launch token', () => {
      process.env.BLM_LOCAL_TOKEN = 'server-local-token-999';
      const forwarded = getBackendForwardHeaders(null);
      expect(forwarded.get('x-blm-token')).toBe('server-local-token-999');
    });
  });

  describe('getServerInternalHeaders', () => {
    it('sets x-blm-server-token from process.env.BLM_INTERNAL_TOKEN', () => {
      const headers = getServerInternalHeaders({ accept: 'application/json' });
      expect(headers.get('x-blm-server-token')).toBe(SENTINEL_INTERNAL_TOKEN);
      expect(headers.get('accept')).toBe('application/json');
    });
  });

  describe('Next.js catch-all proxy /api/py/[...path]', () => {
    it('strips client-supplied internal tokens and never forwards them to upstream', async () => {
      let capturedHeaders: Headers | null = null;
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, init?: RequestInit) => {
          capturedHeaders = new Headers(init?.headers);
          return new Response(JSON.stringify({ status: 'ok' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          });
        }),
      );

      const clientReq = new NextRequest('http://localhost/api/py/some/endpoint', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-blm-internal-token': SENTINEL_CLIENT_TOKEN,
          'x-blm-server-token': SENTINEL_CLIENT_TOKEN,
          'x-blm-token': 'client-launch-token-abc',
        },
        body: JSON.stringify({ test: true }),
      });

      const res = await catchAllPost(clientReq, {
        params: Promise.resolve({ path: ['some', 'endpoint'] }),
      });

      expect(res.status).toBe(200);
      expect(capturedHeaders).not.toBeNull();
      expect(capturedHeaders!.has('x-blm-internal-token')).toBe(false);
      expect(capturedHeaders!.has('x-blm-server-token')).toBe(false);

      // Verify sentinel client token never appears in any forwarded headers
      for (const [, val] of capturedHeaders!.entries()) {
        expect(val).not.toContain(SENTINEL_CLIENT_TOKEN);
      }

      // Verify the separate server-only internal token was NOT forwarded to the client endpoint
      expect(capturedHeaders!.has('x-blm-server-token')).toBe(false);
    });
  });

  describe('OpenAlgo server routes credential resolution', () => {
    it('GET /api/openalgo/health calls the internal credentials endpoint and does not leak key', async () => {
      delete process.env.OPENALGO_URL;
      delete process.env.OPENALGO_API_KEY;

      const fetchCalls: { url: string; headers: Headers }[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const u = String(url);
          fetchCalls.push({ url: u, headers: new Headers(init?.headers) });

          if (u.includes('/api/system-config/openalgo-credentials')) {
            // Verify internal token was presented
            const authHeader = init?.headers ? new Headers(init.headers).get('x-blm-server-token') : null;
            if (authHeader !== SENTINEL_INTERNAL_TOKEN) {
              return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 });
            }
            return new Response(
              JSON.stringify({
                url: 'http://127.0.0.1:5000',
                api_key: SENTINEL_OPENALGO_KEY,
                configured: true,
              }),
              { status: 200, headers: { 'content-type': 'application/json' } },
            );
          }

          if (u.includes('/api/v1/funds')) {
            return new Response(JSON.stringify({ status: 'success' }), {
              status: 200,
              headers: { 'content-type': 'application/json' },
            });
          }

          return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
        }),
      );

      const req = new NextRequest('http://localhost/api/openalgo/health');
      const res = await healthGet(req);

      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.available).toBe(true);

      // Assert sentinel secret never appears in the renderer health response
      const responseText = JSON.stringify(json);
      expect(responseText).not.toContain(SENTINEL_OPENALGO_KEY);

      // Verify internal endpoint was called with server internal token
      const internalCall = fetchCalls.find((c) => c.url.includes('/api/system-config/openalgo-credentials'));
      expect(internalCall).toBeDefined();
      expect(internalCall!.headers.get('x-blm-server-token')).toBe(SENTINEL_INTERNAL_TOKEN);

      // Verify no secrets in request URLs
      for (const call of fetchCalls) {
        expect(call.url).not.toContain(SENTINEL_OPENALGO_KEY);
      }
    });

    it('GET /api/openalgo/ws-token retrieves key via internal endpoint for authenticated websocket', async () => {
      delete process.env.OPENALGO_API_KEY;

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const u = String(url);
          if (u.includes('/api/system-config/openalgo-credentials')) {
            const authHeader = init?.headers ? new Headers(init.headers).get('x-blm-server-token') : null;
            if (authHeader !== SENTINEL_INTERNAL_TOKEN) {
              return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 });
            }
            return new Response(
              JSON.stringify({
                url: 'http://127.0.0.1:5000',
                api_key: SENTINEL_OPENALGO_KEY,
                configured: true,
              }),
              { status: 200, headers: { 'content-type': 'application/json' } },
            );
          }
          return new Response(JSON.stringify({ error: 'not found' }), { status: 404 });
        }),
      );

      const req = new NextRequest('http://localhost/api/openalgo/ws-token');
      const res = await wsTokenGet(req);

      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.api_key).toBe(SENTINEL_OPENALGO_KEY);
    });
  });
  describe('OpenAlgoServerClient', () => {
    it('uses credentials fetched from internal endpoint to call OpenAlgo API', async () => {
      delete process.env.OPENALGO_URL;
      delete process.env.OPENALGO_API_KEY;

      const { OpenAlgoServerClient } = await import('@/lib/openalgo-server');

      const fetchUrls: string[] = [];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const u = String(url);
          fetchUrls.push(u);

          if (u.includes('/api/system-config/openalgo-credentials')) {
            const authHeader = init?.headers ? new Headers(init.headers).get('x-blm-server-token') : null;
            if (authHeader !== SENTINEL_INTERNAL_TOKEN) {
              return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 });
            }
            return new Response(
              JSON.stringify({
                url: 'http://127.0.0.1:5000',
                api_key: SENTINEL_OPENALGO_KEY,
                configured: true,
              }),
              { status: 200, headers: { 'content-type': 'application/json' } },
            );
          }

          if (u.includes('/api/v1/funds')) {
            const body = JSON.parse(String(init?.body || '{}'));
            expect(body.apikey).toBe(SENTINEL_OPENALGO_KEY);
            return new Response(
              JSON.stringify({
                status: 'success',
                data: { availablecash: '100000' },
              }),
              { status: 200, headers: { 'content-type': 'application/json' } },
            );
          }

          return new Response(JSON.stringify({ error: 'not found' }), { status: 404 });
        }),
      );

      const funds = await OpenAlgoServerClient.getFunds();
      expect(funds.status).toBe('success');
      expect(fetchUrls.some((u) => u.includes('/api/system-config/openalgo-credentials'))).toBe(true);
      expect(fetchUrls.some((u) => u.includes('/api/v1/funds'))).toBe(true);

      // Verify no secrets appeared in request URLs
      for (const u of fetchUrls) {
        expect(u).not.toContain(SENTINEL_OPENALGO_KEY);
      }
    });
  });
});
