import { beforeAll, afterEach, afterAll, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { server } from './mocks/msw-server';

/**
 * Simple in-memory Storage polyfill for test environments (e.g. happy-dom)
 * where localStorage/sessionStorage are missing or incomplete.
 */
class MemoryStorage implements Storage {
  private data = new Map<string, string>();

  get length(): number {
    return this.data.size;
  }

  key(index: number): string | null {
    const keys = Array.from(this.data.keys());
    return keys[index] ?? null;
  }

  getItem(key: string): string | null {
    return this.data.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value);
  }

  removeItem(key: string): void {
    this.data.delete(key);
  }

  clear(): void {
    this.data.clear();
  }
}

function ensureStorage(name: 'localStorage' | 'sessionStorage'): Storage {
  const existing = (window as unknown as Record<string, unknown>)[name];
  if (
    existing &&
    typeof (existing as Storage).getItem === 'function' &&
    typeof (existing as Storage).setItem === 'function'
  ) {
    return existing as Storage;
  }
  const polyfill = new MemoryStorage();
  Object.defineProperty(window, name, {
    value: polyfill,
    writable: true,
    configurable: true,
  });
  return polyfill;
}

ensureStorage('localStorage');
ensureStorage('sessionStorage');

function safeClearStorage(storage: Storage | undefined): void {
  if (!storage) return;
  if (typeof storage.clear === 'function') {
    storage.clear();
  } else {
    const keys: string[] = [];
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (key) keys.push(key);
    }
    keys.forEach((key) => storage.removeItem(key));
  }
}

// Start MSW before all tests
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'warn' });
});

// Reset handlers after each test to prevent handler state bleeding
afterEach(() => {
  server.resetHandlers();
  // Clear localStorage to prevent atomWithStorage state bleed
  safeClearStorage(localStorage);
  // Clear sessionStorage for tab-isolated atoms
  safeClearStorage(sessionStorage);
});

// Close MSW server after all tests
afterAll(() => {
  server.close();
});

// Stub out ResizeObserver for ChartWidget and other components that use it
class ResizeObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
global.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

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