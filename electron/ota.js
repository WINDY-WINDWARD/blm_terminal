/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Publisher authentication for OTA updates.
//
// The installer carries no Authenticode certificate, so a valid Ed25519
// signature over ota-manifest.json is the only proof a downloaded .exe came
// from us. electron-updater already compares the installer against latest.yml
// over HTTPS, but latest.yml is served from the same origin as the binary: an
// attacker who owns that origin can rewrite both. The manifest signature is
// made offline and cannot be forged that way.
//
// This module is shared by the client (electron/updater.js) and the release
// gate (scripts/verify_release.js) so the check that ships and the check that
// gates publishing can never drift apart.
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// Public half of the offline OTA signing key (blmlanding/scripts/gen-ota-key.js).
// Rotating it requires shipping a client that trusts the new key BEFORE the
// first release signed with that key.
const OTA_PUBLIC_KEYS = ['BIcIqF8Gl2apHbJ19n5DsMa-6Je0xtBoRsbj7AH1mIM'];

const MANIFEST_TIMEOUT_MS = 15000;
const MAX_MANIFEST_BYTES = 64 * 1024;

let sodiumModule = null;

/** Lazily load libsodium. Throws if the binding is unusable in this build. */
async function loadSodium() {
  if (!sodiumModule) {
    const imported = require('libsodium-wrappers');
    await imported.ready;
    sodiumModule = imported;
  }
  return sodiumModule;
}

const b64Variant = (sodium) => sodium.base64_variants.URLSAFE_NO_PADDING;

/** Numeric dotted-version compare. Returns -1, 0 or 1. */
function cmpVer(a, b) {
  const pa = String(a).replace(/^v/, '').split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b).replace(/^v/, '').split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d > 0 ? 1 : -1;
  }
  return 0;
}

async function fetchText(url, timeoutMs = MANIFEST_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`http_${res.status}`);
    const text = await res.text();
    if (text.length > MAX_MANIFEST_BYTES) throw new Error('response too large');
    return text;
  } finally {
    clearTimeout(timer);
  }
}

/** Reject non-HTTPS feeds in packaged builds; allow http for local testing. */
function assertFeedUrl(feedUrl, isPackaged) {
  const parsed = new URL(feedUrl);
  if (isPackaged && parsed.protocol !== 'https:') {
    throw new Error('update feed must be https in packaged builds');
  }
  return parsed;
}

/**
 * Verify a detached Ed25519 signature over the raw manifest bytes.
 * Returns the parsed manifest, or throws with a stable reason.
 */
async function verifyManifestText(manText, sigText, publicKeys = OTA_PUBLIC_KEYS) {
  const sodium = await loadSodium();
  const manBytes = Buffer.from(manText, 'utf8');
  let signature;
  try {
    signature = sodium.from_base64(sigText.trim(), b64Variant(sodium));
  } catch {
    throw new Error('manifest signature is not valid base64url');
  }
  if (!signature.length) throw new Error('manifest signature is empty');

  const trusted = publicKeys.some((pub) => {
    try {
      return sodium.crypto_sign_verify_detached(
        signature,
        manBytes,
        sodium.from_base64(pub, b64Variant(sodium)),
      );
    } catch {
      return false;
    }
  });
  if (!trusted) throw new Error('manifest signature does not match any trusted key');

  let manifest;
  try {
    manifest = JSON.parse(manText);
  } catch {
    throw new Error('manifest is not valid JSON');
  }
  if (!manifest || manifest.v !== 1 || typeof manifest.version !== 'string' || !Array.isArray(manifest.files)) {
    throw new Error('manifest has an unexpected shape');
  }
  return manifest;
}

function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

function sha512Base64File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha512');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('base64')));
    stream.on('error', reject);
  });
}

/**
 * OTA verifier bound to one feed.
 *
 * Every method resolves to a verdict object instead of throwing, because the
 * caller has to record the reason in the updater state the UI renders.
 */
function createOtaVerifier({
  feedUrl,
  isPackaged = true,
  log = () => {},
  publicKeys = OTA_PUBLIC_KEYS,
  fetchImpl = fetchText,
  cacheMs = 60000,
} = {}) {
  let cachedManifest = null;
  let cachedAt = 0;

  async function fetchManifest({ force = false } = {}) {
    const fresh = cachedManifest && Date.now() - cachedAt < cacheMs;
    if (fresh && !force) return cachedManifest;

    const base = assertFeedUrl(feedUrl, isPackaged);
    const manUrl = new URL('ota-manifest.json', base).toString();
    const sigUrl = new URL('ota-manifest.sig', base).toString();
    const [manText, sigText] = await Promise.all([fetchImpl(manUrl), fetchImpl(sigUrl)]);
    const manifest = await verifyManifestText(manText, sigText, publicKeys);
    cachedManifest = manifest;
    cachedAt = Date.now();
    log(`[ota] manifest verified for ${manifest.version} (${manifest.files.length} file(s))`);
    return manifest;
  }

  /**
   * Prove the crypto stack works in this runtime. A packaged build that cannot
   * load libsodium must not silently offer updates it can never verify.
   */
  async function selfTest() {
    try {
      const sodium = await loadSodium();
      const decoded = sodium.from_base64(publicKeys[0], b64Variant(sodium));
      if (decoded.length !== sodium.crypto_sign_PUBLICKEYBYTES) {
        return { ok: false, error: `public key is ${decoded.length} bytes, expected ${sodium.crypto_sign_PUBLICKEYBYTES}` };
      }
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err?.message || String(err) };
    }
  }

  /** Verify a downloaded installer against the signed manifest. */
  async function verifyInstaller(installerPath, expectedVersion = null) {
    try {
      if (!installerPath || !fs.existsSync(installerPath)) {
        return { ok: false, error: 'downloaded installer is missing from the update cache' };
      }
      // Fail closed: no manifest, no install.
      const manifest = await fetchManifest();
      const name = path.basename(installerPath);
      const entry = manifest.files.find((f) => f.name === name);
      if (!entry) {
        return { ok: false, error: `downloaded file is not listed in the signed manifest: ${name}` };
      }
      if (expectedVersion && cmpVer(manifest.version, expectedVersion) !== 0) {
        return {
          ok: false,
          error: `manifest is for ${manifest.version} but the update is ${expectedVersion}`,
        };
      }
      const stat = fs.statSync(installerPath);
      if (typeof entry.size === 'number' && entry.size !== stat.size) {
        return { ok: false, error: `installer size ${stat.size} does not match manifest size ${entry.size}` };
      }
      const digest = await sha256File(installerPath);
      if (digest.toLowerCase() !== String(entry.sha256 || '').toLowerCase()) {
        return { ok: false, error: `installer sha256 does not match the signed manifest` };
      }
      return { ok: true, manifest, entry };
    } catch (err) {
      return { ok: false, error: err?.message || String(err) };
    }
  }

  function resetCache() {
    cachedManifest = null;
    cachedAt = 0;
  }

  return { feedUrl, publicKeys, fetchManifest, verifyInstaller, selfTest, resetCache };
}

module.exports = {
  OTA_PUBLIC_KEYS,
  MANIFEST_TIMEOUT_MS,
  cmpVer,
  loadSodium,
  fetchText,
  verifyManifestText,
  sha256File,
  sha512Base64File,
  createOtaVerifier,
};
