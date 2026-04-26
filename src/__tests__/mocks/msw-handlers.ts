import { http, HttpResponse } from 'msw';
import { gainers, losers } from '../fixtures/market';
import { symbolData, changeRanges, historicalBars } from '../fixtures/market';
import { watchlists, watchlistItems } from '../fixtures/watchlist';
import { orderBook, positionBook, fundsData } from '../fixtures/trading';
import { notifications } from '../fixtures/notifications';

// Market endpoints
const marketHandlers = [
  http.get('/api/py/market/top-gainers', () => {
    return HttpResponse.json(gainers);
  }),
  http.get('/api/py/market/top-losers', () => {
    return HttpResponse.json(losers);
  }),
  http.get('/api/py/market/symbol-data/:symbol', ({ params }) => {
    const { symbol } = params;
    return HttpResponse.json(symbolData(symbol as string));
  }),
  http.get('/api/py/market/change-ranges/:symbol', ({ params }) => {
    const { symbol } = params;
    return HttpResponse.json(changeRanges(symbol as string));
  }),
  http.get('/api/py/morningstar/fairvalue/:symbol', () => {
    return HttpResponse.json({ fairValue: 1234.5 });
  }),
  http.get('/api/py/stockuniverse/search/:query', ({ params }) => {
    const { query } = params;
    const results = [
      { symbol: `${query?.toString().toUpperCase() ?? ''}1`, companyName: `Test Company ${query}` },
      { symbol: `${query?.toString().toUpperCase() ?? ''}2`, companyName: `Another Company ${query}` },
    ];
    return HttpResponse.json(results);
  }),
];

// Watchlist endpoints
const watchlistHandlers = [
  http.get('/api/watchlist', () => {
    return HttpResponse.json(watchlistItems);
  }),
  http.post('/api/watchlist', async ({ request }) => {
    const body = await request.json() as { symbol: string; exchange: string };
    const newItem = {
      id: Date.now(),
      watchlist_id: 1,
      symbol: body.symbol,
      exchange: body.exchange,
    };
    return HttpResponse.json(newItem, { status: 201 });
  }),
  http.delete('/api/watchlist', () => {
    return HttpResponse.json({ success: true });
  }),
  http.get('/api/watchlists', () => {
    return HttpResponse.json(watchlists);
  }),
  http.post('/api/watchlists', async ({ request }) => {
    const body = await request.json() as { name: string };
    const newList = {
      id: Date.now(),
      name: body.name,
      created_at: new Date().toISOString(),
    };
    return HttpResponse.json(newList, { status: 201 });
  }),
];

// Event calendar endpoints
const eventCalendarHandlers = [
  http.get('/api/event-calendar', () => {
    return HttpResponse.json([]);
  }),
  http.get('/api/event-calendar/past', () => {
    return HttpResponse.json([]);
  }),
];

// Notification endpoints
const notificationHandlers = [
  http.get('/api/py/notifications', () => {
    return HttpResponse.json(notifications);
  }),
  http.delete('/api/py/notifications/:id', () => {
    return HttpResponse.json({ success: true }, { status: 204 });
  }),
  http.delete('/api/py/notifications', () => {
    return HttpResponse.json({ success: true }, { status: 204 });
  }),
];

// OpenAlgo endpoints
const openAlgoHandlers = [
  http.get('/api/openalgo/ws-token', () => {
    return HttpResponse.json({ api_key: 'TEST_KEY' });
  }),
  http.post('/api/openalgo/funds', () => {
    return HttpResponse.json({ status: 'success', data: fundsData });
  }),
  http.post('/api/openalgo/orders', () => {
    return HttpResponse.json({ status: 'success', data: orderBook });
  }),
  http.post('/api/openalgo/positions', () => {
    return HttpResponse.json({ status: 'success', data: positionBook });
  }),
  http.post('/api/openalgo/placeorder', () => {
    return HttpResponse.json({
      status: 'success',
      orderid: 'TEST001',
      message: 'Order placed',
    });
  }),
  http.post('/api/openalgo/history', () => {
    return HttpResponse.json({ status: 'success', data: historicalBars });
  }),
  http.post('/api/openalgo/trades', () => {
    return HttpResponse.json({ status: 'success', data: [] });
  }),
  http.post('/api/openalgo/quotes', () => {
    return HttpResponse.json({
      status: 'success',
      data: {
        ltp: 2450.3,
        open: 2440,
        high: 2460,
        low: 2430,
        close: 2435,
        volume: 1000000,
      },
    });
  }),
];

// Settings endpoint
const settingsHandlers = [
  http.get('/api/settings', () => {
    return HttpResponse.json({
      theme: 'dark',
      panelCount: 4,
    });
  }),
];

// Combine all handlers
export const handlers = [
  ...marketHandlers,
  ...watchlistHandlers,
  ...eventCalendarHandlers,
  ...notificationHandlers,
  ...openAlgoHandlers,
  ...settingsHandlers,
];