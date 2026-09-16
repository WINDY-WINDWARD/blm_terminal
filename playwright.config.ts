import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Browser CDN is unreachable from this environment; reuse the locally
        // cached Chromium build instead of `npx playwright install`.
        launchOptions: {
          executablePath:
            'C:\\Users\\karth\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe',
        },
      },
    },
  ],
  webServer: {
    // NOTE: the UI only loads off a full production build (`npm run build:next`);
    // the dev server does not serve a working app. Build once, then run e2e
    // against `npm run start` (Next production + custom server.js).
    command: 'npm run start',
    url: 'http://127.0.0.1:3000',
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      PORT: '3000',
      PYTHON_BACKEND_URL: 'http://127.0.0.1:4455',
    },
  },
});
