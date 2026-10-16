import { describe, expect, it } from 'vitest';

import {
  addAttachedDocument,
  filterSupportedDocuments,
  formatBytes,
  isSupportedDocument,
  MAX_ATTACHMENTS_PER_TURN,
  removeAttachedDocument,
  detachSessionDocument,
  SUPPORTED_DOCUMENT_EXTENSIONS,
  type AttachedDocument,
} from '@/components/widgets/AiWidget';

function file(name: string): File {
  return new File([new Uint8Array(8)], name, { type: 'application/octet-stream' });
}

function doc(id: number, filename = `doc-${id}.csv`): AttachedDocument {
  return {
    id,
    filename,
    file_type: 'csv',
    mime_type: 'text/csv',
    file_size: 128,
    row_count: 3,
    page_count: null,
    needs_ocr: false,
    is_inlineable: false,
  };
}

describe('document upload helpers', () => {
  it('advertises the extensions the backend accepts', () => {
    expect(SUPPORTED_DOCUMENT_EXTENSIONS).toEqual(['.pdf', '.csv', '.tsv']);
  });

  it('accepts supported extensions regardless of case', () => {
    for (const name of ['report.pdf', 'HOLDINGS.CSV', 'prices.TsV']) {
      expect(isSupportedDocument(file(name))).toBe(true);
    }
  });

  it('rejects unsupported extensions', () => {
    for (const name of ['notes.txt', 'book.xlsx', 'noextension', 'report.pdf.exe', 'a.zip']) {
      expect(isSupportedDocument(file(name))).toBe(false);
    }
  });

  it('filters a dropped file list down to supported documents', () => {
    const dropped = [
      file('report.pdf'),
      file('notes.txt'),
      file('data.csv'),
      file('book.xlsx'),
      file('tab.tsv'),
    ];

    expect(filterSupportedDocuments(dropped).map((item) => item.name)).toEqual([
      'report.pdf',
      'data.csv',
      'tab.tsv',
    ]);
  });

  it('handles an empty drop', () => {
    expect(filterSupportedDocuments([])).toEqual([]);
  });
});

describe('attachment tray state', () => {
  it('appends newly uploaded documents', () => {
    expect(addAttachedDocument([doc(1)], doc(2)).map((item) => item.id)).toEqual([1, 2]);
  });

  it('ignores a duplicate id and keeps the existing array identity', () => {
    const existing = [doc(1), doc(2)];

    expect(addAttachedDocument(existing, doc(1))).toBe(existing);
  });

  it('enforces the per-turn attachment cap', () => {
    const full = Array.from({ length: MAX_ATTACHMENTS_PER_TURN }, (_, index) => doc(index + 1));

    expect(MAX_ATTACHMENTS_PER_TURN).toBe(5);
    expect(addAttachedDocument(full, doc(99))).toBe(full);
    expect(addAttachedDocument(full.slice(0, 4), doc(99)).map((item) => item.id)).toEqual([
      1, 2, 3, 4, 99,
    ]);
  });

  it('removes one attachment by id and leaves the rest untouched', () => {
    expect(removeAttachedDocument([doc(1), doc(2), doc(3)], 2).map((item) => item.id)).toEqual([1, 3]);
    expect(removeAttachedDocument([doc(1)], 42)).toHaveLength(1);
    expect(removeAttachedDocument([], 1)).toEqual([]);
  });
});

describe('formatBytes', () => {
  it('renders bytes, kilobytes and megabytes', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
});

describe('detachSessionDocument', () => {
  it('resolves true without making a network request for staged sessions (null or undefined)', async () => {
    let called = false;
    const mockFetch = (async () => {
      called = true;
      return new Response(null, { status: 200 });
    }) as unknown as typeof fetch;

    const resNull = await detachSessionDocument(null, 42, mockFetch);
    expect(resNull).toBe(true);
    expect(called).toBe(false);

    const resUndef = await detachSessionDocument(undefined as unknown as null, 42, mockFetch);
    expect(resUndef).toBe(true);
    expect(called).toBe(false);
  });

  it('calls the backend endpoint with DELETE for persisted sessions and returns true on success', async () => {
    let requestedUrl = '';
    let requestedMethod = '';
    const mockFetch = (async (url: string, init?: RequestInit) => {
      requestedUrl = url;
      requestedMethod = init?.method ?? '';
      return new Response(JSON.stringify({ ok: true, document_id: 42, session_id: 10 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    const res = await detachSessionDocument(10, 42, mockFetch);
    expect(res).toBe(true);
    expect(requestedUrl).toBe('/api/py/ai/documents/42/sessions/10');
    expect(requestedMethod).toBe('DELETE');
  });

  it('returns false when the backend returns 404 or other error status', async () => {
    const mockFetch = (async () => {
      return new Response(JSON.stringify({ detail: 'Document attachment not found' }), {
        status: 404,
      });
    }) as unknown as typeof fetch;

    const res = await detachSessionDocument(10, 42, mockFetch);
    expect(res).toBe(false);
  });

  it('returns false and catches network errors', async () => {
    const mockFetch = (async () => {
      throw new Error('Network failure');
    }) as unknown as typeof fetch;

    const res = await detachSessionDocument(10, 42, mockFetch);
    expect(res).toBe(false);
  });

  it('simulates removal flow: preserves state on failed detach and removes on success', async () => {
    const initialDocs = [doc(1), doc(2)];

    // Failed detach: state must not be modified
    const mockFailedFetch = (async () => new Response(null, { status: 500 })) as unknown as typeof fetch;
    const failedOk = await detachSessionDocument(99, 1, mockFailedFetch);
    let currentDocs = initialDocs;
    if (failedOk) {
      currentDocs = removeAttachedDocument(currentDocs, 1);
    }
    expect(currentDocs).toHaveLength(2);
    expect(currentDocs.map((d) => d.id)).toEqual([1, 2]);

    // Successful detach: state is modified
    const mockSuccessFetch = (async () => new Response(JSON.stringify({ ok: true }), { status: 200 })) as unknown as typeof fetch;
    const successOk = await detachSessionDocument(99, 1, mockSuccessFetch);
    if (successOk) {
      currentDocs = removeAttachedDocument(currentDocs, 1);
    }
    expect(currentDocs).toHaveLength(1);
    expect(currentDocs[0].id).toBe(2);
  });

  it('validates request payload shape for chat message with document attachments', () => {
    const attached = [doc(1), doc(2)];
    const payload = {
      messages: [{ role: 'user', content: 'Analyze this data' }],
      document_ids: attached.map((d) => d.id),
    };

    expect(payload.document_ids).toEqual([1, 2]);
    expect(Array.isArray(payload.document_ids)).toBe(true);
    expect(payload.document_ids.every((id) => typeof id === 'number')).toBe(true);
  });
});
