/**
 * Capture DOCS screenshots from the real desktop app through the Chrome DevTools Protocol.
 *
 * Usage:
 *   npm run docs:screenshots
 *   npm run docs:screenshots -- --only=CHART,ORDER
 *   BLM_SCREENSHOT_EXE="C:\\path\\BLM Terminal.exe" npm run docs:screenshots
 *
 * The script starts the installed app with --remote-debugging-port, pins the terminal to a
 * single panel, marks every widget tour as seen, then reloads the app once per widget and
 * screenshots the panel. It restores the previous localStorage values before it exits.
 *
 * The app must not already be running without the debug port. The single-instance lock makes
 * a second copy exit immediately.
 */
import { connect } from 'node:net';
import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { spawn } from 'node:child_process';
import { chromium } from '@playwright/test';

const WORKSPACE_ROOT = path.resolve(import.meta.dirname, '..');
const OUTPUT_DIR = path.join(WORKSPACE_ROOT, 'public', 'docs', 'widgets');
const CDP_PORT = Number(process.env.BLM_SCREENSHOT_CDP_PORT ?? 9222);
const CDP_URL = `http://127.0.0.1:${CDP_PORT}`;

const STORAGE_KEYS = {
  panels: 'terminal.activePanels',
  panelCount: 'terminal.panelCount',
  focusedPanel: 'terminal.focusedPanel',
  seen: 'terminal.widgetTours.seen.v1',
  pending: 'terminal.widgetTours.pending.v1',
  tutorial: 'terminal.tutorial.v1',
  onboarding: 'terminal.onboarding.v1',
};

// ORDER is excluded: the deck renders only a gateway error until OpenAlgo is configured,
// so it has no screenshot and the DOCS page shows the text reference alone.
const WIDGET_COMMANDS = [
  'CHART',
  'WATCH',
  'TOP',
  'POS',
  'COMPANY',
  'LARGEDEALS',
  'BREAKOUTS',
  'NEWS',
  'ANALYSIS',
  'NOTIF',
  'ANNC',
  'SCAN',
  'SCREENER',
  'AI',
  'PORTFOLIO',
  'ADMIN',
  'PICKS',
  'DOCS',
];

const PANEL_READY_TIMEOUT_MS = 180_000;
const SETTLE_MS = 1_200;

function parseOnlyArgument() {
  const arg = process.argv.find((value) => value.startsWith('--only='));
  if (!arg) return null;
  const names = arg
    .slice('--only='.length)
    .split(',')
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean);
  return names.length > 0 ? new Set(names) : null;
}

function findExecutable() {
  if (process.env.BLM_SCREENSHOT_EXE) {
    const fromEnv = path.resolve(process.env.BLM_SCREENSHOT_EXE);
    if (existsSync(fromEnv)) return fromEnv;
    throw new Error(`BLM_SCREENSHOT_EXE does not exist: ${fromEnv}`);
  }

  const unpacked = path.join(WORKSPACE_ROOT, 'dist-desktop', 'win-unpacked', 'BLM Terminal.exe');
  if (existsSync(unpacked)) return unpacked;

  const localAppData = process.env.LOCALAPPDATA;
  if (localAppData) {
    const programsDir = path.join(localAppData, 'Programs');
    if (existsSync(programsDir)) {
      for (const entry of readdirSync(programsDir)) {
        const candidate = path.join(programsDir, entry, 'BLM Terminal.exe');
        if (existsSync(candidate)) return candidate;
      }
    }
  }

  throw new Error(
    'Cannot find BLM Terminal.exe. Set BLM_SCREENSHOT_EXE or build dist-desktop/win-unpacked first.',
  );
}

function waitForPort(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = connect({ host: '127.0.0.1', port });
      socket.setTimeout(1_000);
      socket.once('connect', () => {
        socket.destroy();
        resolve();
      });
      socket.once('timeout', () => {
        socket.destroy();
        retry();
      });
      socket.once('error', () => {
        socket.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() > deadline) {
        reject(new Error(`Timed out waiting for CDP on port ${port}`));
        return;
      }
      setTimeout(attempt, 500);
    };
    attempt();
  });
}

