'use client';

import React, { useEffect, useState } from 'react';
import { useAtom } from 'jotai';
import { advancedScrapingConsentAtom } from '@/store/terminalStore';

export function AdvancedScrapingModal() {
  const [consent, setConsent] = useAtom(advancedScrapingConsentAtom);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Avoid hydration mismatch with localStorage
  if (!mounted || consent !== null) {
    return null;
  }

  const syncConsentToBackend = async (value: boolean) => {
    try {
      // Next.js /api/py proxy forwards Authorization from cookie/auth header; no manual header needed.
      // We fetch via same-origin so HttpOnly session cookie is included.
      await fetch('/api/py/system_config/consent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ consent: value }),
      });
    } catch (err) {
      console.error('Failed to sync advanced scraping consent to backend:', err);
    }
  };

  const handleDecline = () => {
    setConsent(false);
    void syncConsentToBackend(false);
  };

  const handleAgree = () => {
    setConsent(true);
    void syncConsentToBackend(true);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-lg rounded border border-[#2d3139] bg-[#121418] p-6 text-[#e1e4ea] shadow-2xl">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded bg-[#f59e0b]/10 text-[#f59e0b]">
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold tracking-wide text-[#f3f4f6]">
              Legal Waiver: Advanced Web Extraction
            </h2>
            <p className="text-xs text-[#9ca3af]">Informed Consent Required</p>
          </div>
        </div>

        <div className="rounded bg-[#1a1d23] p-4 text-xs leading-relaxed text-[#d1d5db] border border-[#2d3139] mb-6 select-text">
          This software contains generic web automation capabilities. By enabling Advanced
          Extraction, you authorize the software to navigate target websites on your behalf.
          You warrant that you have the legal right to access this data and assume all legal
          liability for its extraction.
        </div>

        <div className="flex items-center justify-end gap-3 pt-2 border-t border-[#2d3139]/60">
          <button
            type="button"
            onClick={handleDecline}
            className="rounded px-4 py-2 text-xs font-medium text-[#9ca3af] hover:text-white bg-[#1a1d23] hover:bg-[#252830] transition border border-[#2d3139]"
          >
            Decline (Safe Mode)
          </button>
          <button
            type="button"
            onClick={handleAgree}
            className="rounded px-4 py-2 text-xs font-medium text-white bg-[#2563eb] hover:bg-[#1d4ed8] transition shadow-sm font-semibold"
          >
            I Agree, Enable Advanced Features
          </button>
        </div>
      </div>
    </div>
  );
}
