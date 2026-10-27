/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// `BLM Terminal.exe --verify-ota [feedUrl]` — release gate for the packaged build.
//
// The client refuses to install an update it cannot verify, so a packaging
// regression that breaks libsodium inside the asar would silently turn updates
// off for everyone. Running this against the freshly built binary before
// publishing proves the packaged runtime can reach the feed and validate the
// signed manifest, while it is still cheap to fix.
//
// Exit codes: 0 verified, 2 verifier unusable, 3 feed/manifest failure.
'use strict';

const { createOtaVerifier } = require('./ota');

async function runOtaVerifyCli({ feedUrl, isPackaged, log = () => {} }) {
  const verifier = createOtaVerifier({ feedUrl, isPackaged, log });

  const selfTest = await verifier.selfTest();
  if (!selfTest.ok) {
    const message = `OTA SELF-TEST FAILED: ${selfTest.error}`;
    log(message);
    return { ok: false, code: 2, message };
  }

  try {
    const manifest = await verifier.fetchManifest({ force: true });
    const message = `OTA VERIFY OK: feed=${feedUrl} version=${manifest.version} files=${manifest.files.length}`;
    log(message);
    return { ok: true, code: 0, message, manifest };
  } catch (err) {
    const message = `OTA VERIFY FAILED: ${err?.message || err}`;
    log(message);
    return { ok: false, code: 3, message };
  }
}

module.exports = { runOtaVerifyCli };
