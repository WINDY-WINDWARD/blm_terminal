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

async function mockNotifications(page: Page) {
  await page.route('**/api/py/markets/stocks-categories', async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        RELIANCE: { industry: 'Oil & Gas', sector: 'Energy' },
        TCS: { industry: 'IT Services', sector: 'IT' },
      },
    });
  });
  await page.route('**/api/py/notifications**', async (route) => {
    if (route.request().url().includes('industry-summary')) {
      await route.fulfill({
        status: 200,
        json: {
          industries: [{ industry: 'IT Services', sector: 'IT', alertCount: 2, symbols: ['TCS', 'INFY'] }],
        },
      });
      return;
    }
    await route.fulfill({
      status: 200,
      json: [
        {
          id: 1,
          symbol: 'RELIANCE',
          exchange: 'NSE',
          trigger_type: 'volume_breakout',
          message: 'Volume 3.4x vs 20D SMA',
          triggered_at: Date.now(),
          triggered_date: '2026-10-30',
          read: false,
        },
      ],
    });
  });
}

async function mockAnalysis(page: Page, options: { delaySectorsMs?: number } = {}) {
  const delay = options.delaySectorsMs ?? 0;
  const sector = {
    category_type: 'sector',
    slug: 'it',
    name: 'IT',
    market_cap: 12_500_000,
    pe: 24.6,
    advance: 8,
    decline: 2,
    sentiment: 'Bullish',
    earnings_yoy: 11.4,
    return_1d: 0.82,
    return_1w: 1.4,
    return_1m: 3.1,
    return_6m: 9.7,
    last_updated: '2026-10-30',
  };
  const industry = { ...sector, category_type: 'industry', slug: 'it-services', name: 'IT Services' };
  const stock = {
    id: 1,
    symbol: 'TCS',
    company_name: 'Tata Consultancy Services',
    exchange: 'NSE',
    curr_price: 3120,
    per_change: 0.94,
    market_cap: 11_300_000,
    ttm_pe: 26.1,
    net_profit: 46_000,
    net_profit_yoy: 8.2,
    tech_trend: 'Bullish',
  };

  await page.route('**/api/py/markets/sectors/*/stocks', async (route) => {
    await route.fulfill({ status: 200, json: [stock] });
  });
  await page.route('**/api/py/markets/industries/*/stocks', async (route) => {
    await route.fulfill({ status: 200, json: [stock] });
  });
  await page.route('**/api/py/markets/sectors', async (route) => {
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    await route.fulfill({ status: 200, json: [sector] });
  });
  await page.route('**/api/py/markets/industries', async (route) => {
    await route.fulfill({ status: 200, json: [industry] });
  });
}

async function overlapArea(page: Page, anchor: string): Promise<number> {
  const anchorBox = await page.locator(`[data-widget-tour="${anchor}"]`).first().boundingBox();
  const popoverBox = await page.locator('[data-tour-popover]').boundingBox();
  if (!anchorBox || !popoverBox) {
    return Number.MAX_SAFE_INTEGER;
  }
  const overlapX =
    Math.min(anchorBox.x + anchorBox.width, popoverBox.x + popoverBox.width) -
    Math.max(anchorBox.x, popoverBox.x);
  const overlapY =
    Math.min(anchorBox.y + anchorBox.height, popoverBox.y + popoverBox.height) -
    Math.max(anchorBox.y, popoverBox.y);
  const area = Math.max(0, overlapX) * Math.max(0, overlapY);
  if (area > 0) {
  }
  return area;
}

