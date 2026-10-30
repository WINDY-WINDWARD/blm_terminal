import { expect, test, type Page } from '@playwright/test';

const PANEL_1 = '[data-tour-panel-id="panel-1"]';
const PANEL_2 = '[data-tour-panel-id="panel-2"]';
const OVERLAY = '[data-widget-tour-overlay]';

const ALL_COMMANDS = [
  'TOP',
  'WATCH',
  'CHART',
  'ORDER',
  'POS',
  'COMPANY',
  'LARGEDEALS',
  'BREAKOUTS',
  'NEWS',
  'ANALYSIS',
  'NOTIF',
  'SCAN',
  'ANNC',
  'SCREENER',
  'AI',
  'PORTFOLIO',
  'PICKS',
  'ADMIN',
  'DOCS',
];

async function mockBackend(page: Page) {
  const seen: Record<string, number> = {};

  await page.route('**/api/py/eula-status', async (route) => {
    await route.fulfill({
      status: 200,
      json: { accepted: true, version: 'eula-v1', accepted_at: 123 },
    });
  });
  await page.route('**/api/py/auth/setup-status', async (route) => {
    await route.fulfill({ status: 200, json: { needs_setup: false } });
  });
  await page.route('**/api/py/auth/me', async (route) => {
    await route.fulfill({ status: 200, json: { id: 1, username: 'admin', is_admin: true } });
  });
  await page.route('**/api/py/ai/status', async (route) => {
    await route.fulfill({ status: 200, json: { provider: 'zen', is_configured: false } });
  });
  await page.route('**/api/py/widget-tours', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as { command?: string } | null;
      if (body?.command) seen[body.command] = Date.now();
      await route.fulfill({ status: 200, json: { ok: true } });
      return;
    }
    await route.fulfill({ status: 200, json: { seen } });
  });
}

async function boot(
  page: Page,
  options: { panels: Record<string, string>; unseen?: string[] },
) {
  const unseen = new Set(options.unseen ?? []);
  const seen: Record<string, number> = {};
  for (const command of ALL_COMMANDS) {
    if (!unseen.has(command)) seen[command] = 1;
  }

  // PANEL_LAYOUTS only defines 2, 4, 6, and 8 panels. A single-panel map has no layout.
  const panelMap: Record<string, string> = { ...options.panels };
  for (let index = Object.keys(panelMap).length; index < 2; index += 1) {
    panelMap[`panel-${index + 1}`] = 'EMPTY';
  }

  await page.addInitScript(
    ({ seenMap, panelMap }) => {
      localStorage.setItem('terminal.onboarding.v1', 'true');
      localStorage.setItem('terminal.tutorial.v1', '"done"');
      localStorage.setItem('terminal.advancedScrapingConsent', 'false');
      localStorage.setItem('terminal.panelCount', String(Object.keys(panelMap).length));
      localStorage.setItem('terminal.activePanels', JSON.stringify(panelMap));
      localStorage.setItem('terminal.focusedPanel', JSON.stringify('panel-1'));
      localStorage.setItem('terminal.widgetTours.seen.v1', JSON.stringify(seenMap));
      localStorage.removeItem('terminal.widgetTours.pending.v1');
    },
    { seenMap: seen, panelMap },
  );

  await page.goto('/');
  await expect(page.locator('#terminal-command-input')).toBeVisible({ timeout: 20_000 });
}

async function openWidget(page: Page, command: string) {
  await page.locator('#terminal-command-input').fill(command);
  await page.locator('#terminal-command-input').press('Enter');
}

test('first open of a widget starts its tour inside the panel', async ({ page }) => {
  await mockBackend(page);
  await boot(page, { panels: { 'panel-1': 'EMPTY' }, unseen: ['CHART'] });

  await openWidget(page, 'CHART');

  const overlay = page.locator(OVERLAY);
  await expect(overlay).toBeVisible({ timeout: 20_000 });
  await expect(overlay).toContainText('STEP 1 OF 5');

  const panelBox = await page.locator(PANEL_1).boundingBox();
  const overlayBox = await overlay.boundingBox();
  expect(panelBox).not.toBeNull();
  expect(overlayBox).not.toBeNull();
  if (panelBox && overlayBox) {
    expect(overlayBox.x).toBeGreaterThanOrEqual(panelBox.x - 1);
    expect(overlayBox.y).toBeGreaterThanOrEqual(panelBox.y - 1);
    expect(overlayBox.x + overlayBox.width).toBeLessThanOrEqual(panelBox.x + panelBox.width + 1);
    expect(overlayBox.y + overlayBox.height).toBeLessThanOrEqual(panelBox.y + panelBox.height + 1);
  }

  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('terminal.widgetTours.seen.v1')), {
      timeout: 10_000,
    })
    .toContain('CHART');
});

test('seen widget does not auto-tour again', async ({ page }) => {
  await mockBackend(page);
  await boot(page, { panels: { 'panel-1': 'EMPTY' } });

  await openWidget(page, 'CHART');
  await expect(page.locator(PANEL_1)).toContainText('CHART', { timeout: 20_000 });
  await expect(page.locator(OVERLAY)).toHaveCount(0);
});

test('DOCS replays the tour of an open widget', async ({ page }) => {
  await mockBackend(page);
  await boot(page, { panels: { 'panel-1': 'CHART', 'panel-2': 'DOCS' } });

  const replay = page.locator(`${PANEL_2} button:has-text("REPLAY TOUR")`);
  await expect(replay).toBeVisible({ timeout: 20_000 });
  await replay.click();

  await expect(page.locator(`${PANEL_1} ${OVERLAY}`)).toContainText('STEP 1 OF 5', {
    timeout: 10_000,
  });
});

test('DOCS shows an open hint when the widget is not in a panel', async ({ page }) => {
  await mockBackend(page);
  await boot(page, { panels: { 'panel-1': 'DOCS' } });

  await expect(page.locator(PANEL_1)).toContainText('Widget Reference', { timeout: 20_000 });
  await page.locator(`${PANEL_1} button:has-text("CHART")`).first().click();
  await page.locator(`${PANEL_1} button:has-text("REPLAY TOUR")`).click();

  await expect(page.locator(PANEL_1)).toContainText('OPEN CHART IN A PANEL TO REPLAY THIS TOUR', {
    timeout: 10_000,
  });
  await expect(page.locator(OVERLAY)).toHaveCount(0);
});
