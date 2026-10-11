/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Encrypted local store: key + iid + lease + clock state.
// safeStorage.encryptString when available, else 0600 file fallback.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { app, safeStorage } = require('electron');

const FILE = 'license.dat';

function filePath() {
  return path.join(app.getPath('userData'), FILE);
}

function readRaw() {
  try {
    const fp = filePath();
    if (!fs.existsSync(fp)) return null;
    const blob = JSON.parse(fs.readFileSync(fp, 'utf8'));
    if (blob.enc && safeStorage.isEncryptionAvailable()) {
      return JSON.parse(safeStorage.decryptString(Buffer.from(blob.enc, 'base64')).toString('utf8'));
    }
    if (blob.plain) return blob.plain; // 0600 fallback (written only when safeStorage unavailable)
    return null;
  } catch {
    return null;
  }
}

function writeRaw(obj) {
  const fp = filePath();
  let blob;
  if (safeStorage.isEncryptionAvailable()) {
    try {
      blob = { v: 1, enc: safeStorage.encryptString(JSON.stringify(obj)).toString('base64') };
    } catch {
      blob = { v: 1, plain: obj };
    }
  } else {
    blob = { v: 1, plain: obj };
  }
  fs.writeFileSync(fp, JSON.stringify(blob));
  try { fs.chmodSync(fp, 0o600); } catch {}
}

function randomIid() {
  return crypto.randomUUID();
}

function load() {
  const d = readRaw() || {};
  if (!d.iid) {
    d.iid = randomIid();
    writeRaw(d);
  }
  return d;
}

module.exports = {
  load,
  saveKey: (key) => writeRaw({ ...load(), key }),
  saveLease: (lease, serverTs, localNowS) => {
    const d = load();
    d.lease = lease;
    d.serverOffset = serverTs - localNowS;
    d.maxServerTs = Math.max(d.maxServerTs || 0, serverTs);
    writeRaw(d);
  },
  clearLease: () => {
    const d = load();
    delete d.lease;
    writeRaw(d);
  },
  clearAll: () => {
    const d = load();
    writeRaw({ iid: d.iid }); // keep iid stable across key changes
  },
};
