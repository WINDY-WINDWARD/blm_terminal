'use client';

import React, { useState, useEffect } from 'react';
import { useAtom } from 'jotai';
import { authAtom, isAuthenticatedAtom } from '@/store/terminalStore';

export function LoginModal() {
  const [auth, setAuth] = useAtom(authAtom);
  const [isAuthenticated] = useAtom(isAuthenticatedAtom);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    
    const handleAuthExpired = () => {
      setAuth(null);
    };
    window.addEventListener('auth-expired', handleAuthExpired);
    return () => window.removeEventListener('auth-expired', handleAuthExpired);
  }, [setAuth]);

  if (!mounted || isAuthenticated) return null;

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // Create x-www-form-urlencoded data for OAuth2PasswordBearer
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const response = await fetch('/api/py/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData.toString(),
      });

      if (!response.ok) {
        throw new Error('Invalid username or password');
      }

      const data = await response.json();
      
      // Fetch user profile
      const userRes = await fetch('/api/py/auth/me', {
        headers: {
          'Authorization': `Bearer ${data.access_token}`
        }
      });
      const userData = await userRes.json();

      setAuth({
        token: data.access_token,
        user: userData
      });
      
      // Trigger a page reload to reset query caches
      window.location.reload();
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