async function readLocalStorage(page) {
  return page.evaluate((keys) => {
    const snapshot = {};
    for (const key of Object.values(keys)) {
      snapshot[key] = window.localStorage.getItem(key);
    }
    return snapshot;
  }, STORAGE_KEYS);
}

async function writeLocalStorage(page, values) {
  await page.evaluate((entries) => {
    for (const [key, value] of Object.entries(entries)) {
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    }
  }, values);
}

async function waitForTerminal(page) {
  await page.waitForSelector('[data-tour-panel-id="panel-1"]', {
    timeout: PANEL_READY_TIMEOUT_MS,
  });
}

async function pickTerminalPage(browser, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const context of browser.contexts()) {
      for (const candidate of context.pages()) {
        if (candidate.isClosed()) continue;
        const url = candidate.url();
        if (url.startsWith('http://127.0.0.1') || url.startsWith('http://localhost')) {
          return candidate;
        }
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error('No terminal page found through CDP. The app may still be on the splash screen.');
}

async function hideTourOverlays(page) {
  await page.evaluate(() => {
    for (const node of document.querySelectorAll('[data-widget-tour-overlay]')) {
      node.remove();
    }
  });
}

const BUSY_MARKERS = ['LOADING', 'INITIALIZING', 'SYNCING', 'OPTIMIZING', 'FETCHING'];

// Documentation seed for POS. The paper book is empty on a fresh install, and an empty
// table does not show what the widget is for. These rows are deleted right after capture.
const SEED_PAPER_TRADES = [
  { symbol: 'RELIANCE', quantity: 120, price: 1385.5, notes: 'Documentation capture' },
  { symbol: 'TCS', quantity: 40, price: 3120, notes: 'Documentation capture' },
  { symbol: 'HDFCBANK', quantity: 60, price: 1495.25, notes: 'Documentation capture' },
];

async function seedPaperTrades(page) {
  return page.evaluate(async (trades) => {
    const created = [];
    for (const trade of trades) {
      const res = await fetch('/api/py/paper-trades', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(trade),
      });
      if (!res.ok) continue;
      const data = await res.json();
      if (typeof data?.id === 'number') created.push(data.id);
    }
    return created;
  }, SEED_PAPER_TRADES);
}

async function clearPaperTrades(page, tradeIds) {
  if (tradeIds.length === 0) return;
  await page
    .evaluate(async (ids) => {
      for (const id of ids) {
        await fetch(`/api/py/paper-trades/${id}`, { method: 'DELETE' });
      }
    }, tradeIds)
    .catch(() => undefined);
}

// Reloading the app re-runs every widget query. Capture only after the panel stops
// showing a transient loading label, so a screenshot never records a spinner.
async function waitForWidgetReady(page, command) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const text = await page
      .evaluate(() => {
        const panel = document.querySelector('[data-tour-panel-id="panel-1"]');
        return panel ? panel.innerText : '';
      })
      .catch(() => '');
    const upper = text.toUpperCase();
    const busy = BUSY_MARKERS.some((marker) => upper.includes(marker));
    if (text.trim().length > 0 && !busy) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  console.warn(`  ${command} still reported a loading state after 30 s. Capturing anyway.`);
}

