import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import * as route from '@/app/api/py/[...path]/route';

/**
 * Next.js answers a request with 405 when the route module does not export a
 * handler for that method. The Python backend never sees the call, so a
 * missing export silently breaks every caller. PATCH was missing and took
 * workflow pause, workflow edit, and prompt edit down together.
 */
const REQUIRED_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const;

describe('/api/py catch-all proxy', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each(REQUIRED_METHODS)('exports a %s handler', (method) => {
    const handler = (route as unknown as Record<string, unknown>)[method];
    expect(typeof handler).toBe('function');
  });

  it('forwards a PATCH body and method to the backend', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ id: 1, is_enabled: false }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const request = new NextRequest('http://localhost/api/py/ai/workflows/1', {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ is_enabled: false }),
    });

    const response = await route.PATCH(request, {
      params: Promise.resolve({ path: ['ai', 'workflows', '1'] }),
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.method).toBe('PATCH');
    expect(init?.body).toBe('{"is_enabled":false}');
    expect(response.status).toBe(200);
  });
});
