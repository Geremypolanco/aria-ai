# AGENTS.md — ARIA AI

Guidance for AI coding agents working in this repository. ARIA AI is an
autonomous business-operations backend: a FastAPI service (`apps/core/`)
with ~20 domain modules (`apps/`), chat over HTTP + WebSocket, persistent
memory on Supabase, Stripe billing, and OAuth connectors.

## Layout

- `apps/core/main.py` — FastAPI app entrypoint. Run: `python -m uvicorn apps.core.main:app --host 0.0.0.0 --port 8080` (respects `PORT`).
- `apps/core/scale/worker.py` — background mission worker. Run: `python -m apps.core.scale.worker`.
- `apps/core/config.py` — all settings via pydantic BaseSettings (env vars). Every field has a safe default; the app boots with zero env vars in degraded mode.
- `apps/<domain>/` — domain modules (acquisition, content, shopify, economics, …). `apps/dashboard/` does not exist — don't reference it.
- `database/` + `supabase_schema.sql` — Supabase schemas to apply manually.
- `infra/docker-compose.yml` — local dev stack (api + worker + redis). From repo root, `docker compose up` works via the root `docker-compose.yml` wrapper.
- `Dockerfile` (root) — production image (python:3.12-slim, Playwright, non-root `aria` user). Multiarch: builds natively on ARM64. Deploy target is Oracle Cloud Always Free (Ampere A1): `infra/oracle-cloud/docker-compose.yml` + `infra/oracle-cloud/DEPLOY.md`.
- `.env.example` — documents all 232 settings. Copy to `.env` for local dev; never commit `.env`.
- `tests/` — unit + integration tests. `conftest.py` mocks Redis/Supabase/AI — tests never touch the real network.

## Rules

1. **Never fabricate data.** If a backend is unavailable, return an explicit error / `status: "unavailable"` — never hardcoded findings, synthetic leads, or `# TODO` placeholder files. LLM code-generation failures surface as explicit errors at the tool boundary: builders return `{"success": False, "error": ...}` and agents' exceptions are converted to failure dicts by `BusinessHub.dispatch` — an exception must never escape to the chat caller, which only checks the result dict.
2. **Secrets only via environment.** Never hardcode keys, tokens, or passwords — not even "dev" ones. `.gitignore` covers `.env`.
3. **The ERP/CRM connector is disabled by default** (`ERP_ENABLED=false` in config). Its mutating calls raise `NotImplementedError` until a real backend is implemented. Don't "fix" this by faking success.
4. **Don't break imports.** `apps/core/main.py` mounts routers in try/except so one broken module can't take down boot — keep it that way.
5. **Tests:** run the affected test files before pushing. If the sandbox lacks dependencies, at least `python -m py_compile` every touched file.
6. **Commits:** atomic, messages in English, on a feature branch — never commit straight to `main`.

## Multi-agent coordination

- `git fetch origin main` and rebase your branch before starting; keep branches short-lived.
- If another agent's merge lands first, re-fetch, re-merge, and re-verify — don't force-push over it.
- Hot files with frequent concurrent edits: `apps/core/main.py`, `apps/core/config.py`.
