'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  addAttachedDocument,
  filterSupportedDocuments,
  isSupportedDocument,
  removeAttachedDocument,
  detachSessionDocument,
  MAX_ATTACHMENTS_PER_TURN,
  type AttachedDocument,
  type SessionState,
} from '@/types/aiWidgetTypes';

export interface UploadJob {
  tempId: string;
  filename: string;
  progress: number;
  error?: string;
}

export interface UseAiDocumentsOptions {
  activeKey: number | null;
  sessionMap: Map<number | null, SessionState>;
  setSessionMap: React.Dispatch<React.SetStateAction<Map<number | null, SessionState>>>;
  defaultModel: string;
}

export interface UseAiDocumentsReturn {
  libraryDocuments: AttachedDocument[];
  uploadJobs: UploadJob[];
  dragActive: boolean;
  setDragActive: (active: boolean) => void;
  refreshLibrary: () => Promise<void>;
  uploadFile: (file: File) => void;
  removeSessionDocument: (documentId: number) => Promise<void>;
  attachLibraryDocument: (document: AttachedDocument) => void;
  deleteLibraryDocument: (documentId: number) => Promise<void>;
  handleDocumentDrop: (event: React.DragEvent<HTMLDivElement>) => void;
}

export function useAiDocuments({
  activeKey,
  sessionMap,
  setSessionMap,
  defaultModel,
}: UseAiDocumentsOptions): UseAiDocumentsReturn {
  const [libraryDocuments, setLibraryDocuments] = useState<AttachedDocument[]>([]);
  const [uploadJobs, setUploadJobs] = useState<UploadJob[]>([]);
  const [dragActive, setDragActive] = useState(false);

  const refreshLibrary = useCallback(async () => {
    try {
      const res = await fetch('/api/py/ai/documents');
      if (!res.ok) return;
      setLibraryDocuments((await res.json()) as AttachedDocument[]);
    } catch (err) {
      console.error('Failed to load document library:', err);
    }
  }, []);

  useEffect(() => {
    void refreshLibrary();
  }, [refreshLibrary]);

  const uploadFile = useCallback(
    (file: File) => {
      const targetKey = activeKey;
      if (!isSupportedDocument(file)) {
        setUploadJobs((prev) => [
          ...prev,
          { tempId: `${Date.now()}-${file.name}`, filename: file.name, progress: 0, error: 'Unsupported file type' },
        ]);
        return;
      }
      if (file.size > 50 * 1024 * 1024) {
        setUploadJobs((prev) => [
          ...prev,
          { tempId: `${Date.now()}-${file.name}`, filename: file.name, progress: 0, error: 'File is larger than 50 MB' },
        ]);
        return;
      }
      const currentDocuments = sessionMap.get(targetKey)?.documents ?? [];
      if (currentDocuments.length >= MAX_ATTACHMENTS_PER_TURN) {
        setUploadJobs((prev) => [
          ...prev,
          { tempId: `${Date.now()}-${file.name}`, filename: file.name, progress: 0, error: 'Attachment limit reached (5)' },
        ]);
        return;
      }

      const tempId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setUploadJobs((prev) => [...prev, { tempId, filename: file.name, progress: 0 }]);

      const form = new FormData();
      form.append('file', file);
      if (typeof targetKey === 'number') form.append('session_id', String(targetKey));

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/py/ai/documents/upload');
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const progress = Math.round((event.loaded / event.total) * 100);
        setUploadJobs((prev) => prev.map((job) => (job.tempId === tempId ? { ...job, progress } : job)));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const document = JSON.parse(xhr.responseText) as AttachedDocument;
            setSessionMap((prev) => {
              const next = new Map(prev);
              const currentState = next.get(targetKey) ?? {
                messages: [],
                isStreaming: false,
                toolsDone: false,
                input: '',
                model: defaultModel,
                mode: 'research' as const,
                documents: [],
                abortController: null,
              };
              const existing = currentState.documents ?? [];
              const merged = addAttachedDocument(existing, document);
              if (merged !== existing) {
                next.set(targetKey, { ...currentState, documents: merged });
              }
              return next;
            });
          } catch (err) {
            console.error('Upload response parse failed:', err);
          }
          setUploadJobs((prev) => prev.filter((job) => job.tempId !== tempId));
          void refreshLibrary();
        } else {
          let message = `Upload failed (${xhr.status})`;
          try {
            const parsed = JSON.parse(xhr.responseText) as { detail?: string };
            if (parsed.detail) message = parsed.detail;
          } catch {
            /* non-JSON error */
          }
          setUploadJobs((prev) => prev.map((job) => (job.tempId === tempId ? { ...job, error: message } : job)));
        }
      };
      xhr.onerror = () => {
        setUploadJobs((prev) => prev.map((job) => (job.tempId === tempId ? { ...job, error: 'Upload failed' } : job)));
      };
      xhr.send(form);
    },
    [activeKey, sessionMap, refreshLibrary, defaultModel, setSessionMap],
  );

  const removeSessionDocument = useCallback(
    async (documentId: number) => {
      if (typeof activeKey === 'number') {
        const ok = await detachSessionDocument(activeKey, documentId);
        if (!ok) return;
      }
      setSessionMap((prev) => {
        const next = new Map(prev);
        const currentState = next.get(activeKey) ?? {
          messages: [],
          isStreaming: false,
          toolsDone: false,
          input: '',
          model: defaultModel,
          mode: 'research' as const,
          documents: [],
          abortController: null,
        };
        next.set(activeKey, {
          ...currentState,
          documents: removeAttachedDocument(currentState.documents ?? [], documentId),
        });
        return next;
      });
      void refreshLibrary();
    },
    [activeKey, defaultModel, refreshLibrary, setSessionMap],
  );

  const attachLibraryDocument = useCallback(
    (document: AttachedDocument) => {
      const currentDocuments = sessionMap.get(activeKey)?.documents ?? [];
      if (currentDocuments.some((item) => item.id === document.id)) return;
      if (currentDocuments.length >= MAX_ATTACHMENTS_PER_TURN) return;
      setSessionMap((prev) => {
        const next = new Map(prev);
        const currentState = next.get(activeKey) ?? {
          messages: [],
          isStreaming: false,
          toolsDone: false,
          input: '',
          model: defaultModel,
          mode: 'research' as const,
          documents: [],
          abortController: null,
        };
        const existing = currentState.documents ?? [];
        const merged = addAttachedDocument(existing, document);
        if (merged !== existing) {
          next.set(activeKey, { ...currentState, documents: merged });
        }
        return next;
      });
      if (typeof activeKey === 'number') {
        const ids = addAttachedDocument(currentDocuments, document).map((item) => item.id);
        void fetch('/api/py/ai/documents/attach', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: activeKey, document_ids: ids }),
        }).then(() => refreshLibrary());
      }
    },
    [activeKey, sessionMap, defaultModel, refreshLibrary, setSessionMap],
  );

  const deleteLibraryDocument = useCallback(
    async (documentId: number) => {
      const res = await fetch(`/api/py/ai/documents/${documentId}`, { method: 'DELETE' });
      if (!res.ok) return;
      setLibraryDocuments((prev) => prev.filter((item) => item.id !== documentId));
      setSessionMap((prev) => {
        const next = new Map(prev);
        for (const [key, state] of next) {
          if (state.documents.some((item) => item.id === documentId)) {
            next.set(key, { ...state, documents: state.documents.filter((item) => item.id !== documentId) });
          }
        }
        return next;
      });
    },
    [setSessionMap],
  );

  const handleDocumentDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragActive(false);
      const files = filterSupportedDocuments(event.dataTransfer.files);
      files.forEach((file) => uploadFile(file));
    },
    [uploadFile],
  );

  return {
    libraryDocuments,
    uploadJobs,
    dragActive,
    setDragActive,
    refreshLibrary,
    uploadFile,
    removeSessionDocument,
    attachLibraryDocument,
    deleteLibraryDocument,
    handleDocumentDrop,
  };
}
