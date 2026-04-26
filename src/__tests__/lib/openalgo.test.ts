import { describe, it, expect } from 'vitest';
import { server } from '../mocks/msw-server';
import { http, HttpResponse } from 'msw';
import { OpenAlgoClient } from '@/lib/openalgo';

describe('OpenAlgoClient', () => {
  describe('getFunds', () => {
    it('should return funds data', async () => {
      const result = await OpenAlgoClient.getFunds();
      expect(result.status).toBe('success');
      expect(result.data).toBeDefined();
    });
  });

  describe('getOrderBook', () => {
    it('should return order book with statistics', async () => {
      const result = await OpenAlgoClient.getOrderBook();
      expect(result.status).toBe('success');
      expect(result.data.orders).toBeDefined();
      expect(result.data.statistics).toBeDefined();
    });
  });

  describe('getPositionBook', () => {
    it('should return position data', async () => {
      const result = await OpenAlgoClient.getPositionBook();
      expect(result.status).toBe('success');
      expect(result.data).toBeInstanceOf(Array);
    });
  });

  describe('placeOrder', () => {
    it('should place order successfully', async () => {
      const result = await OpenAlgoClient.placeOrder({
        symbol: 'RELIANCE',
        exchange: 'NSE',
        action: 'BUY',
        quantity: '10',
        price: '2450',
        order_type: 'LIMIT',
        product: 'MIS',
      });
      expect(result.status).toBe('success');
      expect(result.orderid).toBe('TEST001');
    });
  });

  describe('getHistory', () => {
    it('should return historical data', async () => {
      const result = await OpenAlgoClient.getHistory('RELIANCE', 'NSE', 'D', '2024-01-01', '2024-04-24');
      expect(result.status).toBe('success');
      expect(result.data).toBeInstanceOf(Array);
    });
  });
});