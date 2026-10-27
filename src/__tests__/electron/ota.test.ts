import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  afterAll, beforeAll, describe, expect, it, vi,
} from 'vitest';

// The OTA verifier is Electron main-process CommonJS, shared with the release
// gate script. These tests pin the behaviour the client depends on: fail closed
// on anything that is not a valid signature over the exact installer bytes.
const require = createRequire(import.meta.url);

type Manifest = { v: number; version: string; files: Array<{ name: string; sha256: string; size: number }> };
type SignedManifest = { text: string; sigText: string; pub: string };

const ota = require('../../../electron/ota.js') as {
  OTA_PUBLIC_KEYS: string[];
  cmpVer: (a: string, b: string) => number;
  verifyManifestText: (man: string, sig: string, keys?: string[]) => Promise<Manifest>;
  sha256File: (p: string) => Promise<string>;
  createOtaVerifier: (opts: Record<string, unknown>) => {
    selfTest: () => Promise<{ ok: boolean; error?: string }>;
    verifyInstaller: (p: string, v?: string) => Promise<{ ok: boolean; error?: string; manifest?: Manifest }>;
    fetchManifest: (opts?: { force?: boolean }) => Promise<Manifest>;
  };
};

const sodium = require('libsodium-wrappers') as {
  ready: Promise<void>;
  crypto_sign_keypair: () => { publicKey: Uint8Array; privateKey: Uint8Array };
  crypto_sign_detached: (msg: Uint8Array, key: Uint8Array) => Uint8Array;
  to_base64: (bytes: Uint8Array, variant: number) => string;
  base64_variants: { URLSAFE_NO_PADDING: number };
};

let keypair: { publicKey: Uint8Array; privateKey: Uint8Array };
let tmpDir: string;

beforeAll(async () => {
  await sodium.ready;
  keypair = sodium.crypto_sign_keypair();
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'blm-ota-test-'));
});

