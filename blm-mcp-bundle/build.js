#!/usr/bin/env node
/**
 * Build script for BLM MCP Bundle
 * 
 * Creates a Claude Desktop .mcpb plugin that proxies tool calls to the BLM backend.
 * 
 * Usage:
 *   node build.js                    # Uses localhost:4455
 *   node build.js --port 8000        # Custom port on localhost
 *   node build.js --url http://host:4455  # Full URL
 * 
 * Environment:
 *   PYTHON_BACKEND_URL=http://host:4455 node build.js
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const BUNDLE_DIR = __dirname;
const DIST_DIR = path.join(BUNDLE_DIR, 'dist');

// Parse arguments
const args = process.argv.slice(2);
let remoteHost = 'localhost';
let remotePort = 4455;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--port' && args[i + 1]) {
    remotePort = parseInt(args[i + 1], 10);
    i++;
  } else if (args[i] === '--url' && args[i + 1]) {
    const url = new URL(args[i + 1]);
    remoteHost = url.hostname;
    remotePort = parseInt(url.port, 10);
    i++;
  }
}

// Check env var (overrides defaults if set)
if (process.env.PYTHON_BACKEND_URL) {
  try {
    const url = new URL(process.env.PYTHON_BACKEND_URL);
    remoteHost = url.hostname;
    remotePort = parseInt(url.port, 10);
  } catch (e) {
    console.error('Invalid PYTHON_BACKEND_URL:', process.env.PYTHON_BACKEND_URL);
    process.exit(1);
  }
}

console.log(`Building BLM MCP Bundle with remote: ${remoteHost}:${remotePort}`);

// Read manifest template
const manifestPath = path.join(BUNDLE_DIR, 'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));

// Update manifest with actual host/port defaults
manifest.user_config.remote_host.default = remoteHost;
manifest.user_config.remote_port.default = remotePort;

// Bake into env as fallback for Claude Desktop versions that don't resolve templates
manifest.server.mcp_config.env.REMOTE_HOST = remoteHost;
manifest.server.mcp_config.env.REMOTE_PORT = remotePort.toString();
manifest.server.mcp_config.env.REMOTE_PATH = '/api/mcp/mcp';

// Create dist directory
if (!fs.existsSync(DIST_DIR)) {
  fs.mkdirSync(DIST_DIR, { recursive: true });
}

// Write updated manifest to dist
const distManifestPath = path.join(DIST_DIR, 'manifest.json');
fs.writeFileSync(distManifestPath, JSON.stringify(manifest, null, 2));

// Copy server files
const serverDir = path.join(BUNDLE_DIR, 'server');
const distServerDir = path.join(DIST_DIR, 'server');

if (!fs.existsSync(distServerDir)) {
  fs.mkdirSync(distServerDir, { recursive: true });
}

// Copy index.js
fs.copyFileSync(
  path.join(serverDir, 'index.js'),
  path.join(distServerDir, 'index.js')
);

// Create package.json for the bundle (optional but helps with mcpb)
const packageJson = {
  name: 'blm-mcp-proxy',
  version: '1.0.0',
  description: 'BLM MCP Proxy for Claude Desktop',
  main: 'server/index.js',
 engines: {
    node: '>=14'
  }
};
fs.writeFileSync(
  path.join(DIST_DIR, 'package.json'),
  JSON.stringify(packageJson, null, 2)
);

console.log('Manifest and server files prepared.');

// Check if mcpb is installed
let mcpbPath;
try {
  execSync('mcpb --version', { stdio: 'ignore' });
  mcpbPath = 'mcpb';
} catch (e) {
  // Try npx
  try {
    execSync('npx @anthropic-ai/mcpb --version', { stdio: 'ignore' });
    mcpbPath = 'npx @anthropic-ai/mcpb';
  } catch (e2) {
    console.error('Error: mcpb CLI not found.');
    console.error('Please install it with: npm install -g @anthropic-ai/mcpb');
    process.exit(1);
  }
}

// Run mcpb pack
console.log('Running mcpb pack...');
try {
  execSync(`${mcpbPath} pack`, { 
    cwd: DIST_DIR,
    stdio: 'inherit'
  });
  
  // Find the generated .mcpb file
  const mcpbFiles = fs.readdirSync(DIST_DIR).filter(f => f.endsWith('.mcpb'));
  
  if (mcpbFiles.length > 0) {
    const mcpbFile = mcpbFiles[0];
    const outputPath = path.join(BUNDLE_DIR, mcpbFile);
    
    // Move to bundle root
    fs.copyFileSync(path.join(DIST_DIR, mcpbFile), outputPath);
    fs.unlinkSync(path.join(DIST_DIR, mcpbFile));
    
    console.log(`\n✓ Bundle created: ${outputPath}`);
    console.log(`  Remote: ${remoteHost}:${remotePort}`);
    console.log('\nTo install:');
    console.log('  1. Open Claude Desktop');
    console.log('  2. Go to Developer → Extensions → Install Extension');
    console.log(`  3. Select: ${outputPath}`);
  } else {
    console.error('Error: .mcpb file not generated');
    process.exit(1);
  }
} catch (e) {
  console.error('Error running mcpb pack:', e.message);
  process.exit(1);
}