async function expectPopoverClearsAnchor(page: Page, anchor: string, timeout = 4_000) {
  // The popover is placed one frame after the step text changes.
  await expect(page.locator('[data-tour-popover]')).toBeVisible();
  await expect.poll(() => overlapArea(page, anchor), { timeout }).toBeLessThan(1);
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

test('NOTIF tour opens the heatmap, returns to the stream, and never covers its target', async ({
  page,
}) => {
  await mockBackend(page);
  await mockNotifications(page);
  await boot(page, { panels: { 'panel-1': 'NOTIF' }, unseen: ['NOTIF'] });

  const overlay = page.locator(`${PANEL_1} ${OVERLAY}`);
  await expect(overlay).toContainText('STEP 1 OF 7', { timeout: 20_000 });
  await expectPopoverClearsAnchor(page, 'notif-scope-selector');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 2 OF 7');
  await expectPopoverClearsAnchor(page, 'notif-view-mode');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 3 OF 7');
  await expect(page.locator(`${PANEL_1} [role="tab"][aria-selected="true"]`)).toContainText(
    'INDUSTRY HEATMAP',
  );
  await expectPopoverClearsAnchor(page, 'notif-heatmap');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 4 OF 7');
  await expect(page.locator(`${PANEL_1} [role="tab"][aria-selected="true"]`)).toContainText(
    'LIVE ALERTS',
  );

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 5 OF 7');
  await expectPopoverClearsAnchor(page, 'notif-categories');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 6 OF 7');
  await expectPopoverClearsAnchor(page, 'notif-read-filter');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  // The alert card only exists when the feed has rows. This spec mocks no
  // watchlist, so the optional card step must retire instead of stalling.
  await expect(overlay).toHaveCount(0, { timeout: 15_000 });
});

test('SCAN tour highlights the heatmap grid it switches to', async ({ page }) => {
  await mockBackend(page);
  await mockNotifications(page);
  await boot(page, { panels: { 'panel-1': 'SCAN' }, unseen: ['SCAN'] });

  const overlay = page.locator(`${PANEL_1} ${OVERLAY}`);
  await expect(overlay).toContainText('STEP 1 OF 6', { timeout: 20_000 });
  await expectPopoverClearsAnchor(page, 'scan-scope');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 2 OF 6');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 3 OF 6');
  await expect(page.locator(`${PANEL_1} [role="tab"][aria-selected="true"]`)).toContainText(
    'INDUSTRY HEATMAP',
  );
  await expectPopoverClearsAnchor(page, 'scan-heatmap');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 4 OF 6');
  await expect(page.locator(`${PANEL_1} [role="tab"][aria-selected="true"]`)).toContainText(
    'LIVE ALERTS',
  );
  await expectPopoverClearsAnchor(page, 'scan-categories');
});

test('ANALYSIS tour visits Sectors and Heatmap, never covers its target, and restores Summary', async ({
  page,
}) => {
  await mockBackend(page);
  await mockAnalysis(page);
  await boot(page, { panels: { 'panel-1': 'ANALYSIS' }, unseen: ['ANALYSIS'] });

  const overlay = page.locator(`${PANEL_1} ${OVERLAY}`);
  const activeTab = page.locator(`${PANEL_1} [role="tab"][aria-selected="true"]`);
  await expect(overlay).toContainText('STEP 1 OF 8', { timeout: 20_000 });
  await expectPopoverClearsAnchor(page, 'analysis-tabs');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 2 OF 8');
  await expect(activeTab).toContainText('Summary');
  await expectPopoverClearsAnchor(page, 'analysis-kpis');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 3 OF 8');
  await expect(activeTab).toContainText('Sectors');
  await expectPopoverClearsAnchor(page, 'analysis-rail');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 4 OF 8');
  await expectPopoverClearsAnchor(page, 'analysis-stats');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 5 OF 8');
  await expectPopoverClearsAnchor(page, 'analysis-actions');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 6 OF 8');
  await expect(activeTab).toContainText('Heatmap');
  await expectPopoverClearsAnchor(page, 'analysis-heat-controls');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 7 OF 8');
  await expectPopoverClearsAnchor(page, 'analysis-heat-legend');

  await overlay.getByRole('button', { name: 'NEXT' }).click();
  await expect(overlay).toContainText('STEP 8 OF 8');
  await expectPopoverClearsAnchor(page, 'analysis-heatmap');

  await overlay.getByRole('button', { name: 'FINISH' }).click();
  await expect(activeTab).toContainText('Summary');
});

test('a slow widget holds its step and highlights the anchor when it finally renders', async ({
  page,
}) => {
  await mockBackend(page);
  await mockAnalysis(page, { delaySectorsMs: 8000 });
  await boot(page, { panels: { 'panel-1': 'ANALYSIS' }, unseen: ['ANALYSIS'] });
  const overlay = page.locator(`${PANEL_1} ${OVERLAY}`);

  await expect(overlay).toContainText('STEP 1 OF 8', { timeout: 20_000 });
  await expectPopoverClearsAnchor(page, 'analysis-tabs');
  await overlay.getByRole('button', { name: 'NEXT' }).click();

  // Step 2 needs the sector basket. The tour must hold the step, explain the
  // wait, then place the highlight on the KPI band without a manual nudge.
  await expect(overlay).toContainText('STEP 2 OF 8');
  await expect(page.locator('[data-tour-waiting="true"]')).toBeVisible({ timeout: 6_000 });
  await expect(overlay).toContainText('WAITING FOR ANALYSIS');
  await expectPopoverClearsAnchor(page, 'analysis-kpis', 15_000);
  await expect(overlay).toContainText('STEP 2 OF 8');
  await expect(page.locator('[data-tour-waiting="true"]')).toHaveCount(0);
});
