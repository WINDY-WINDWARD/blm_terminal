#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports -- Node CLI script, same style as scripts/*.js */
// Release gate for desktop OTA artifacts.
//
// `npm run verify:release` used to be an echo stub, so every release shipped on
// the operator's word alone. This script performs the checks the release skill
// lists, and reuses electron/ota.js so the gate and the client cannot drift.
//
//   node scripts/verify_release.js                 # verify dist-desktop/
//   node scripts/verify_release.js --live          # verify the published feed
//   node scripts/verify_release.js --live --binary # ...and re-download the exe
//
// Local mode proves the five artifacts are internally consistent:
//   * ota-manifest.sig is a valid Ed25519 signature over ota-manifest.json
//   * the manifest covers the exact installer in dist-desktop
//   * the installer bytes hash to the manifest's sha256
//   * latest.yml names the same version/file/size and hashes to the same bytes
//   * exactly one installer version is present (no stale .exe from a prior run)
// Live mode proves the portal serves the same release the repo just built.
'use strict';

const fs = require('fs');
const path = require('path');

const {
  cmpVer,
  verifyManifestText,
  sha256File,
  sha512Base64File,
  fetchText,
  createOtaVerifier,
} = require('../electron/ota.js');

const DEFAULT_FEED = 'https://blmterminal.windytech.org';

function parseArgs(argv) {
  const args = { live: false, binary: false, feed: DEFAULT_FEED, dir: 'dist-desktop', expect: null, quiet: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--live') args.live = true;
    else if (a === '--binary') args.binary = true;
    else if (a === '--quiet') args.quiet = true;
    else if (a === '--feed') args.feed = argv[++i];
    else if (a === '--dir') args.dir = argv[++i];
    else if (a === '--expect') args.expect = argv[++i];
    else if (a === '--help' || a === '-h') args.help = true;
    else throw new Error(`unknown argument: ${a}`);
  }
  return args;
}

/** Minimal parser for electron-builder's latest.yml (no YAML dependency). */
function parseLatestYml(text) {
  const out = { files: [] };
  let inFiles = false;
  const unquote = (v) => v.replace(/^['"]|['"]$/g, '');
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim()) continue;
    const line = raw.trim();
    const indented = /^\s/.test(raw);
    if (!indented) {
      inFiles = line.startsWith('files:');
      if (inFiles) continue;
      const m = line.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
      if (m) out[m[1]] = unquote(m[2]);
      continue;
    }
    if (!inFiles) continue;
    const item = line.match(/^-\s*([A-Za-z0-9_]+):\s*(.*)$/);
    if (item) {
      out.files.push({ [item[1]]: unquote(item[2]) });
      continue;
    }
    const kv = line.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
    if (kv && out.files.length) out.files[out.files.length - 1][kv[1]] = unquote(kv[2]);
  }
  return out;
}

function makeReport(quiet) {
  const results = [];
  return {
    results,
    check(name, ok, detail = '') {
      results.push({ name, ok, detail });
      if (!quiet) {
        const mark = ok ? 'PASS' : 'FAIL';
        console.log(`  [${mark}] ${name}${detail ? ` — ${detail}` : ''}`);
      }
      return ok;
    },
    section(title) {
      if (!quiet) console.log(`\n${title}`);
    },
  };
}

