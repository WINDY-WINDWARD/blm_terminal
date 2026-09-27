import { expect, test, type Page } from '@playwright/test';

const MODAL = 'div.fixed.inset-0.z-50:has-text("FIRST-TIME SETUP")';

async function mockBackend(
  page: Page,
  opts: { needsSetup: boolean; authed: boolean; eulaAccepted?: boolean },
) {
  let authed = opts.authed;
  // Stateful: flips to true when the app POSTs /eula/accept so a post-wizard
  // reload sees the agreement persisted (mirrors the DB-backed endpoint).
  let eulaAccepted = opts.eulaAccepted ?? true;
  await page.route('**/api/py/eula-status', async (route) => {
    await route.fulfill({
      status: 200,
      json: { accepted: eulaAccepted, version: 'eula-v1', accepted_at: eulaAccepted ? 123 : null },
    });
  });
  await page.route('**/api/py/eula/accept', async (route) => {
    eulaAccepted = true;
    await route.fulfill({ status: 200, json: { accepted: true, version: 'eula-v1', accepted_at: 123 } });
  });
  await page.route('**/api/py/auth/setup-status', async (route) => {
    await route.fulfill({ status: 200, json: { needs_setup: opts.needsSetup && !authed } });
  });
  await page.route('**/api/py/auth/me', async (route) => {
    if (authed) {
      await route.fulfill({ status: 200, json: { id: 1, username: 'admin', is_admin: true } });
    } else {
      await route.fulfill({ status: 401, json: { detail: 'Not authenticated' } });
    }
  });
  await page.route('**/api/py/auth/setup', async (route) => {
    authed = true;
    await route.fulfill({ status: 200, json: { access_token: 'e2e-token', token_type: 'bearer' } });
  });
  await page.route('**/api/py/system-config', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 401, json: { detail: 'Not authenticated' } });
    } else {
      await route.continue();
    }
  });
  await page.route('**/api/py/system_config/consent', async (route) => {
    await route.fulfill({ status: 200, json: { ok: true } });
  });
  await page.route('**/api/py/ai/status', async (route) => {
    await route.fulfill({ status: 200, json: { provider: 'zen', is_configured: false } });
  });
}

async function clickContinue(page: Page) {
  await page.locator(`${MODAL} button:has-text("Continue")`).click();
}

/** Advance the driver.js tour to the end regardless of how many steps rendered.
 *  A click that lands inside driver's 400ms highlight animation is swallowed
 *  (no destroy), so confirm persistence after the Finish click and retry. */
async function finishTour(page: Page) {
  const tutorialStatus = () => page.evaluate(() => localStorage.getItem('terminal.tutorial.v1'));
  await expect(page.locator('.driver-popover')).toBeVisible({ timeout: 15_000 });
  for (let i = 0; i < 30; i++) {
    const finish = page.locator('.driver-popover button:has-text("Finish tour")');
    if ((await finish.count()) > 0) {
      await finish.first().click();
      try {
        await expect.poll(tutorialStatus, { timeout: 4000 }).toBe('"done"');
        break;
      } catch {
        continue; // click landed mid-transition; the tour is still on its last step
      }
    }
    await page.locator('.driver-popover button:has-text("Next")').first().click();
  }
  await expect.poll(tutorialStatus, { timeout: 10_000 }).toBe('"done"');
  await expect(page.locator('.driver-popover')).toBeHidden({ timeout: 10_000 });
}

test('fresh boot: wizard → create admin → consent → skip AI → tour → done persists', async ({
  page,
}) => {
  await mockBackend(page, { needsSetup: true, authed: false, eulaAccepted: false });
  await page.goto('/');

  // Step 1: EULA (must agree before anything else)
  await expect(page.locator(MODAL)).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(MODAL)).toContainText('End-User License Agreement');
  await expect(
    page.locator(`${MODAL} button:has-text("Continue")`),
  ).toBeDisabled();
  await page.locator(`${MODAL} input[type="checkbox"]`).check();
  await expect(
    page.locator(`${MODAL} button:has-text("Continue")`),
  ).toBeEnabled();
  await clickContinue(page);

  // Step 2: welcome
  await expect(page.locator(MODAL)).toContainText('Welcome to BLM Terminal.');
  await clickContinue(page);

  // Step 3: backend (mocked 401 = alive)
  await expect(page.locator(MODAL)).toContainText('Checking engine status');
  await expect(page.locator(MODAL)).toContainText('Engine active', { timeout: 10_000 });
  await clickContinue(page);

  // Step 4: create admin
  await expect(page.locator(MODAL)).toContainText('Create your administrator account');
  await page.locator(`${MODAL} input[type="text"]`).fill('admin');
  const passwords = page.locator(`${MODAL} input[type="password"]`);
  await passwords.nth(0).fill('StrongPass123!');
  await passwords.nth(1).fill('StrongPass123!');
  await page.locator(`${MODAL} button:has-text("CREATE ADMIN")`).click();
  await expect(page.locator(MODAL)).toContainText('Signed in as admin', { timeout: 10_000 });
  await clickContinue(page);

  // Step 5: consent (agree immediately transitions to AI)
  await expect(page.locator(MODAL)).toContainText('Data extraction & privacy');
  await page.locator(`${MODAL} button:has-text("I Agree, Enable")`).click();

  // Step 6: AI — skip
  await expect(page.locator(MODAL)).toContainText('AI assistant (optional)');
  await expect(page.locator(MODAL)).toContainText('generous free tier');
  await page.locator(`${MODAL} button:has-text("Set up later")`).click();

  // Step 7: done → finish launches the tour
  await expect(page.locator(MODAL)).toContainText('Setup complete');
  await page.locator(`${MODAL} button:has-text("Finish & start tour")`).click();
  await expect(page.locator(MODAL)).toBeHidden({ timeout: 5000 });

  await finishTour(page);

  // Persistence: reload → wizard stays gone
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('terminal.onboarding.v1')), {
      timeout: 10_000,
    })
    .toBe('true');
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem('terminal.tutorial.v1')), {
      timeout: 10_000,
    })
    .toBe('"done"');
  await page.reload();
  await expect(page.locator('text=FIRST-TIME SETUP')).toBeHidden({ timeout: 20_000 });
});

test('TOUR command replays the finished tour', async ({ page }) => {
  await mockBackend(page, { needsSetup: false, authed: true });
  await page.addInitScript(() => {
    localStorage.setItem('terminal.onboarding.v1', 'true');
    localStorage.setItem('terminal.tutorial.v1', '"done"');
  });
  await page.goto('/');
  await expect(page.locator('#terminal-command-input')).toBeVisible({ timeout: 20_000 });

  await page.locator('#terminal-command-input').fill('TOUR');
  await page.locator('#terminal-command-input').press('Enter');

  await finishTour(page);
});

test('tour completes with a 2-panel layout (missing widgets skip)', async ({ page }) => {
  await mockBackend(page, { needsSetup: false, authed: true });
  await page.addInitScript(() => {
    localStorage.setItem('terminal.onboarding.v1', 'true');
    localStorage.setItem('terminal.tutorial.v1', '"done"');
    localStorage.setItem('terminal.panelCount', '2');
  });
  await page.goto('/');
  await expect(page.locator('#terminal-command-input')).toBeVisible({ timeout: 20_000 });

  await page.locator('#terminal-command-input').fill('TOUR');
  await page.locator('#terminal-command-input').press('Enter');

  await finishTour(page);
});
