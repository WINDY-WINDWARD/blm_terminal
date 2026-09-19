/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Token holder: main delivers the per-launch token over IPC (fork channel).
// Dev direct-run may set BLM_LAUNCH_TOKEN. Nothing else sets this.
// On receipt, the token is also published to process.env.BLM_LOCAL_TOKEN so
// in-process Next.js route handlers (bundled separately by webpack, so they
// cannot share this module instance) can forward it server-side to Python.
// Runtime-set, never argv: invisible in process listings. Same-user processes
// could read it — out of scope (they own the box); the token's job is other
// users, web pages/DNS-rebinding, and accidental direct-run. See licensing.md.
let launchToken = process.env.BLM_LAUNCH_TOKEN || null;
const tickets = new Map(); // single-use WS tickets -> expiry ms

function noteIpc() {
  process.on('message', (m) => {
    if (m && m.type === 'license-token' && typeof m.token === 'string') {
      launchToken = m.token;
      process.env.BLM_LOCAL_TOKEN = m.token;
    }
  });
}

function tokenOk(req) {
  if (!launchToken) return process.env.NODE_ENV !== 'production';
  const t = req.headers['x-blm-token'];
  return typeof t === 'string' && t.length > 0 && t === launchToken;
}

function mintTicket() {
  const crypto = require('crypto');
  const ticket = crypto.randomBytes(24).toString('hex');
  tickets.set(ticket, Date.now() + 10_000);
  if (tickets.size > 1000) {
    const now = Date.now();
    for (const [k, v] of tickets) if (v <= now) tickets.delete(k);
  }
  return ticket;
}

function consumeTicket(ticket) {
  const exp = tickets.get(typeof ticket === 'string' ? ticket : '');
  if (!exp) return false;
  tickets.delete(ticket);
  return exp > Date.now();
}

module.exports = { noteIpc, tokenOk, mintTicket, consumeTicket, getToken: () => launchToken };
