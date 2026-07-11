# ARIA — QA Standard (UI / integration tests)

Premium-standard Playwright suite that guards the responsive ARIA dashboard
(`apps/core/templates/app.html`).

## What it validates

1. **Responsiveness (iPhone 14)** — the `Sidebar` and `Live Agent Logs` panels
   start hidden off-canvas, their buttons open the drawers with the correct
   Tailwind transform classes, and there is **no involuntary horizontal scroll**.
2. **Real mission flow** — dispatching a mission intercepts `/api/v1/chat`,
   renders the card in the **RUNNING** state with its animated progress bar, then
   transitions to **Done** with the media deliverable.
3. **Live logs console** — monospace typography is active and the console
   **auto-scrolls** to the bottom as new lines arrive.

## Run

```bash
cd tests/qa_standard
npm install
npm run test:ui          # headless
npm run test:ui:headed   # watch it drive the browser
npm run report           # open the HTML report after a run
```

The suite is **self-contained**: it loads the real `app.html`, substitutes the
same placeholders the FastAPI `/app` route does, and swaps the runtime Tailwind
CDN for a small local `harness.css` (models the mobile breakpoint) so it runs
green offline / in CI without network. `/api/v1/chat` is stubbed in-page, so no
backend or API key is required.

### Browsers

If Playwright's own browser download is blocked, the config auto-detects a
pre-installed Chromium under `PLAYWRIGHT_BROWSERS_PATH` (default
`/opt/pw-browsers`). Otherwise `npx playwright install chromium` provisions one.

## Projects

- `mobile-iphone14` — iPhone 14 metrics (Chromium engine); runs everything incl.
  the responsiveness checks.
- `desktop` — 1440×900; runs the viewport-agnostic mission + logs checks (the
  mobile-only responsiveness checks are skipped here by design).
