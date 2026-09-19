/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Client-side key precheck: normalize + checksum BEFORE any network call.
'use strict';
const { KEY_ALPHABET, KEY_BODY_LEN, KEY_TOTAL_LEN } = require('./constants');

const VAL = new Map([...KEY_ALPHABET].map((c, i) => [c, i]));

function normalizeKey(input) {
  let s = String(input || '').toUpperCase().replace(/[\s-]+/g, '');
  if (s.startsWith('BLM')) s = s.slice(3);
  return s;
}

function validateKeyFormat(input) {
  const s = normalizeKey(input);
  if (s.length !== KEY_TOTAL_LEN) return { ok: false, reason: 'length' };
  for (const c of s) if (!VAL.has(c)) return { ok: false, reason: 'alphabet' };
  let sum = 0;
  const body = s.slice(0, KEY_BODY_LEN);
  for (const c of body) sum += VAL.get(c);
  if (KEY_ALPHABET[sum % 32] !== s[KEY_BODY_LEN]) return { ok: false, reason: 'checksum' };
  return { ok: true, bare: s };
}

module.exports = { normalizeKey, validateKeyFormat };
