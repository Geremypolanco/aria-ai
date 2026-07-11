import { test, expect } from '@playwright/test';
import { loadDashboard } from './fixture';

// ── 1. RESPONSIVENESS (iPhone 14) ────────────────────────────────
// The harness stylesheet models the mobile breakpoint only, so these run on
// the mobile project.
test.describe('Responsiveness · iPhone 14', () => {
  // These validate the mobile breakpoint; the harness models mobile only.
  test.beforeEach(async ({}, info) => {
    test.skip(!info.project.name.includes('mobile'), 'mobile-only checks');
  });

  test('Sidebar and Live Logs are hidden off-canvas and open as drawers', async ({ page }) => {
    await loadDashboard(page);
    const side = page.locator('#side');
    const logs = page.locator('#logs');
    const vw = page.viewportSize()!.width;

    // Both panels start off-canvas (the correct Tailwind responsive classes).
    await expect(side).toHaveClass(/-translate-x-full/);
    await expect(logs).toHaveClass(/translate-x-full/);
    expect((await side.boundingBox())!.x).toBeLessThan(0); // off the left edge
    expect((await logs.boundingBox())!.x).toBeGreaterThanOrEqual(vw - 1); // off the right edge

    // The hamburger opens the sidebar drawer (poll past the 0.3s slide-in).
    await page.click('button[aria-label="Menu"]');
    await expect(side).not.toHaveClass(/-translate-x-full/);
    await expect.poll(async () => (await side.boundingBox())!.x).toBeGreaterThanOrEqual(0);

    // Close it so the topbar is interactive again (backdrop centre sits under
    // the open sidebar, so drive the documented close path directly).
    await page.evaluate(() => window.toggleSide(false));
    await expect(side).toHaveClass(/-translate-x-full/);

    // The floating pill opens the Live Agent Logs drawer.
    await page.click('button[aria-label="Live logs"]');
    await expect(logs).not.toHaveClass(/translate-x-full/);
    await expect.poll(async () => (await logs.boundingBox())!.x).toBeLessThan(vw);
  });

  test('No involuntary horizontal scroll', async ({ page }) => {
    await loadDashboard(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

// ── 2. REAL MISSION FLOW ─────────────────────────────────────────
test.describe('Mission flow', () => {
  test('dispatch renders a RUNNING card with progress bar, then Done + deliverable', async ({
    page,
  }) => {
    await loadDashboard(page, 1500); // hold RUNNING long enough to observe
    await page.fill('#igniter', 'Research the top AI newsletters and draft a post');
    await page.click('#ignite');

    const card = page.locator('#missions article').first();
    await expect(card).toBeVisible();

    // RUNNING state + animated render progress bar.
    await expect(card).toContainText('Running');
    await expect(card.locator('.bar-anim')).toHaveCount(1);

    // Transitions to Done with the media deliverable rendered.
    await expect(card).toContainText('Done', { timeout: 8000 });
    await expect(card.locator('img')).toHaveCount(1);
    await expect(card.locator('.bar-anim')).toHaveCount(0);
  });
});

// ── 3. LIVE LOGS CONSOLE ─────────────────────────────────────────
test.describe('Live agent logs', () => {
  test('monospace typography is active and the console auto-scrolls to the bottom', async ({
    page,
  }) => {
    await loadDashboard(page);

    // Monospace font family active.
    const fontFamily = await page
      .locator('#logStream')
      .evaluate((el) => getComputedStyle(el).fontFamily);
    expect(fontFamily.toLowerCase()).toContain('mono');

    // Inject many log lines and verify the container scrolled to the bottom.
    await page.evaluate(() => {
      for (let i = 0; i < 60; i++) window.log('qa injected log line ' + i);
    });
    const atBottom = await page
      .locator('#logStream')
      .evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop <= 2);
    expect(atBottom).toBeTruthy();
  });
});
