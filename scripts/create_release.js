const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const packageJson = require('../package.json');
const version = `v${packageJson.version}`;

try {
  console.log(`==> Checking if release ${version} exists...`);
  // This will throw if the release doesn't exist
  execSync(`gh release view ${version}`, { stdio: 'ignore' });
  console.log(`Release ${version} already exists.`);
} catch (e) {
  console.log(`==> Creating draft release for ${version} to prevent electron-builder upload race condition...`);
  try {
    execSync(`gh release create ${version} --draft --title "${packageJson.version}" --notes "Release ${packageJson.version}"`, { stdio: 'inherit' });
    console.log(`Draft release ${version} created successfully.`);
  } catch (createError) {
    console.warn(`Warning: Failed to pre-create release. Electron-builder will attempt to create it. (${createError.message})`);
  }
}
