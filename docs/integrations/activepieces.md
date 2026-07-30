# Activepieces integration docs for ARIA

This document explains how to run a self-hosted Activepieces instance and
connect it to ARIA via the MCP endpoint.

Quickstart (local)

1. Start Activepieces (see infra/activepieces/docker-compose.yml)

   ```bash
   cd infra/activepieces
   cp .env.example .env
   # edit .env -> AP_POSTGRES_PASSWORD, AP_JWT_SECRET, AP_ENCRYPTION_KEY
   docker compose up -d
   ```

2. Open the Activepieces UI at http://localhost:8080 and create the admin
   account. In Platform Settings → MCP Servers you will find the MCP URL and
   token for this instance.

3. Point ARIA at the MCP endpoint by adding the following environment
   variables (copy into .env or set secrets in your host):

   - ACTIVEPIECES_MCP_URL: https://your-activepieces-host/mcp
   - ACTIVEPIECES_API_KEY: the MCP token from the Activepieces admin UI

4. Restart ARIA (or run in dev):

   ```bash
   # if using infra/docker-compose (aria-api service) the env file should include the keys
   docker-compose -f infra/docker-compose.yml up aria-api
   # or locally:
   export ACTIVEPIECES_MCP_URL="http://localhost:8080"
   export ACTIVEPIECES_API_KEY="<token>"
   uvicorn apps.core.main:app --reload
   ```

ARIA end-points

- GET /api/v1/activepieces/selftest  — quick health check
- GET /api/v1/activepieces/flows     — list discovered flows/pieces
- POST /api/v1/activepieces/execute  — execute a flow (body: {"flow_id":"...","input":{}})

Notes

- Activepieces is run as an independent service (it has its own Postgres/Redis
  backing store). We purposely keep it separate so it can be scaled/secured
  independently of ARIA.
- The client implemented in apps/core/integrations is defensive about endpoint
  shapes; if your Activepieces installation exposes different paths, update the
  client candidates in apps/core/integrations/activepieces_client.py.
