import React, { ReactElement, ReactNode } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Provider as JotaiProvider, createStore } from 'jotai';
import type { WritableAtom } from 'jotai';

interface RenderWithProvidersOptions {
  initialAtomValues?: [WritableAtom<any, any[], any>, unknown][];
  queryClientOptions?: Partial<QueryClient>;
}

interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  wrapperProps?: RenderWithProvidersOptions;
}

// Create a fresh QueryClient for each test
function createTestQueryClient(options?: Partial<QueryClient>) {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
        refetchInterval: false,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
    ...options,
  });
}

// Create a fresh Jotai store for each test
function createTestStore(initialValues?: [WritableAtom<any, any[], any>, unknown][]) {
  const testStore = createStore();
  if (initialValues) {
    initialValues.forEach(([atom, value]) => {
      testStore.set(atom as WritableAtom<any, any[], any>, value);
    });
  }
  return testStore;
}

// Custom wrapper component
function TestProviders({ children, options }: { children: ReactNode; options?: RenderWithProvidersOptions }) {
  const [queryClient] = React.useState(() => createTestQueryClient(options?.queryClientOptions));
  const [store] = React.useState(() => createTestStore(options?.initialAtomValues));

  return (
    <JotaiProvider store={store}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </JotaiProvider>
  );
}

// Custom render function that wraps component with providers
function customRender(
  ui: ReactElement,
  { wrapperProps, ...renderOptions }: CustomRenderOptions = {}
) {
  return render(ui, {
    wrapper: ({ children }) => <TestProviders options={wrapperProps}>{children}</TestProviders>,
    ...renderOptions,
  });
}

// Re-export everything from @testing-library/react
export * from '@testing-library/react';
export { customRender as render };

// Export utilities that are commonly needed in tests
export { createTestQueryClient, createTestStore };
export type { RenderWithProvidersOptions, CustomRenderOptions };