/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Lease verification: signature over exact bytes + iid bind + expiry.
// Rollback guard (max server ts) and lic_exp live with the caller (store).
'use strict';

let sodium = null;
async function ready() {
  if (!sodium) {
    sodium = require('libsodium-wrappers');
    await sodium.ready;
  }
  return sodium;
}

const B64 = () => sodium.base64_variants.URLSAFE_NO_PADDING;

async function verifyLease(payloadB64Std, sigB64, leasePubs, expectedIid, nowS) {
  const s = await ready();
  let payloadBytes;
  try {
    payloadBytes = Buffer.from(String(payloadB64Std), 'base64');
  } catch {
    return { ok: false, reason: 'encoding' };
  }
  let sig;
  try {
    sig = s.from_base64(sigB64, B64());
  } catch {
    return { ok: false, reason: 'encoding' };
  }
  let payload;
  try {
    payload = JSON.parse(payloadBytes.toString('utf8'));
  } catch {
    return { ok: false, reason: 'encoding' };
  }
  // Try every trusted lease-verify key (rotation-ready list).
  let sigOk = false;
  for (const pub of leasePubs) {
    try {
      const pk = s.from_base64(pub, B64());
      if (s.crypto_sign_verify_detached(sig, payloadBytes, pk)) { sigOk = true; break; }
    } catch { /* next key */ }
  }
  if (!sigOk) return { ok: false, reason: 'signature' };
  if (payload.v !== 1) return { ok: false, reason: 'version' };
  if (payload.iid !== expectedIid) return { ok: false, reason: 'iid_mismatch' };
  if (typeof payload.exp !== 'number' || nowS >= payload.exp) {
    return { ok: false, reason: 'expired' };
  }
  return { ok: true, payload };
}

module.exports = { ready, verifyLease };