afterAll(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function sign(manifest: Manifest): SignedManifest {
  const text = JSON.stringify(manifest);
  const sig = sodium.crypto_sign_detached(Buffer.from(text, 'utf8'), keypair.privateKey);
  return {
    text,
    sigText: sodium.to_base64(sig, sodium.base64_variants.URLSAFE_NO_PADDING),
    pub: sodium.to_base64(keypair.publicKey, sodium.base64_variants.URLSAFE_NO_PADDING),
  };
}

function writeInstaller(name: string, contents: string) {
  const file = path.join(tmpDir, name);
  fs.writeFileSync(file, contents);
  return file;
}

async function makeManifest(installerPath: string, version = '2026.10.10'): Promise<Manifest> {
  const sha256 = await ota.sha256File(installerPath);
  return {
    v: 1,
    version,
    files: [{ name: path.basename(installerPath), sha256, size: fs.statSync(installerPath).size }],
  };
}

describe('verifyManifestText', () => {
  it('accepts a signature made by the trusted key', async () => {
    const installer = writeInstaller('ok.exe', 'payload');
    const signed = sign(await makeManifest(installer));
    const manifest = await ota.verifyManifestText(signed.text, signed.sigText, [signed.pub]);
    expect(manifest.version).toBe('2026.10.10');
  });

  it('accepts a manifest signed by any key in the trusted list', async () => {
    const installer = writeInstaller('ok2.exe', 'payload');
    const signed = sign(await makeManifest(installer));
    const manifest = await ota.verifyManifestText(signed.text, signed.sigText, ['AAAA', signed.pub]);
    expect(manifest.version).toBe('2026.10.10');
  });

  it('rejects a manifest modified after signing', async () => {
    const installer = writeInstaller('tamper.exe', 'payload');
    const signed = sign(await makeManifest(installer));
    const tampered = signed.text.replace('2026.10.10', '2026.10.11');
    await expect(ota.verifyManifestText(tampered, signed.sigText, [signed.pub]))
      .rejects.toThrow(/does not match any trusted key/);
  });

  it('rejects a signature from an untrusted key', async () => {
    const installer = writeInstaller('untrusted.exe', 'payload');
    const signed = sign(await makeManifest(installer));
    await expect(ota.verifyManifestText(signed.text, signed.sigText, [ota.OTA_PUBLIC_KEYS[0]]))
      .rejects.toThrow(/does not match any trusted key/);
  });

  it('rejects a malformed signature blob', async () => {
    const installer = writeInstaller('badsig.exe', 'payload');
    const signed = sign(await makeManifest(installer));
    await expect(ota.verifyManifestText(signed.text, 'not-a-signature', [signed.pub]))
      .rejects.toThrow(/does not match any trusted key|not valid base64url/);
  });

  it('rejects an unexpected manifest shape', async () => {
    const text = JSON.stringify({ v: 2, version: '2026.10.10', files: [] });
    const sig = sodium.crypto_sign_detached(Buffer.from(text, 'utf8'), keypair.privateKey);
    const sigText = sodium.to_base64(sig, sodium.base64_variants.URLSAFE_NO_PADDING);
    const pub = sodium.to_base64(keypair.publicKey, sodium.base64_variants.URLSAFE_NO_PADDING);
    await expect(ota.verifyManifestText(text, sigText, [pub])).rejects.toThrow(/unexpected shape/);
  });
});

describe('createOtaVerifier.verifyInstaller', () => {
  function verifierFor(manifest: Manifest) {
    const signed = sign(manifest);
    const fetchImpl = vi.fn(async (url: string) => (url.endsWith('.sig') ? signed.sigText : signed.text));
    return ota.createOtaVerifier({
      feedUrl: 'https://updates.example.test',
      isPackaged: true,
      publicKeys: [signed.pub],
      fetchImpl,
    });
  }

  it('accepts an installer matching the signed manifest', async () => {
    const installer = writeInstaller('good.exe', 'installer-bytes');
    const verdict = await verifierFor(await makeManifest(installer)).verifyInstaller(installer, '2026.10.10');
    expect(verdict.ok).toBe(true);
    expect(verdict.manifest?.version).toBe('2026.10.10');
  });

  it('rejects an installer whose bytes changed', async () => {
    const installer = writeInstaller('mismatch.exe', 'installer-bytes');
    const manifest = await makeManifest(installer);
    fs.appendFileSync(installer, 'tampered');
    const verdict = await verifierFor(manifest).verifyInstaller(installer, '2026.10.10');
    expect(verdict.ok).toBe(false);
    expect(verdict.error).toMatch(/size|sha256/);
  });

  it('rejects a file the manifest does not list', async () => {
    const listed = writeInstaller('listed.exe', 'a');
    const other = writeInstaller('other.exe', 'b');
    const verdict = await verifierFor(await makeManifest(listed)).verifyInstaller(other, '2026.10.10');
    expect(verdict.ok).toBe(false);
    expect(verdict.error).toMatch(/not listed/);
  });

  it('rejects a manifest for a different version', async () => {
    const installer = writeInstaller('version.exe', 'a');
    const verdict = await verifierFor(await makeManifest(installer, '2026.10.9')).verifyInstaller(installer, '2026.10.10');
    expect(verdict.ok).toBe(false);
    expect(verdict.error).toMatch(/manifest is for 2026\.10\.9/);
  });

  it('rejects a missing installer', async () => {
    const verdict = await verifierFor({ v: 1, version: '2026.10.10', files: [] })
      .verifyInstaller(path.join(tmpDir, 'nope.exe'), '2026.10.10');
    expect(verdict.ok).toBe(false);
    expect(verdict.error).toMatch(/missing/);
  });

  it('fails closed when the feed is unreachable', async () => {
    const installer = writeInstaller('offline.exe', 'a');
    const verifier = ota.createOtaVerifier({
      feedUrl: 'https://updates.example.test',
      isPackaged: true,
      publicKeys: [ota.OTA_PUBLIC_KEYS[0]],
      fetchImpl: vi.fn(async () => {
        throw new Error('http_503');
      }),
    });
    const verdict = await verifier.verifyInstaller(installer, '2026.10.10');
    expect(verdict.ok).toBe(false);
    expect(verdict.error).toMatch(/http_503/);
  });

  it('self-tests the real shipped public key', async () => {
    const verdict = await ota.createOtaVerifier({ feedUrl: 'https://updates.example.test' }).selfTest();
    expect(verdict).toEqual({ ok: true });
  });
});

describe('cmpVer', () => {
  it('orders dotted numeric versions', () => {
    expect(ota.cmpVer('2026.10.10', '2026.10.9')).toBe(1);
    expect(ota.cmpVer('2026.10.9', '2026.10.10')).toBe(-1);
    expect(ota.cmpVer('2026.10.10', '2026.10.10')).toBe(0);
    expect(ota.cmpVer('v2026.10.10', '2026.10.10')).toBe(0);
  });
});
