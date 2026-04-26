import { vi } from 'vitest';
import type { TickData, WsMode } from '@/lib/socket';

// WebSocket mock for testing components that use wsService
class MockWebSocketService {
  private _connected = false;
  private _tickListeners: Set<(data: TickData) => void> = new Set();
  private _connectionListeners: Set<(connected: boolean) => void> = new Set();
  private _subscriptions: Map<string, WsMode> = new Map();

  connect = vi.fn();
  disconnect = vi.fn();
  subscribe = vi.fn((symbol: string, exchange: string, mode: WsMode = 2) => {
    const key = `${symbol}.${exchange}`;
    this._subscriptions.set(key, mode);
  });
  unsubscribe = vi.fn((symbol: string, exchange: string, _mode: WsMode = 2) => {
    const key = `${symbol}.${exchange}`;
    this._subscriptions.delete(key);
  });

  onTick = vi.fn((handler: (data: TickData) => void) => {
    this._tickListeners.add(handler);
    return vi.fn(() => this._tickListeners.delete(handler));
  });

  onConnectionChange = vi.fn((handler: (connected: boolean) => void) => {
    this._connectionListeners.add(handler);
    return vi.fn(() => this._connectionListeners.delete(handler));
  });

  get isConnected(): boolean {
    return this._connected;
  }

  // Test helpers to trigger events
  __triggerTick(data: TickData) {
    this._tickListeners.forEach((handler) => handler(data));
  }

  __triggerConnection(connected: boolean) {
    this._connected = connected;
    this._connectionListeners.forEach((handler) => handler(connected));
  }

  __reset() {
    this._connected = false;
    this._tickListeners.clear();
    this._connectionListeners.clear();
    this._subscriptions.clear();
  }
}

export const mockWsService = new MockWebSocketService();