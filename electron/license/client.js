/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Online validation client: sealed request, secretbox reply, decision table.
// Outcomes: { outcome: 'ok' } | { outcome: 'denied', status } |
//           { outcome: 'indeterminate', status?, detail? }.
// Only revoked/expired/unknown are denials. Everything else indeterminate.
'use strict';
const { PROTOCOL_V, LEASE_WIPING_STATUSES } = require('./constants');
const { validateKeyFormat } = require('./keycodec');

let sodium = null;
async function ready() {
  if (!sodium) {
    sodium = require('libsodium-wrappers');
    await sodium.ready;
  }
  return sodium;
}
const B64 = () => sodium.base64_variants.URLSAFE_NO_PADDING;

async function postJson(url, body, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    const text = await r.text();
    let json = null;
    try { json = JSON.parse(text); } catch {}
    return { http: r.status, json };
  } finally {
    clearTimeout(t);
  }
}

/**
 * cfg: { url, boxKid, encPub (b64), key, iid, timeoutMs }
 * Returns outcome object; lease verification is the caller's job (needs store).
 */
async function validateOnce(cfg) {
  const s = await ready();
  const fmt = validateKeyFormat(cfg.key);
  if (!fmt.ok) return { outcome: 'invalid_key', reason: fmt.reason };

  const sk = s.randombytes_buf(s.crypto_secretbox_KEYBYTES);
  let encPub;
  try {
    encPub = s.from_base64(cfg.encPub, B64());
  } catch {
    return { outcome: 'indeterminate', detail: 'bad_config' };
  }
  const R = {
    v: PROTOCOL_V, k: cfg.key, iid: cfg.iid,
    sk: s.to_base64(sk, B64()),
    ts: Math.floor(Date.now() / 1000),
  };
  const sealed = s.crypto_box_seal(Buffer.from(JSON.stringify(R), 'utf8'), encPub);

  let res;
  try {
    res = await postJson(cfg.url, { v: PROTOCOL_V, kid: cfg.boxKid, sealed: s.to_base64(sealed, B64()) }, cfg.timeoutMs || 10000);
  } catch {
    return { outcome: 'indeterminate', detail: 'network' };
  }
  if (res.http === 429 || (res.http >= 500 && res.http < 600)) {
    return { outcome: 'indeterminate', detail: `http_${res.http}` };
  }
  if (res.http !== 200 || !res.json || typeof res.json.boxed !== 'string') {
    // 400/404/405 or undecryptable-by-construction: suspicious, not decisive.
    return { outcome: 'indeterminate', detail: `http_${res.http}`, suspicious: true };
  }
  let pt;
  try {
    const nonce = s.from_base64(res.json.nonce, B64());
    const boxed = s.from_base64(res.json.boxed, B64());
    pt = s.crypto_secretbox_open_easy(boxed, nonce, sk);
  } catch {
    return { outcome: 'indeterminate', detail: 'undecryptable', suspicious: true };
  }
  let P;
  try {
    P = JSON.parse(Buffer.from(pt).toString('utf8'));
  } catch {
    return { outcome: 'indeterminate', detail: 'undecryptable', suspicious: true };
  }
  if (!P || P.v !== 1 || typeof P.status !== 'string') {
    return { outcome: 'indeterminate', detail: 'malformed_reply', suspicious: true };
  }
  if (LEASE_WIPING_STATUSES.includes(P.status)) {
    return { outcome: 'denied', status: P.status, reply: P };
  }
  if (P.status === 'ok') return { outcome: 'ok', reply: P };
  // rate_limited, error, or anything unrecognized: indeterminate.
  return { outcome: 'indeterminate', status: P.status, reply: P };
}

/** Launch retry: 3 attempts, 10s timeout, exponential backoff. */
async function validateWithRetry(cfg) {
  const delays = [0, 1500, 4000];
  let last = { outcome: 'indeterminate', detail: 'network' };
  for (const d of delays) {
    if (d) await new Promise((r) => setTimeout(r, d));
    last = await validateOnce(cfg);
    if (last.outcome !== 'indeterminate' || last.suspicious) break;
    // plain indeterminate (network/429/5xx): retry
    if (d === delays[delays.length - 1]) break;
  }
  return last;
}

module.exports = { ready, validateOnce, validateWithRetry };
