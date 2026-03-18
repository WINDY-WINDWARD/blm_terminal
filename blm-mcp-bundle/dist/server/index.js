#!/usr/bin/env node
// server/index.js  —  MCPB Proxy to remote MCP server
// Translates Claude Desktop's stdio MCP protocol → HTTP JSON-RPC

const http = require('http');
const readline = require('readline');

// Safely parse env — guard against unresolved ${user_config.*} template strings
// that some Claude Desktop versions pass through literally on Windows
function resolvedEnv(value, fallback) {
  if (!value || value.startsWith('${')) return fallback;
  return value;
}

const REMOTE_HOST = resolvedEnv(process.env.REMOTE_HOST, 'localhost');
const REMOTE_PORT = parseInt(resolvedEnv(process.env.REMOTE_PORT, '4455'), 10);

// !! IMPORTANT: Update this path to match your Python backend's actual MCP route
// Common options: '/mcp', '/api/mcp', '/mcp/v1'
const REMOTE_PATH ='/api/mcp/mcp';

const BASE_URL = `http://${REMOTE_HOST}:${REMOTE_PORT}${REMOTE_PATH}`;

// ── JSON-RPC helpers ──────────────────────────────────────────
function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

function sendError(id, code, message) {
  send({ jsonrpc: '2.0', id, error: { code, message } });
}

// ── HTTP call to remote server ────────────────────────────────
function remoteCall(method, params) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method,
      params: params || {}
    });

    const req = http.request({
      hostname: REMOTE_HOST,
      port: REMOTE_PORT,
      path: REMOTE_PATH,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'Host': REMOTE_HOST + ':' + REMOTE_PORT
      },
      timeout: 30000
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`Invalid JSON from remote (HTTP ${res.statusCode}): ${data}`));
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timed out'));
    });

    req.write(body);
    req.end();
  });
}

// ── MCP message router ────────────────────────────────────────
async function handleMessage(msg) {
  const { id, method, params } = msg;

  if (method === 'initialize') {
    // Echo back the client's protocolVersion -- Claude Desktop enforces version match
    send({
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: params?.protocolVersion || '2025-11-25',
        serverInfo: { name: 'blm-mcp-proxy', version: '1.0.0' },
        capabilities: { tools: {}, prompts: {}, resources: {} }
      }
    });
    return;
  }

  if (method === 'ping') {
    send({ jsonrpc: '2.0', id, result: {} });
    return;
  }

  // Notifications have no id — drop silently, never respond
  if (id === undefined || id === null) {
    process.stderr.write(`[blm-mcp-proxy] Notification dropped: ${method}\n`);
    return;
  }

  // Forward request to remote server
  try {
    const response = await remoteCall(method, params);
    if (response.error) {
      send({ jsonrpc: '2.0', id, error: response.error });
    } else if (response.result !== undefined) {
      send({ jsonrpc: '2.0', id, result: response.result });
    } else {
      process.stderr.write(`[blm-mcp-proxy] Unexpected response: ${JSON.stringify(response)}\n`);
      send({ jsonrpc: '2.0', id, result: {} });
    }
  } catch (err) {
    process.stderr.write(`[blm-mcp-proxy] Remote call failed (${method}): ${err.message}\n`);
    sendError(id, -32603, `Remote error: ${err.message}`);
  }
}

// ── stdin reader ──────────────────────────────────────────────
const rl = readline.createInterface({ input: process.stdin });

rl.on('line', (line) => {
  if (!line.trim()) return;
  try {
    const msg = JSON.parse(line);
    handleMessage(msg).catch(err => {
      sendError(msg.id ?? null, -32603, err.message);
    });
  } catch {
    sendError(null, -32700, 'Parse error');
  }
});

process.stdin.on('end', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
process.on('SIGINT', () => process.exit(0));

process.stderr.write(`[blm-mcp-proxy] Config → host=${REMOTE_HOST} port=${REMOTE_PORT} path=${REMOTE_PATH}\n`);
process.stderr.write(`[blm-mcp-proxy] Ready → ${BASE_URL}\n`);
