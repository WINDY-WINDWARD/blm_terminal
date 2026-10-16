/**
 * Regression test for the multipart binary proxy bug in
 * `src/app/api/py/[...path]/route.ts`.
 *
 * Bug: every non-GET body was read with `request.text()`, which decodes the
 * body as UTF-8 with replacement characters. A PDF upload therefore reached
 * FastAPI with corrupted bytes and pypdf failed to parse it. The route now
 * reads multipart bodies with `request.arrayBuffer()` so the file survives
 * the hop byte-for-byte.
 */

import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { POST } from '@/app/api/py/[...path]/route';

const BOUNDARY = '----BLMUploadBoundary7f3a';

function buildMultipartBody(): Uint8Array<ArrayBuffer> {
  const encoder = new TextEncoder();
  const head = encoder.encode(
    `--${BOUNDARY}\r\n` +
      'Content-Disposition: form-data; name="file"; filename="annual-report.pdf"\r\n' +
      'Content-Type: application/pdf\r\n\r\n',
  );
  // A lone byte sequence that is not valid UTF-8: a text() round-trip would
  // turn 0xff 0xfe 0x80 into U+FFFD replacement characters.
  const fileBytes = new Uint8Array([
    0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34,
    0xff, 0xfe, 0x80, 0xbf, 0xc0, 0xc3, 0x00, 0x9c, 0xf3, 0x0a,
  ]);
  const tail = encoder.encode(`\r\n--${BOUNDARY}--\r\n`);

  const body = new Uint8Array(new ArrayBuffer(head.length + fileBytes.length + tail.length));
  body.set(head, 0);
  body.set(fileBytes, head.length);
  body.set(tail, head.length + fileBytes.length);
  return body;
}

function buildUploadRequest(body: BodyInit): NextRequest {
  return new NextRequest('http://localhost/api/py/ai/documents/upload?source=chat', {
    method: 'POST',
    headers: { 'content-type': `multipart/form-data; boundary=${BOUNDARY}` },
    body,
  });
}

const UPLOAD_PARAMS = { params: Promise.resolve({ path: ['ai', 'documents', 'upload'] }) };

describe('POST /api/py/[...path] — multipart proxying', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    process.env.PYTHON_BACKEND_URL = 'http://127.0.0.1:4455';
    fetchSpy = vi.fn(
      async () =>
        new Response(JSON.stringify({ id: 7 }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    );
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.PYTHON_BACKEND_URL;
  });

  it('forwards multipart PDF bytes to FastAPI unchanged', async () => {
    const body = buildMultipartBody();

    const response = await POST(buildUploadRequest(body), UPLOAD_PARAMS);

    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:4455/api/ai/documents/upload?source=chat');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(ArrayBuffer);

    const forwarded = new Uint8Array(init.body as ArrayBuffer);
    expect(forwarded.byteLength).toBe(body.byteLength);
    expect(Array.from(forwarded)).toEqual(Array.from(body));
  });

  it('preserves the multipart boundary in the upstream content-type', async () => {
    await POST(buildUploadRequest(buildMultipartBody()), UPLOAD_PARAMS);

    const headers = fetchSpy.mock.calls[0][1].headers as Headers;
    expect(headers.get('content-type')).toBe(`multipart/form-data; boundary=${BOUNDARY}`);
  });

  it('still forwards JSON bodies as text', async () => {
    const payload = JSON.stringify({ session_id: 3, document_ids: [1] });
    const request = new NextRequest('http://localhost/api/py/ai/documents/attach', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: payload,
    });

    await POST(request, { params: Promise.resolve({ path: ['ai', 'documents', 'attach'] }) });

    expect(fetchSpy.mock.calls[0][1].body).toBe(payload);
  });
});
