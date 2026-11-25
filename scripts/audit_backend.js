#!/usr/bin/env node
// Security audit for the Python backend (pip-audit over backend/.venv).
//
// Exit codes:
//   0  no known vulnerabilities
//   1  pip-audit reported findings (or the environment is unusable)
//
// Findings are reported but never enforced by a build. Run it manually:
//   npm run audit:backend

const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const root = path.resolve(__dirname, '..');
const backend = path.join(root, 'backend');

const pythonCandidates = [
  path.join(backend, '.venv', 'Scripts', 'python.exe'),
  path.join(backend, '.venv', 'bin', 'python'),
];
const python = pythonCandidates.find((p) => fs.existsSync(p));
if (!python) {
  console.error('No backend/.venv found. Create one first:');
  console.error('  cd backend');
  console.error('  python -m venv .venv');
  console.error('  .venv\\Scripts\\pip install -e ".[dev]" -c constraints.txt pip-audit');
  process.exit(1);
}

const sitePackages = spawnSync(
  python,
  ['-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'],
  { encoding: 'utf8' },
).stdout.trim();
if (!sitePackages) {
  console.error('Could not locate the virtualenv site-packages directory.');
  process.exit(1);
}

const probe = spawnSync(python, ['-c', 'import pip_audit'], { encoding: 'utf8' });
if (probe.status !== 0) {
  console.error('pip-audit is not installed in backend/.venv. Install it with:');
  console.error(`  ${python} -m pip install pip-audit`);
  process.exit(1);
}

console.log(`Auditing ${sitePackages}`);
const res = spawnSync(
  python,
  ['-m', 'pip_audit', '--path', sitePackages, '--progress-spinner', 'off'],
  { stdio: 'inherit', cwd: backend },
);

// pip-audit exits 1 when it finds vulnerabilities, 0 when the tree is clean.
if (res.status === 0) {
  console.log('\nbackend: no known vulnerabilities.');
} else if (res.status === 1) {
  console.error('\nbackend: vulnerabilities found (see list above).');
  process.exit(1);
} else {
  console.error('\nbackend: pip-audit failed to run.');
  process.exit(res.status ?? 1);
}