async function main() {
  const only = parseOnlyArgument();
  const targets = only ? WIDGET_COMMANDS.filter((command) => only.has(command)) : WIDGET_COMMANDS;
  if (targets.length === 0) throw new Error('No matching widget command in --only.');

  mkdirSync(OUTPUT_DIR, { recursive: true });

  const executable = findExecutable();
  console.log(`App: ${executable}`);
  console.log(`Output: ${OUTPUT_DIR}`);
  console.log(`Widgets: ${targets.join(', ')}`);

  await waitForPort(CDP_PORT, 1_000).catch(() => undefined);
  const appProcess = spawn(executable, [`--remote-debugging-port=${CDP_PORT}`], {
    detached: false,
    stdio: 'ignore',
  });

  let browser;
  let page;
  let original = null;
  let seededPaperTrades = [];
  try {
    await waitForPort(CDP_PORT, 90_000);
    browser = await chromium.connectOverCDP(CDP_URL);

    if (browser.contexts().length === 0) throw new Error('No browser context found through CDP.');

    page = await pickTerminalPage(browser, 120_000);

    // A freshly packaged build runs on a new origin, so it has no saved session. When the
    // caller supplies a session snapshot, seed it before the terminal mounts.
    const seedAuth = process.env.BLM_SCREENSHOT_SEED_AUTH;
    if (seedAuth) {
      await writeLocalStorage(page, { 'terminal.auth': seedAuth });
      await page.reload({ waitUntil: 'domcontentloaded' });
    }

    await page.bringToFront();
    try {
      await waitForTerminal(page);
    } catch (error) {
      const replacement = await pickTerminalPage(browser, 120_000);
      if (replacement === page) throw error;
      page = replacement;
      await page.bringToFront();
      await waitForTerminal(page);
    }
    console.log('Terminal ready. If a login screen was visible, the session was already signed in.');

    original = await readLocalStorage(page);

    const panelsJson = JSON.stringify({ 'panel-1': targets[0], 'panel-2': '' });
    const seenJson = JSON.stringify(
      Object.fromEntries(WIDGET_COMMANDS.map((command) => [command, Date.now()])),
    );

    await writeLocalStorage(page, {
      [STORAGE_KEYS.panels]: panelsJson,
      [STORAGE_KEYS.panelCount]: JSON.stringify(2),
      [STORAGE_KEYS.focusedPanel]: JSON.stringify('panel-1'),
      [STORAGE_KEYS.seen]: seenJson,
      [STORAGE_KEYS.pending]: JSON.stringify([]),
      [STORAGE_KEYS.tutorial]: JSON.stringify('done'),
      [STORAGE_KEYS.onboarding]: JSON.stringify(true),
    });

    for (const command of targets) {
      if (command === 'POS' && process.env.BLM_SCREENSHOT_SEED_POS === '1') {
        seededPaperTrades = await seedPaperTrades(page);
        if (seededPaperTrades.length === 0) {
          console.warn('  POS seeding created no paper trades.');
        }
      }

      await page.evaluate(
        ({ key, value }) => window.localStorage.setItem(key, value),
        {
          key: STORAGE_KEYS.panels,
          value: JSON.stringify({ 'panel-1': command, 'panel-2': '' }),
        },
      );

      await page.reload({ waitUntil: 'domcontentloaded' });
      await waitForTerminal(page);
      await waitForWidgetReady(page, command);
      await page.waitForTimeout(SETTLE_MS);
      await hideTourOverlays(page);

      const panel = page.locator('[data-tour-panel-id="panel-1"]');
      const box = await panel.boundingBox();
      if (!box || box.width < 50 || box.height < 50) {
        throw new Error(`Panel for ${command} has no usable size.`);
      }

      const target = path.join(OUTPUT_DIR, `${command}.png`);
      await panel.screenshot({ path: target, animations: 'disabled' });
      console.log(`Captured ${command} -> ${path.relative(WORKSPACE_ROOT, target)}`);

      if (command === 'POS' && seededPaperTrades.length > 0) {
        await clearPaperTrades(page, seededPaperTrades);
        seededPaperTrades = [];
      }
    }

    await writeLocalStorage(page, original);
    await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => undefined);
    original = null;
    writeFileSync(
      path.join(OUTPUT_DIR, 'README.md'),
      [
        '# Widget screenshots',
        '',
        'These PNG files are captured from the installed BLM Terminal desktop app through CDP.',
        'Regenerate them after a widget layout change:',
        '',
        '```powershell',
        'npm run docs:screenshots',
        '```',
        '',
        'Use `-- --only=CHART,ORDER` to recapture a subset.',
        '',
        'ORDER has no screenshot. The order deck shows only a gateway error until OpenAlgo is',
        'configured, so its DOCS page is text only.',
        '',
        'POS needs `$env:BLM_SCREENSHOT_SEED_POS="1"` to seed three paper trades for the capture.',
        'The script deletes those trades after the screenshot.',
        '',
      ].join('\n'),
      'utf-8',
    );
  } finally {
    if (page && seededPaperTrades.length > 0) {
      await clearPaperTrades(page, seededPaperTrades);
    }
    if (page && original) {
      await writeLocalStorage(page, original).catch(() => undefined);
      await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => undefined);
    }
    if (browser) await browser.close().catch(() => undefined);
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(appProcess.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      appProcess.kill();
    }
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
