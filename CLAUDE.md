# CLAUDE.md — ARIA AI

## What this repo is

ARIA AI — Autonomous Business System. Python/FastAPI backend (`apps/core/main.py`, ~89 endpoints + WebSocket chat), ~20 domain modules under `apps/`, Supabase for persistence (`database/*.sql`), Stripe billing, OAuth connector hub. Primary LLM engine: HuggingFace, with Groq/Anthropic/OpenAI fallbacks via `apps/core/tools/ai_client.py`.

## Working here

- **Entry points:** API → `python -m uvicorn apps.core.main:app --host 0.0.0.0 --port ${PORT:-8080}`; worker → `python -m apps.core.scale.worker`. Local stack: `docker compose up` (root wrapper → `infra/docker-compose.yml`).
- **Config:** everything comes from env vars defined in `apps/core/config.py` (see `.env.example` — all 232 documented). The app boots with no env vars in degraded mode; don't add required fields without a safe default.
- **Golden rule: never fabricate.** Unavailable backend → explicit error, never invented data. LLM generation failure → `RuntimeError`, never `# TODO` placeholder files. The ERP connector (`apps/core/integrations/business_os_connector.py`) is intentionally disabled (`ERP_ENABLED=false`) until a real backend exists.
- **Tests** live in `tests/` with a fully-mocked `conftest.py` (no real network). Run affected tests; at minimum `py_compile` touched files.
- **Secrets** via env only. Never commit `.env`. Never invent credential values.

## Conventions

- Atomic commits, English messages, feature branches — never push straight to `main`.
- Before starting: `git fetch origin main`, rebase your branch. Keep branches short-lived; re-merge and re-verify if `main` moves under you.
- Don't force-push over another agent's work.
