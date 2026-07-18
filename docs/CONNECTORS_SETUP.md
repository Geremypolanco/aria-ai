# ARIA Connectors — Setup Guide (one-click OAuth like Claude)

ARIA's dashboard has a real **OAuth2 connect** flow: clicking **Connect** opens the
provider's sign-in/consent screen, ARIA receives a token, and the connector turns
**Connected ✓**. This is the same model Claude uses.

**Why each connector needs setup:** every provider requires *its own developer
app* (a Client ID + Secret). ARIA can't create those for you — you register the
app once, paste the two values as Fly secrets, and the connector goes live. A few
providers also require the platform to **review/approve** your app before real
users can post (marked below). Until credentials exist, the button honestly shows
**"Set up"** instead of a fake "Connected".

## The one thing every provider needs

For each connector you enable, set the **redirect / callback URL** in the
provider's app to exactly:

```
https://aria-ai.fly.dev/connectors/<id>/callback
```

…where `<id>` is the connector id (`google`, `linkedin`, `slack`, …). Then provide
the matching Client ID + Secret. Two ways — pick one:

**A) GitHub repo secrets (recommended, plug-and-play).** Add each value under
*Repo → Settings → Secrets and variables → Actions* using the exact names in the
table below (e.g. `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). The deploy workflow
(`.github/workflows/deploy.yml`) already propagates every connector secret to Fly
on each deploy — you never touch code. Trigger a deploy (or push to `main`) and the
connector flips to **Connect**.

**B) Directly on Fly.**

```bash
fly secrets set <PROVIDER>_CLIENT_ID="..." <PROVIDER>_CLIENT_SECRET="..." -a aria-ai
```

Either way, the moment the values exist the connector goes live and users can just
sign in and grant permission. Empty/unset secrets keep it honestly at **"Set up"**.

---

## Per-provider steps

| Connector | Where to register | Secrets to set | Callback URL | Notes |
|---|---|---|---|---|
| **Google** (Gmail/Drive/Calendar) | console.cloud.google.com → APIs & Services → Credentials → OAuth client (Web) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `/connectors/google/callback` | Sensitive scopes need Google **app verification** before other users can grant them. Same app also powers login. |
| **YouTube** | Same Google Cloud app; enable **YouTube Data API v3** | (reuses `GOOGLE_CLIENT_ID/SECRET`) | `/connectors/youtube/callback` | Upload scope needs Google verification. |
| **LinkedIn** | linkedin.com/developers → Create app → Auth | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | `/connectors/linkedin/callback` | Request the "Share on LinkedIn" + "Sign In with OpenID" products. |
| **Instagram** | developers.facebook.com → app → Instagram Graph API | `META_APP_ID`, `META_APP_SECRET` | `/connectors/instagram/callback` | Needs **App Review** for `instagram_content_publish`. Business/Creator IG account linked to a Page. |
| **Facebook** | developers.facebook.com → app → Facebook Login | `META_APP_ID`, `META_APP_SECRET` | `/connectors/facebook/callback` | Needs App Review for `pages_manage_posts`. |
| **Slack** | api.slack.com/apps → Create App → OAuth & Permissions | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` | `/connectors/slack/callback` | Add bot scopes `chat:write`, `channels:read`. |
| **Notion** | notion.so/my-integrations → New **public** integration | `NOTION_OAUTH_CLIENT_ID`, `NOTION_OAUTH_CLIENT_SECRET` | `/connectors/notion/callback` | Must be a *public* OAuth integration (not internal). |
| **X (Twitter)** | developer.twitter.com → Project & App → User auth settings (OAuth 2.0) | `TWITTER_OAUTH_CLIENT_ID`, `TWITTER_OAUTH_CLIENT_SECRET` | `/connectors/x/callback` | Uses PKCE. Enable `tweet.write`, `offline.access`. |
| **TikTok** | developers.tiktok.com → app → Content Posting API | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | `/connectors/tiktok/callback` | Needs TikTok app approval for `video.publish`. |
| **Stripe** | dashboard.stripe.com → Connect settings (get the **Connect client id** `ca_...`) | `STRIPE_CONNECT_CLIENT_ID`, `STRIPE_SECRET_KEY` | `/connectors/stripe/callback` | Uses Stripe **Connect** OAuth. |
| **Shopify** | Shopify Partners → app (per-store OAuth) | `SHOPIFY_URL`, `SHOPIFY_ADMIN_TOKEN` | — | OAuth is per-store; connect from your store admin or provide the Admin API token. |
| **Zapier** | zapier.com → your Zap webhook | `ZAPIER_WEBHOOK_URL` (or `ZAPIER_MCP_URL`) | — | Zapier integrates via webhook/API key, not a redirect OAuth. |

---

## How it works under the hood (for reference)

- `GET /connectors/<id>/connect` → signs a CSRF state (cookie-bound), builds the
  provider authorize URL (+ PKCE where required), redirects to the provider.
- `GET /connectors/<id>/callback` → verifies state, exchanges the code for a
  token, stores it **per user** in the cache (never exposed to the browser),
  returns to `/app?conn=<id>&s=connected`.
- `GET /api/v1/connectors/status` → tells the dashboard which connectors are
  `connected` / `ready` / `setup` so the buttons reflect reality.

Code: `apps/core/connectors/oauth_hub.py` + the `/connectors/*` routes in
`apps/core/main.py`.

> **Honesty:** ARIA never shows a connector as "Connected" without a real stored
> token. Providers that require platform approval are labeled so you know an
> external review — not code — is the remaining gate.
