import { describe, expect, it } from 'vitest';

import {
  addAttachedDocument,
  filterSupportedDocuments,
  formatBytes,
  isSupportedDocument,
  MAX_ATTACHMENTS_PER_TURN,
  removeAttachedDocument,
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
