'use client';

import { useEffect } from 'react';

/**
 * Root-level error boundary. Replaces Next.js's cryptic default
 * ("This page couldn't load") with the actual error message so crashes
 * can be diagnosed instead of guessed at.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('[BLM global-error]', error);
  }, [error]);

  const message = error?.message || 'Unknown error';
  const stack = error?.stack
    ?.split('\n')
    .slice(0, 6)
    .join('\n');

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          background: '#09090b',
          color: '#e1e4ea',
          fontFamily: 'monospace',
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 16,
        }}
      >
        <div
          style={{
            maxWidth: 640,
            width: '100%',
            border: '1px solid #7f1d1d',
            background: '#1a1d23',
            padding: 20,
          }}
        >
          <div style={{ color: '#f87171', fontWeight: 'bold', fontSize: 14, marginBottom: 8 }}>
            SOMETHING BROKE WHILE LOADING THE TERMINAL
          </div>
          <div
            style={{
              color: '#fbbf24',
              fontSize: 12,
              marginBottom: 8,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {message}
          </div>
          {error?.digest ? (
            <div style={{ color: '#6b7280', fontSize: 11, marginBottom: 8 }}>
              digest: {error.digest}
            </div>
          ) : null}
          {stack ? (
            <pre
              style={{
                color: '#9ca3af',
                fontSize: 11,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 160,
                overflow: 'auto',
                margin: '0 0 12px 0',
              }}
            >
              {stack}
            </pre>
          ) : null}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={() => reset()}
              style={{
                background: '#f59e0b',
                color: '#000',
                fontWeight: 'bold',
                padding: '8px 16px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'monospace',
                fontSize: 12,
              }}
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{
                background: 'transparent',
                color: '#9ca3af',
                padding: '8px 16px',
                border: '1px solid #2d3139',
                cursor: 'pointer',
                fontFamily: 'monospace',
                fontSize: 12,
              }}
            >
              Reload page
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
