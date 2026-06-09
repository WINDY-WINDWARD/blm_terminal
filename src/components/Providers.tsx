'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, useEffect } from 'react';

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 1000,
            retry: 2,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const originalFetch = window.fetch;
    window.fetch = async (input, init) => {
      // Only intercept calls to our backend API
      const urlStr = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      if (!urlStr.startsWith('/api/') && !urlStr.includes('localhost:4455') && !urlStr.includes('/api/py/')) {
        return originalFetch(input, init);
      }

      const authStr = window.localStorage.getItem('terminal.auth');
      let token = '';
      if (authStr) {
        try {
          const auth = JSON.parse(authStr);
          if (auth?.token) token = auth.token;
        } catch {}
      }

      let newInit = init;
      if (token) {
        const headers = new Headers(init?.headers);
        if (!headers.has('Authorization')) {
          headers.set('Authorization', `Bearer ${token}`);
        }
        newInit = { ...init, headers };
      }

      const res = await originalFetch(input, newInit);
      if (res.status === 401 && !urlStr.includes('/api/py/auth/login')) {
        window.localStorage.removeItem('terminal.auth');
        window.dispatchEvent(new Event('auth-expired'));
      }
      return res;
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
