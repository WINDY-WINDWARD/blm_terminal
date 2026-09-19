/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Manifest-gated OTA (A5): verify the signed manifest BEFORE download,
// hash-verify the installer BEFORE install. Fail closed on missing manifest.
// Unsigned NSIS => this manifest is the only publisher check.
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

let sodium = null;
async function ready() {
  if (!sodium) {
    sodium = require('libsodium-wrappers');
    await sodium.ready;
  }
  return sodium;
}
const B64 = () => sodium.base64_variants.URLSAFE_NO_PADDING;

function cmpVer(a, b) {
  const pa = String(a).replace(/^v/, '').split('.').map(Number);
  const pb = String(b).replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d > 0 ? 1 : -1;
  }
  return 0;
}

async function getJson(url, timeoutMs = 15000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`http_${r.status}`);
    return await r.text();
  } finally {
    clearTimeout(t);
  }
}

function requireHttps(feedUrl, isPackaged) {
  const u = new URL(feedUrl);
  if (isPackaged && u.protocol !== 'https:') throw new Error('feed must be https in packaged builds');
  return u;
}

/** Fetch + verify manifest. Returns parsed manifest or throws. */
async function fetchVerifiedManifest(feedUrl, otaPubs, isPackaged, log = () => {}) {
  const base = requireHttps(feedUrl, isPackaged);
  const manUrl = new URL('ota-manifest.json', base).toString();
  const sigUrl = new URL('ota-manifest.sig', base).toString();
  log(`OTA manifest: ${manUrl}`);
  let manText, sigText;
  try {
    [manText, sigText] = await Promise.all([getJson(manUrl), getJson(sigUrl)]);
  } catch (e) {
    throw new Error(`manifest unavailable: ${e.message}`);
  }
  const s = await ready();
  const manBytes = Buffer.from(manText, 'utf8');
  let sig;
  try {
    sig = s.from_base64(sigText.trim(), B64());
  } catch {
    throw new Error('manifest signature undecodable');
  }
  let ok = false;
  for (const pub of otaPubs) {
    try {
      if (s.crypto_sign_verify_detached(sig, manBytes, s.from_base64(pub, B64()))) { ok = true; break; }
    } catch { /* next */ }
  }
  if (!ok) throw new Error('manifest signature invalid');
  const man = JSON.parse(manText);
  if (!man || man.v !== 1 || typeof man.version !== 'string' || !Array.isArray(man.files)) {
    throw new Error('manifest malformed');
  }
  return man;
}

function sha256File(fp) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    const st = fs.createReadStream(fp);
    st.on('data', (d) => h.update(d));
    st.on('end', () => resolve(h.digest('hex')));
    st.on('error', reject);
  });
}

/** Verify every downloaded installer path against the manifest. */
async function verifyDownloaded(paths, manifest) {
  const list = (Array.isArray(paths) ? paths : [paths]).filter(Boolean);
  if (!list.length) throw new Error('nothing downloaded');
  for (const fp of list) {
    const name = path.basename(String(fp));
    const entry = manifest.files.find((f) => f.name === name);
    if (!entry) throw new Error(`downloaded file not in manifest: ${name}`);
    const digest = await sha256File(String(fp));
    if (digest.toLowerCase() !== String(entry.sha256).toLowerCase()) {
      throw new Error(`hash mismatch: ${name}`);
    }
  }
  return list;
}

module.exports = { cmpVer, fetchVerifiedManifest, verifyDownloaded };
