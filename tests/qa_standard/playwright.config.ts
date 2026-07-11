import { defineConfig, devices } from '@playwright/test';
import { existsSync, readdirSync } from 'fs';

// Use the pre-installed Chromium if present (the sandbox ships it and pins a
// browser build that may differ from @playwright/test's own download).
function chromiumPath(): string | undefined {
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
  if (!existsSync(root)) return undefined;
  const dir = readdirSync(root).find((d) => d.startsWith('chromium-'));
  if (!dir) return undefined;
  const p = `${root}/${dir}/chrome-linux/chrome`;
  return existsSync(p) ? p : undefined;
}

const executablePath = chromiumPath();

export default defineConfig({
  testDir: '.',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  reporter: [['list']],
  use: {
    launchOptions: {
      // --no-sandbox is required to run Chromium as root (CI containers).
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
      ...(executablePath ? { executablePath } : {}),
    },
  },
  projects: [
    {
      name: 'mobile-iphone14',
      // iPhone metrics (viewport, DPR, touch, UA) but force the Chromium engine
      // (the device descriptor defaults to WebKit, which isn't provisioned here).
      use: { ...devices['iPhone 14'], browserName: 'chromium', defaultBrowserType: 'chromium' },
    },
    {
      name: 'desktop',
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } },
    },
  ],
});