async function verifyLocal({ dir, expect, report }) {
  const root = path.resolve(dir);
  if (!fs.existsSync(root)) {
    report.check('dist-desktop exists', false, root);
    return { ok: false };
  }

  const pkgVersion = JSON.parse(fs.readFileSync(path.resolve('package.json'), 'utf8')).version;
  const expected = expect || pkgVersion;
  report.check('package.json version matches expectation', cmpVer(pkgVersion, expected) === 0, `package=${pkgVersion} expected=${expected}`);

  const manPath = path.join(root, 'ota-manifest.json');
  const sigPath = path.join(root, 'ota-manifest.sig');
  const ymlPath = path.join(root, 'latest.yml');
  for (const p of [manPath, sigPath, ymlPath]) {
    report.check(`${path.basename(p)} present`, fs.existsSync(p), p);
  }
  if (![manPath, sigPath, ymlPath].every((p) => fs.existsSync(p))) return { ok: false };

  let manifest;
  try {
    manifest = await verifyManifestText(fs.readFileSync(manPath, 'utf8'), fs.readFileSync(sigPath, 'utf8'));
    report.check('ota-manifest.sig is a valid signature over ota-manifest.json', true, `version ${manifest.version}`);
  } catch (err) {
    report.check('ota-manifest.sig is a valid signature over ota-manifest.json', false, err.message);
    return { ok: false };
  }

  report.check('manifest version matches package version', cmpVer(manifest.version, pkgVersion) === 0, `${manifest.version} vs ${pkgVersion}`);

  if (manifest.files.length !== 1) {
    report.check('manifest lists exactly one installer', false, `${manifest.files.length} entries`);
  } else {
    report.check('manifest lists exactly one installer', true, manifest.files[0].name);
  }

  const entry = manifest.files[0] || null;
  const installerName = entry?.name || `BLM Terminal Setup ${pkgVersion}.exe`;
  const installerPath = path.join(root, installerName);
  const hasInstaller = fs.existsSync(installerPath);
  report.check('installer present', hasInstaller, installerName);
  if (!hasInstaller) return { ok: false };

  // Artifact hygiene: a leftover installer from another version means the
  // manifest may have been signed against the wrong file.
  const strayInstallers = fs
    .readdirSync(root)
    .filter((f) => /^BLM Terminal Setup .*\.exe$/i.test(f) && f !== installerName);
  report.check('no stale installer from a previous version', strayInstallers.length === 0, strayInstallers.join(', '));

  const stat = fs.statSync(installerPath);
  report.check('installer size matches manifest', Number(entry.size) === stat.size, `${stat.size} vs ${entry.size}`);
  const sha256 = await sha256File(installerPath);
  report.check('installer sha256 matches manifest', sha256.toLowerCase() === String(entry.sha256).toLowerCase(), sha256);
  const sha512 = await sha512Base64File(installerPath);

  const yml = parseLatestYml(fs.readFileSync(ymlPath, 'utf8'));
  report.check('latest.yml version matches manifest', cmpVer(yml.version, manifest.version) === 0, `${yml.version} vs ${manifest.version}`);
  const ymlFile = (yml.files && yml.files[0]) || {};
  report.check('latest.yml names the signed installer', ymlFile.url === installerName, String(ymlFile.url));
  report.check('latest.yml size matches installer', Number(ymlFile.size) === stat.size, `${ymlFile.size} vs ${stat.size}`);
  report.check('latest.yml sha512 matches installer bytes', String(ymlFile.sha512) === sha512, 'sha512');
  report.check('latest.yml path matches installer', yml.path === installerName, String(yml.path));

  return { ok: report.results.every((r) => r.ok), manifest, installerName, installerPath, sha256, sha512, size: stat.size };
}

