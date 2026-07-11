# ARIA Clipper — Chrome Extension (Manifest V3)

Clip the current page's URL and your highlighted text straight into your ARIA
workspace.

## Files
- `manifest.json` — MV3 manifest (`scripting`, `activeTab`, `storage` perms;
  host permission for `https://aria-ai.fly.dev/*`).
- `popup.html` — minimalist dark popup.
- `popup.js` — reads the active tab's URL + selection via `chrome.scripting`,
  then `POST`s to `/api/v1/clipper/capture` with `credentials: 'include'` so the
  ARIA session cookie authenticates the request.

## Load it (developer mode)
1. Add a 128×128 `icon128.png` to this folder (any brand icon).
2. Open `chrome://extensions`, enable **Developer mode**.
3. **Load unpacked** → select `extensions/chrome-clipper`.
4. Sign in at <https://aria-ai.fly.dev/login> in the same browser.
5. Highlight text on any page, click the ARIA icon → **Clip to ARIA**.

## Backend
`POST /api/v1/clipper/capture` (in `apps/core/routes/clipper.py`) is
authenticated with the existing signed session (cookie **or**
`Authorization: Bearer <token>`), rate-limited, and stores each clip under
`aria:clips:{email}`.
