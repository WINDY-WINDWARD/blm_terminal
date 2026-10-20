/* eslint-disable @typescript-eslint/no-require-imports */
const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const httpProxy = require('http-proxy');
const { WebSocketServer } = require('ws');

const { handleMarketWsConnection } = require('./server/marketWsHandler');

let launchToken = null;
let serverInternalToken = process.env.BLM_INTERNAL_TOKEN || null;
process.on('message', (message) => {
  if (message && message.type === 'launch-token' && typeof message.token === 'string') {
    launchToken = message.token;
    process.env.BLM_LOCAL_TOKEN = message.token;
  }
  if (message && message.type === 'internal-token' && typeof message.token === 'string') {
    serverInternalToken = message.token;
    process.env.BLM_INTERNAL_TOKEN = message.token;
  }
});

const dev = process.env.NODE_ENV !== 'production';
// Ephemeral by default (A6): a port squatter must never receive the launch
// token. Set PORT explicitly only for dev convenience.
const configuredPort = parseInt(process.env.PORT || '0', 10);
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

  let actualPort = configuredPort;
  const expectedHost = () => `127.0.0.1:${actualPort}`;

  const deny = (res, code, msg) => {
    res.writeHead(code, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: msg }));
  };

  const server = createServer((req, res) => {
    // Host validation (DNS-rebinding protection): exact loopback origin only.
    const host = req.headers.host || '';
    if (actualPort && host !== expectedHost()) {
      return deny(res, 403, 'forbidden_host');
    }

    // Never trust client-supplied internal tokens on incoming requests.
    // The server internal token is kept strictly in Node process.env.
    delete req.headers['x-blm-internal-token'];
    delete req.headers['x-blm-server-token'];

    if (launchToken && !req.headers['x-blm-token']) {
      req.headers['x-blm-token'] = launchToken;
    }

    const { pathname, query } = parse(req.url || '', true);
    void query;
    handle(req, res, parse(req.url, true));
  });

  server.on('upgrade', (req, socket, head) => {
    const { pathname, query } = parse(req.url || '', true);
    const host = req.headers.host || '';
    if (actualPort && host !== expectedHost()) {
      socket.destroy();
      return;
    }
    
    // Ignore Next.js internal paths to allow Hot Module Replacement (HMR) to work during development
    if (pathname.startsWith('/_next/')) {
      return;
    }
    
    if (pathname !== '/ws/market' && pathname !== '/ws/news') {
      socket.destroy();
      return;
    }
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

  server.listen(configuredPort, '127.0.0.1', (err) => {
    if (err) throw err;
    actualPort = server.address().port;
    console.log(`[server] Ready on http://127.0.0.1:${actualPort} (${dev ? 'dev' : 'prod'})`);
    console.log(`[server] /ws/market → in-process Next.js handler`);
    console.log(`[server] /ws/news → ${backendUrl}`);
    // Report the ephemeral port to the Electron parent over IPC.
    if (typeof process.send === 'function') {
      process.send({ type: 'server-ready', port: actualPort });
    }
  });
});