async function verifyLive({ feed, expect, binary, report, local }) {
  const base = feed.endsWith('/') ? feed : `${feed}/`;
  const urls = {
    yml: new URL('latest.yml', base).toString(),
    man: new URL('ota-manifest.json', base).toString(),
    sig: new URL('ota-manifest.sig', base).toString(),
  };

  let ymlText;
  let manText;
  let sigText;
  try {
    [ymlText, manText, sigText] = await Promise.all([
      fetchText(urls.yml),
      fetchText(urls.man),
      fetchText(urls.sig),
    ]);
  } catch (err) {
    report.check('feed is reachable (latest.yml, manifest, signature)', false, `${err.message} @ ${base}`);
    return { ok: false };
  }
  report.check('feed is reachable (latest.yml, manifest, signature)', true, base);

  const yml = parseLatestYml(ymlText);
  let manifest;
  try {
    manifest = await verifyManifestText(manText, sigText);
    report.check('published manifest signature is valid', true, `version ${manifest.version}`);
  } catch (err) {
    report.check('published manifest signature is valid', false, err.message);
    return { ok: false };
  }

  const expected = expect || (fs.existsSync('package.json') ? JSON.parse(fs.readFileSync('package.json', 'utf8')).version : manifest.version);
  report.check('published manifest version matches package version', cmpVer(manifest.version, expected) === 0, `${manifest.version} vs ${expected}`);
  report.check('published latest.yml version matches manifest', cmpVer(yml.version, manifest.version) === 0, `${yml.version} vs ${manifest.version}`);

  const entry = (manifest.files && manifest.files[0]) || null;
  const ymlFile = (yml.files && yml.files[0]) || {};
  report.check('published latest.yml names the manifest installer', entry?.name === ymlFile.url, `${ymlFile.url} vs ${entry?.name}`);
  report.check('published latest.yml size matches manifest', Number(ymlFile.size) === Number(entry?.size), `${ymlFile.size} vs ${entry?.size}`);

  if (local && local.ok) {
    report.check('published manifest matches the local build', cmpVer(manifest.version, local.manifest.version) === 0 && String(entry?.sha256).toLowerCase() === local.sha256.toLowerCase(), 'sha256');
  }

  if (binary) {
    try {
      const exeUrl = new URL(encodeURIComponent(ymlFile.url), base).toString();
      const res = await fetch(exeUrl, { redirect: 'follow' });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const hash = require('crypto').createHash('sha256');
      const tmp = path.join(require('os').tmpdir(), `blm-verify-${process.pid}.exe`);
      const fd = fs.openSync(tmp, 'w');
      try {
        for await (const chunk of res.body) {
          hash.update(chunk);
          fs.writeSync(fd, chunk);
        }
      } finally {
        fs.closeSync(fd);
      }
      const digest = hash.digest('hex');
      fs.unlinkSync(tmp);
      report.check('downloaded installer sha256 matches manifest', digest.toLowerCase() === String(entry?.sha256).toLowerCase(), digest);
    } catch (err) {
      report.check('downloaded installer sha256 matches manifest', false, err.message);
    }
  }

  return { ok: report.results.every((r) => r.ok), manifest };
}

async function runVerifyRelease(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (args.help) {
    console.log('usage: verify_release.js [--live] [--binary] [--feed URL] [--dir PATH] [--expect VERSION] [--quiet]');
    return 0;
  }

  // Prove the verifier itself works before trusting a PASS: a packaged build
  // with a broken libsodium is exactly the failure this gate exists to catch.
  const selfTest = await createOtaVerifier({ feedUrl: args.feed, isPackaged: false }).selfTest();
  const report = makeReport(args.quiet);
  report.section('Verifier');
  if (!report.check('Ed25519 verifier is usable', selfTest.ok, selfTest.error || '')) return 2;

  report.section(`Local artifacts (${path.resolve(args.dir)})`);
  const local = await verifyLocal({ dir: args.dir, expect: args.expect, report });

  if (args.live) {
    report.section(`Published feed (${args.feed})`);
    await verifyLive({ feed: args.feed, expect: args.expect, binary: args.binary, report, local });
  }

  const ok = report.results.every((r) => r.ok);
  console.log('');
  if (ok) {
    console.log(`verify:release OK — ${report.results.length} checks passed${args.live ? ' (local + live)' : ''}.`);
    return 0;
  }
  const failed = report.results.filter((r) => !r.ok);
  console.error(`verify:release FAILED — ${failed.length} of ${report.results.length} checks failed:`);
  for (const f of failed) console.error(`  - ${f.name}${f.detail ? ` (${f.detail})` : ''}`);
  return 1;
}

if (require.main === module) {
  runVerifyRelease()
    .then((code) => process.exit(code))
    .catch((err) => {
      console.error(`verify:release errored: ${err?.stack || err}`);
      process.exit(2);
    });
}

module.exports = { runVerifyRelease, verifyLocal, verifyLive, parseLatestYml, parseArgs };
