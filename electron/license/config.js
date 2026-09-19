/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Runtime license config: packaged builds use BAKED values ONLY (env ignored);
// dev builds allow env overrides for localhost testing. Packaged builds reject
// any non-https URL and any host other than the production domain.
'use strict';

let baked = {};
try {
  baked = require('./licenseConfig.js');
} catch {
  baked = {};
}

const { app } = require('electron');
const isPackaged = app.isPackaged;

const PROD_HOST = process.env.BLM_PROD_HOST || '';

function resolve() {
  if (isPackaged) {
    const url = baked.url || '';
    if (!url.startsWith('https://')) {
      throw new Error('packaged license config missing https URL');
    }
    if (PROD_HOST) {
      const host = new URL(url).host;
      if (host !== PROD_HOST) throw new Error(`untrusted license host: ${host}`);
    }
    if (!baked.encPub || !baked.leasePubs || baked.leasePubs.length === 0) {
      throw new Error('packaged license keys missing: rebuild with gen-license-config');
    }
    return {
      url, boxKid: baked.boxKid || 'box-1', encPub: baked.encPub,
      leasePubs: baked.leasePubs, feedUrl: baked.feedUrl || '', otaPubs: baked.otaPubs || [],
    };
  }
  return {
    url: process.env.LICENSE_VALIDATOR_URL || baked.url || 'http://127.0.0.1:3050/api/license/validate',
    boxKid: process.env.LICENSE_BOX_KID || baked.boxKid || 'box-1',
    encPub: process.env.LICENSE_SERVER_PUBLIC_KEY || baked.encPub || '',
    leasePubs: baked.leasePubs && baked.leasePubs.length
      ? baked.leasePubs
      : (process.env.LICENSE_LEASE_PUBS || '').split(',').map((s) => s.trim()).filter(Boolean),
    feedUrl: process.env.OTA_FEED_URL || baked.feedUrl || '',
    otaPubs: baked.otaPubs && baked.otaPubs.length
      ? baked.otaPubs
      : (process.env.OTA_PUBS || '').split(',').map((s) => s.trim()).filter(Boolean),
  };
}

module.exports = { resolve };
