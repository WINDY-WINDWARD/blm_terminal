const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const httpProxy = require('http-proxy');

const dev = process.env.NODE_ENV !== 'production';
const hostname = process.env.HOSTNAME || '0.0.0.0';
const port = parseInt(process.env.PORT || '3000', 10);
const backendUrl = process.env.PYTHON_BACKEND_URL || 'http://localhost:4455';

const app = next({ dev, hostname, port });
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

app.prepare().then(() => {
  const server = createServer((req, res) => {
    handle(req, res, parse(req.url, true));
  });

  server.on('upgrade', (req, socket, head) => {
    const { pathname } = parse(req.url || '');
    if (pathname === '/ws/market' || pathname === '/ws/news') {
      console.log(`[server] WS upgrade: ${pathname}`);
      proxy.ws(req, socket, head);
    } else {
      socket.destroy();
    }
  });

  server.listen(port, hostname, (err) => {
    if (err) throw err;
    console.log(`[server] Ready on http://${hostname}:${port} (${dev ? 'dev' : 'prod'})`);
    console.log(`[server] WS proxy → ${backendUrl}`);
  });
});
