'use client';

import React, { useState, useEffect } from 'react';
import { useAtom, useAtomValue } from 'jotai';
import { useQueryClient } from '@tanstack/react-query';
import { authAtom, isAuthenticatedAtom, onboardingCompletedAtom } from '@/store/terminalStore';

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useAtom(authAtom);
  const [isAuthenticated] = useAtom(isAuthenticatedAtom);
  const onboardingCompleted = useAtomValue(onboardingCompletedAtom);
  const queryClient = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [sessionChecking, setSessionChecking] = useState(true);
  // True when the backend has no user accounts yet — the first-launch wizard
  // owns auth in that case, so this guard must not show its own login wall.
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    setMounted(true);

    const handleAuthExpired = async () => {
      await fetch('/api/py/auth/logout', { method: 'POST' }).catch(() => {});
      setAuth(null);
    };
    window.addEventListener('auth-expired', handleAuthExpired);
    return () => window.removeEventListener('auth-expired', handleAuthExpired);
  }, [setAuth]);

  useEffect(() => {
    let isCancelled = false;
    
    const initializeAuth = async () => {
      while (!isCancelled) {
        try {
          const res = await fetch('/api/py/auth/me', {
            signal: AbortSignal.timeout(2000),
          });
          // If we get 502/503/504, the Python backend is not yet ready (Next.js proxy error).
          // If we get 200 or 401, the Python backend is online.
          if (res.status !== 502 && res.status !== 503 && res.status !== 504) {
            if (!isCancelled) {
              if (res.ok) {
                const userData = await res.json();
                setAuth({ user: userData });
              } else {
                setAuth(null);
              }
              // Best-effort first-boot probe: when no accounts exist, the
              // setup wizard handles auth and this guard stays out of the way.
              try {
                const setupRes = await fetch('/api/py/auth/setup-status', {
                  signal: AbortSignal.timeout(2000),
                });
                if (setupRes.ok) {
                  const setupData = await setupRes.json();
                  if (!isCancelled && setupData?.needs_setup === true) {
                    setNeedsSetup(true);
                  }
                }
              } catch {
                // Ignore — login wall remains the fallback.
              }
              setSessionChecking(false);
            }
            break;
          }
        } catch {
          // Network error means proxy or backend is completely unreachable yet
        }
        
        // Wait 1 second before retrying
        if (!isCancelled) {
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
      }
    };

    initializeAuth();

    return () => {
      isCancelled = true;
    };
  }, [setAuth]);

  if (!mounted || sessionChecking) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-terminal-bg">
        <div className="flex flex-col items-center gap-4">
          <span className="text-terminal-amber font-mono text-sm animate-pulse">CONNECTING TO BACKEND...</span>
          <span className="text-terminal-muted font-mono text-xs">Please wait while the system initializes</span>
        </div>
      </div>
    );
  }

  // First boot with no accounts: the setup wizard owns the auth flow, so let
  // the app render underneath it instead of stacking a second login wall.
  if (!isAuthenticated && needsSetup && !onboardingCompleted) {
    return <>{children}</>;
  }

  if (!isAuthenticated) {
    const handleLogin = async (e: React.FormEvent) => {
      e.preventDefault();
      setError('');
      setLoading(true);

      try {
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch('/api/py/auth/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: formData.toString(),
          signal: AbortSignal.timeout(8000),
        });

        if (!response.ok) {
          if (response.status === 401) {
            throw new Error('Invalid username or password');
          }
          throw new Error('Authentication service unavailable. Please try again.');
        }

        const userRes = await fetch('/api/py/auth/me', {
          signal: AbortSignal.timeout(5000),
        });
        const userData = await userRes.json();

        setAuth({ user: userData });

        queryClient.invalidateQueries();
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Login failed');
      } finally {
        setLoading(false);
      }
    };

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-terminal-bg/90 backdrop-blur-sm">
        <div className="w-full max-w-sm p-6 bg-terminal-panel border border-terminal-border shadow-xl font-mono">
          <div className="text-center mb-6">
            <h2 className="text-xl text-terminal-amber font-bold tracking-wider">BLM TERMINAL</h2>
            <p className="text-xs text-terminal-muted mt-1">AUTHORIZATION REQUIRED</p>
          </div>

          {error && (
            <div className="mb-4 p-2 bg-red-900/50 border border-red-500 text-red-200 text-xs">
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs text-terminal-muted mb-1">USERNAME</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-terminal-bg border border-terminal-border p-2 text-terminal-amber text-sm focus:outline-none focus:border-terminal-amber focus:ring-1 focus:ring-terminal-amber transition-colors"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-terminal-muted mb-1">PASSWORD</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-terminal-bg border border-terminal-border p-2 text-terminal-amber text-sm focus:outline-none focus:border-terminal-amber focus:ring-1 focus:ring-terminal-amber transition-colors"
                required
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-terminal-amber text-terminal-bg font-bold py-2 px-4 hover:bg-yellow-500 disabled:opacity-50 transition-colors"
            >
              {loading ? 'AUTHENTICATING...' : 'LOGIN'}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // Once authenticated and backend is ready, render the main application
  return <>{children}</>;
}
