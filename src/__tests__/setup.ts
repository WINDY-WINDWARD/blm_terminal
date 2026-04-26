import { beforeAll, afterEach, afterAll, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { server } from './mocks/msw-server';

// Start MSW before all tests
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'warn' });
});

// Reset handlers after each test to prevent handler state bleeding
afterEach(() => {
  server.resetHandlers();
  // Clear localStorage to prevent atomWithStorage state bleed
  localStorage.clear();
});

// Close MSW server after all tests
afterAll(() => {
  server.close();
});

// Stub out ResizeObserver for ChartWidget and other components that use it
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})) as unknown as typeof ResizeObserver;

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock scrollTo for react-split and other components
window.scrollTo = vi.fn();