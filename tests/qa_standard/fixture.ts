import { readFileSync } from 'fs';
import { join } from 'path';
import type { Page } from '@playwright/test';

const TEMPLATE = join(__dirname, '..', '..', 'apps', 'core', 'templates', 'app.html');
const HARNESS = join(__dirname, 'harness.css');

/**
 * Build the dashboard HTML exactly as the FastAPI /app route serves it
 * (placeholder substitution), but swap the runtime Tailwind CDN for the local
 * harness stylesheet so the responsive contract is testable offline.
 */
export function buildDashboardHtml(): string {
  let html = readFileSync(TEMPLATE, 'utf-8');

  const profile = JSON.stringify({ work: 'Founder', goals: ['Create content'] });
  html = html
    .replace(/__NAME__/g, 'Geremy Polanco')
    .replace(/__FIRST__/g, 'Geremy')
    .replace(/__INITIAL__/g, 'G')
    .replace(/__EMAIL__/g, 'geremy@example.com')
    .replace(/__PLAN__/g, 'Business')
    .replace(/__ONBOARDED__/g, 'true') // skip onboarding overlay in tests
    .replace(/__PROFILE_JSON__/g, profile)
    .replace(/__IS_OWNER__/g, 'true');

  // Remove the Tailwind CDN (firewalled in CI) and the @apply block it compiles.
  html = html.replace(/<script src="https:\/\/cdn\.tailwindcss\.com"><\/script>/g, '');
  html = html.replace(/<style type="text\/tailwindcss">[\s\S]*?<\/style>/g, '');
  // Drop the Google Fonts link (network) — harness provides a mono fallback.
  html = html.replace(/<link[^>]*fonts\.g[^>]*>/g, '');

  // Inject the local harness stylesheet.
  const harness = readFileSync(HARNESS, 'utf-8');
  html = html.replace('</head>', `<style>${harness}</style></head>`);

  return html;
}

/**
 * Load the dashboard into the page and install a stubbed /api/v1/chat that
 * returns a text reply + a tiny PNG deliverable after `delayMs`, so the mission
 * card's RUNNING → Done transition is observable. NOTE: the function passed to
 * page.evaluate runs in the browser as plain JS — no TypeScript syntax inside.
 */
export async function loadDashboard(page: Page, delayMs = 400): Promise<void> {
  await page.setContent(buildDashboardHtml(), { waitUntil: 'load' });
  await page.evaluate((delay) => {
    const PNG =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC';
    window.fetch = function (url) {
      const isChat = String(url).indexOf('/api/v1/chat') !== -1;
      return new Promise((resolve) => {
        setTimeout(
          () =>
            resolve({
              json: async () =>
                isChat ? { reply: '**Done.** Deliverable attached.', media_base64: PNG } : {},
            }),
          isChat ? delay : 0
        );
      });
    };
  }, delayMs);
}
