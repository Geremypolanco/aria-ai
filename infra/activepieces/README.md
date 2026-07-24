# Activepieces → ARIA integration

Gives ARIA access to Activepieces' 200+ pieces (Google, Slack, HubSpot, Stripe,
and more) as MCP tools, the same way `apps/core/tools/zapier_mcp.py` already
gives it access to Zapier's — one credential, no per-app OAuth build-out.

Activepieces Community Edition is MIT-licensed and runs as its own service.
This directory is **not** ARIA's code merged with theirs — it's a deploy of
the upstream project, wired to ARIA purely over MCP (network calls), the same
arrangement ARIA already has with Zapier.

## 1. Deploy Activepieces

```bash
cd infra/activepieces
cp .env.example .env
# Fill in AP_ENCRYPTION_KEY, AP_JWT_SECRET, AP_POSTGRES_PASSWORD (see comments in .env.example)
docker compose up -d
```

This starts Activepieces' own app/worker/Postgres/Redis — completely separate
from ARIA's own Postgres/Redis. Run it on a VPS, its own Fly.io app, or any
Docker host; it does not need to live next to ARIA's containers.

Open `http://<your-host>:8080`, create the admin account, and connect
whichever pieces you want ARIA to be able to use (Slack, HubSpot, Stripe,
Google Sheets, etc.) — same as connecting apps in Zapier today.

## 2. Get the MCP endpoint

In the Activepieces dashboard: **Platform Settings → MCP Servers**. Copy the
MCP endpoint URL + token for this instance (see
[Activepieces' MCP docs](https://www.activepieces.com/docs/mcp/overview) if
the exact path in your installed version differs).

## 3. Point ARIA at it

```bash
fly secrets set ACTIVEPIECES_MCP_URL="<the URL you copied>" -a aria-ai
```

Once set, the connector shows as "ready" in ARIA's Connectors panel
(`apps/core/connectors/oauth_hub.py`), and
`GET /api/v1/activepieces/selftest` reports the reachable tool count.

## Notes

- Activepieces surfaces one MCP tool per connected piece/action — there's no
  fixed name mapping to hardcode on ARIA's side (unlike Zapier's generic
  `execute_zapier_write_action`). Use
  `ActivepiecesMCPClient.list_tools()` / `.find_tool(...)` to discover what's
  actually available on your instance before wiring a specific mission to it.
- Pin the image tag (`0.86.3` as of this writing) rather than tracking
  `:latest` — the Activepieces team has flagged at least one past release
  (0.78.1) with a CPU-usage regression.
