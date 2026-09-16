/* eslint-disable @typescript-eslint/no-require-imports */
const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const httpProxy = require('http-proxy');
const { WebSocketServer } = require('ws');

const { handleMarketWsConnection } = require('./server/marketWsHandler');

const dev = process.env.NODE_ENV !== 'production';
const port = parseInt(process.env.PORT || '3000', 10);
const backendUrl = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';

// In packaged Electron builds, .next/ is unpacked outside the ASAR archive.
// NEXT_DIR tells Next.js where to find the production build on the real filesystem.
const dir = process.env.NEXT_DIR || undefined;
const app = next({ dev, dir });
const handle = app.getRequestHandler();

const proxy = httpProxy.createProxyServer({
  target: backendUrl,
  ws: true,
  changeOrigin: true,
});

proxy.on('error', (err, _req, socket) => {
  console.error('[server] WS proxy error:', err.message);
  if (socket && typeof socket.destroy === 'function') socket.destroy();
});

// In-process WS server for /ws/market. The browser connects
// here directly (same-origin), and we resolve each symbol via
// NSE-direct + Python-fallback (see server/marketWsHandler.js).
const marketWss = new WebSocketServer({ noServer: true });

marketWss.on('connection', (ws) => {
  handleMarketWsConnection(ws);
});

app.prepare().then(() => {
  // Ensure the proxied backend URL stays pinned to the startup value; next() may reload .env.local
  if (backendUrl && process.env.PYTHON_BACKEND_URL !== backendUrl) {
    process.env.PYTHON_BACKEND_URL = backendUrl;
  }

  const server = createServer((req, res) => {
    handle(req, res, parse(req.url, true));
  });

  server.on('upgrade', (req, socket, head) => {
    const { pathname } = parse(req.url || '');
    if (pathname === '/ws/market') {
      console.log('[server] WS upgrade: /ws/market (handled in-process)');
      marketWss.handleUpgrade(req, socket, head, (ws) => {
        marketWss.emit('connection', ws, req);
      });
    } else if (pathname === '/ws/news') {
      console.log('[server] WS upgrade: /ws/news → Python');
      proxy.ws(req, socket, head);
    } else {
      socket.destroy();
    }
  });

  server.listen(port, '127.0.0.1', (err) => {
    if (err) throw err;
    console.log(`[server] Ready on http://127.0.0.1:${port} (${dev ? 'dev' : 'prod'})`);
    console.log(`[server] /ws/market → in-process Next.js handler`);
    console.log(`[server] /ws/news → ${backendUrl}`);
  });
});
