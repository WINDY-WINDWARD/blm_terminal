'use client';

import { useState, useEffect } from 'react';
import type { BrowserProvision } from './types';

export function useBrowserProvisioning({
  scrapingConsent,
  setScrapingConsent,
}: {
  scrapingConsent: boolean | null;
  setScrapingConsent: (val: boolean | null) => void;
}) {
  const [consentSyncStatus, setConsentSyncStatus] = useState<string | null>(null);
  const [browserProvision, setBrowserProvision] = useState<BrowserProvision | null>(null);
  const [browserFetchBusy, setBrowserFetchBusy] = useState(false);

  const refreshBrowserStatus = async () => {
    try {
      const res = await fetch('/api/py/system_config/browser-status', { credentials: 'include' });
      if (!res.ok) return false;
      const data = await res.json();
      setBrowserProvision({
        state: data.state ?? 'unknown',
        downloaded: data.downloaded ?? 0,
        total: data.total ?? 0,
        version: data.version ?? null,
        error: data.error ?? null,
      });
      return (data.state ?? 'unknown') === 'ready';
    } catch {
      return false;
    }
  };

  const handleBrowserRetry = async () => {
    setBrowserFetchBusy(true);
    try {
      const res = await fetch('/api/py/system_config/browser-fetch', {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) {
        setConsentSyncStatus(`Browser fetch failed (HTTP ${res.status}) — will retry automatically`);
        setTimeout(() => setConsentSyncStatus(null), 5000);
      }
      await refreshBrowserStatus();
    } catch (e) {
      console.error('Failed to trigger browser fetch:', e);
      setConsentSyncStatus('Could not reach backend to start browser fetch');
      setTimeout(() => setConsentSyncStatus(null), 5000);
    } finally {
      setBrowserFetchBusy(false);
    }
  };

  useEffect(() => {
    if (scrapingConsent !== true) {
      setBrowserProvision(null);
      return;
    }
    let timer: ReturnType<typeof setInterval> | null = null;
    const poll = async () => {
      const ready = await refreshBrowserStatus();
      if (ready && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };
    void poll();
    timer = setInterval(() => {
      void poll();
    }, 5000);
    return () => {
      if (timer !== null) clearInterval(timer);
    };
  }, [scrapingConsent]);

  const handleUpdateConsent = async (val: boolean) => {
    setScrapingConsent(val);
    try {
      setConsentSyncStatus('Updating...');
      await fetch('/api/py/system_config/consent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ consent: val }),
      });
      setConsentSyncStatus(val ? 'Advanced Extraction Enabled' : 'Safe Mode Enabled');
      setTimeout(() => setConsentSyncStatus(null), 3000);
    } catch (e) {
      console.error('Failed to sync consent:', e);
      setConsentSyncStatus('Error syncing setting');
      setTimeout(() => setConsentSyncStatus(null), 3000);
    }
  };

  return {
    consentSyncStatus,
    browserProvision,
    browserFetchBusy,
    handleBrowserRetry,
    handleUpdateConsent,
  };
}
