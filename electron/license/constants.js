// Frozen client-side mirror of the license protocol constants.
// Source of truth lives in blmlanding/lib/license/constants.js — keep in sync.
'use strict';

const PROTOCOL_V = 1;
const KEY_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
const KEY_BODY_LEN = 17;
const KEY_TOTAL_LEN = 18;
const KEY_PREFIX = 'BLM-';
const KEY_GROUP = 6;

const LEASE_TTL_S = 7 * 24 * 60 * 60;
const SKEW_WARN_S = 5 * 60;
const ROLLBACK_TOLERANCE_S = 120;

// Only these server statuses wipe the stored lease. Everything else is
// indeterminate (run iff a valid lease exists; never delete or renew).
const LEASE_WIPING_STATUSES = ['revoked', 'expired', 'unknown'];

module.exports = {
  PROTOCOL_V, KEY_ALPHABET, KEY_BODY_LEN, KEY_TOTAL_LEN, KEY_PREFIX, KEY_GROUP,
  LEASE_TTL_S, SKEW_WARN_S, ROLLBACK_TOLERANCE_S, LEASE_WIPING_STATUSES,
};
