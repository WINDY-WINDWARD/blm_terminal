#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const packageJsonPath = path.join(__dirname, '..', 'package.json');
const pkg = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8'));

// Format: YYYY.M.B (e.g. 2026.9.1)
const now = new Date();
const year = now.getFullYear();
const month = now.getMonth() + 1; // 1-12

let buildNumber = 1;

if (pkg.version) {
  const parts = pkg.version.split('.');
  if (parts.length === 3) {
    const prevYear = parseInt(parts[0], 10);
    const prevMonth = parseInt(parts[1], 10);
    const prevBuild = parseInt(parts[2], 10);

    if (prevYear === year && prevMonth === month && !isNaN(prevBuild)) {
      buildNumber = prevBuild + 1;
    }
  }
}

const newVersion = `${year}.${month}.${buildNumber}`;
pkg.version = newVersion;

fs.writeFileSync(packageJsonPath, JSON.stringify(pkg, null, 2) + '\n');
console.log(`==> Bumped version in package.json to ${newVersion}`);

// Check if git working tree is clean (excluding package.json which we just changed)
try {
  console.log(`==> Creating release commit and git tag v${newVersion}...`);
  execSync('git add package.json package-lock.json', { stdio: 'inherit' });
  execSync(`git commit -m "chore(release): v${newVersion}"`, { stdio: 'inherit' });
  execSync(`git tag v${newVersion}`, { stdio: 'inherit' });
  console.log(`\nRelease v${newVersion} tagged successfully!`);
  console.log(`\nTo publish the release and trigger the CI/CD build, run:`);
  console.log(`  git push origin HEAD --follow-tags\n`);
} catch (err) {
  console.error('Git tagging error:', err.message);
  process.exit(1);
}
