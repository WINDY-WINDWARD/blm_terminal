const fs = require('fs');
const path = require('path');
const sodium = require('libsodium-wrappers');
const { verifyDownloaded } = require('../electron/license/ota.js');
const { otaPubs } = require('../licenseConfig.js');

const rootDir = path.resolve(__dirname, '..');
const distDir = path.join(rootDir, 'dist-desktop');
const pkg = JSON.parse(fs.readFileSync(path.join(rootDir, 'package.json'), 'utf8'));
const version = pkg.version;

async function verify() {
  console.log(`==> Verifying release artifacts for v${version} in ${distDir}...`);

  if (!fs.existsSync(distDir)) {
    throw new Error(`Build output directory not found: ${distDir}`);
  }

  // 1. Check installer exists
  const files = fs.readdirSync(distDir);
  const exeName = files.find(f => f.endsWith('.exe') && f.includes(version) && f.includes('Setup'));
  if (!exeName) {
    throw new Error(`No installer executable matching version ${version} found in ${distDir}`);
  }
  const exePath = path.join(distDir, exeName);
  const exeStat = fs.statSync(exePath);
  console.log(`[PASS] Installer found: ${exeName} (${exeStat.size} bytes)`);

  // 2. Check latest.yml exists and matches
  const latestYmlPath = path.join(distDir, 'latest.yml');
  if (!fs.existsSync(latestYmlPath)) {
    throw new Error(`latest.yml not found in ${distDir}`);
  }
  const latestYml = fs.readFileSync(latestYmlPath, 'utf8');
  if (!latestYml.includes(version)) {
    throw new Error(`latest.yml does not reference version ${version}`);
  }
  console.log(`[PASS] latest.yml references version ${version}`);

  // 3. Check ota-manifest.json exists and matches
  const manifestPath = path.join(distDir, 'ota-manifest.json');
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`ota-manifest.json not found in ${distDir}`);
  }
  const manifestText = fs.readFileSync(manifestPath, 'utf8');
  let manifest;
  try {
    manifest = JSON.parse(manifestText);
  } catch (err) {
    throw new Error(`ota-manifest.json is malformed JSON: ${err.message}`);
  }
  if (manifest.version !== version) {
    throw new Error(`ota-manifest.json version '${manifest.version}' does not match package.json '${version}'`);
  }
  console.log(`[PASS] ota-manifest.json version matches (${manifest.version})`);

  // 4. Verify OTA cryptographic signature
  const sigPath = path.join(distDir, 'ota-manifest.sig');
  if (!fs.existsSync(sigPath)) {
    throw new Error(`ota-manifest.sig not found in ${distDir}`);
  }
  const sigText = fs.readFileSync(sigPath, 'utf8').trim();
  await sodium.ready;
  const B64 = sodium.base64_variants.URLSAFE_NO_PADDING;
  const sig = sodium.from_base64(sigText, B64);
  const manBytes = Buffer.from(manifestText, 'utf8');
  let sigValid = false;
  for (const pub of otaPubs) {
    if (sodium.crypto_sign_verify_detached(sig, manBytes, sodium.from_base64(pub, B64))) {
      sigValid = true;
      break;
    }
  }
  if (!sigValid) {
    throw new Error(`ota-manifest.sig failed cryptographic signature verification against baked OTA public keys!`);
  }
  console.log(`[PASS] Cryptographic signature valid with baked OTA public key.`);

  // 5. Verify OTA manifest files match disk hash via ota.js
  const verifiedList = await verifyDownloaded([exePath], manifest);
  console.log(`[PASS] Manifest hash verification passed for ${verifiedList.length} installer file(s).`);

  console.log(`\n===> All release pre-flight checks PASSED for v${version}!\n`);
}

verify().catch(err => {
  console.error(`\n[FAIL] Release verification failed: ${err.message}\n`);
  process.exit(1);
});
