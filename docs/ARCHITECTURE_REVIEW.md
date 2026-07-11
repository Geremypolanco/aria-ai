# ARIA — Architecture Review & Improvement Roadmap

A professional review of the repository against the engineering checklist
(architecture, product, economics, automation, code quality, scalability,
observability, security, AI, memory, learning, business, UX, evolution) and the
guiding principle: **build reusable capabilities, not per-case fixes.**

The system is **live and processing real payments**, so adjustments are made
**incrementally and safely** — never a big-bang rewrite that could break revenue.

---

## Top findings (ranked by impact × risk)

### 1. `income_loop.py` is a 25k-line monolith (116 strategies in one file)
- **Violates:** single responsibility, testability, "readable in 6 months", scalability of development.
- **Why it matters:** every strategy change risks the whole file; coverage is ~15% because strategies are hard to test in isolation; merge conflicts and cognitive load are high.
- **Roadmap (incremental, low-risk):** introduce `apps/core/income/strategies/` with one module per strategy and a registry that the loop imports. Move strategies a few at a time; the dispatcher already isolates them by name, so this can be done without behavior change. Add a test per extracted strategy.
- **Status:** _planned_ — high effort, do in small batches.

### 2. Massive duplication of cross-cutting concerns
The same patterns are copy-pasted across ~100+ sites:
- **Publishing** (API → browser fallback): **105 sites.** ✅ **DONE** — extracted into `apps/distribution/publishers/broadcaster.py` (`broadcast(text, channels=[...])`), 8 isolated tests, first strategy migrated. Remaining sites migrate incrementally behind the same call.
- **SMTP email send:** repeated `smtplib` blocks in several strategies → extract `apps/distribution/email/sender.py` (`send_email(to, subject, body)`), credential-aware, testable.
- **GitHub archiving** (`gh._get`/`gh._put` + base64): repeated → extract `archive_markdown(repo, path, content)`.
- **Telegram alerts / Redis CRM access:** repeated → thin reusable helpers.
- **Principle:** each of these is a *capability*, not a per-strategy detail.
- **Status:** broadcaster done; email/archive/crm helpers _planned_.

### 3. Test coverage ~15% (CI gate is exactly 15%)
- **Risk:** strategies are largely unverified; regressions ship silently.
- **Roadmap:** every extraction (above) ships with isolated tests (as broadcaster did). Target: raise the floor as modules are pulled out, not via one big test push.

### 4. Observability: good infra, inconsistent use
- **Good:** OpenTelemetry, Prometheus metrics, structured logging, Sentry wiring exist.
- **Gap:** strategies use bare `logger.warning` + silent `except Exception: pass`; no per-strategy success/latency metric, so silent degradation is invisible.
- **Roadmap:** standardize a `record_strategy_result(name, success, latency, revenue_potential)` metric emitted by the dispatcher; alert on success-rate drops.

### 5. Security: solid baseline, two cleanups before public launch
- **Good:** secrets read from env (managed in Fly.io), never in code; payment links created server-side.
- **Cleanups:** (a) remove/gate the temporary `/paypal/diag` and `/stripe/diag` endpoints (they expose no secrets but no longer need to be public); (b) **no rate limiting** on public endpoints (`/subscribe`, `/api/webhooks/lead`, `/access/{key}`) — add it (the cache already has `check_rate_limit`); (c) validate/limit webhook payload sizes.
- **Status:** _planned_ — quick wins.

### 6. Scalability: the income loop assumes a single instance
- **Risk:** if Fly scales to >1 machine, each runs the loop → duplicate posts/outreach.
- **Roadmap:** wrap each cycle in the existing Redis `acquire_lock`/`release_lock` so only one instance executes per interval. Low effort, prevents real-world duplication.

### 7. Fulfillment & anti-fraud (business correctness)
- **Done:** digital products are real files delivered automatically post-payment (`/access/{key}`); high-ticket is a deliverable service.
- **Watch:** the Shopify store is password-gated and has no auto-delivery — keep the canonical purchase path on the Stripe links (which deliver) until Shopify fulfillment is wired.

---

## What changed in this review
- Extracted the **reusable publishing capability** (`broadcaster.py`) + tests; migrated the first strategy. This is the template for collapsing the other duplicated cross-cutting concerns.

## Operating policy going forward (per the engineering checklist)
Before each new module/feature, answer: does it raise revenue / conversion / LTV
or cut CAC / churn? can it reuse an existing component? is it a reusable capability
or a per-case patch? how is it tested, observed, secured, and how will it evolve?
If the answers aren't clear, it isn't a priority.

---

## Repo-wide audit execution log (every file reviewed)

A 6-agent parallel audit covered all 528 files in `apps/`. Findings executed:

### ✅ Done & deployed (validated: prod /health=ok, full test suite green)
- **Dead code removed — 57 files / >10,000 lines**, each verified to have zero
  importers across `apps/` and `tests/`: the orphan "ARIA ELITE" island, 5 unused
  memory clients, 15 caller-less `intelligence/` modules (several were simulated
  stubs — dishonest in a live system), 4 orphan orchestration engines, 4 dead
  agents, 3 dead tracing impls, 10 dead `tools/` modules, dead integrations,
  `commands/`, `planning/strategic`, and the unused `apps/api/main.py`.
- **Security:**
  - 🔴 Closed an unauthenticated **RCE** (`POST /execute_shell`) — it lived only in
    the deleted `apps/api/main.py`.
  - 🔴 **Stripe webhook signature** now enforced (was `except: pass` → forgeable
    payment events).
  - 🔴 `infra_tools` arbitrary `shell=True` → binary allowlist + no shell.
  - 🐛 Fixed a real runtime crash in the live sandbox (`timeout=` on
    `create_subprocess_exec`).
  - 🔒 `.gitignore` hardened for the encrypted secret store.
  - 🚦 Reusable **rate-limit dependency** (`apps/api/ratelimit.py`) on `/lead` and the
    diag endpoints (email-bomb / token-minting vectors).

### ⏳ Remaining roadmap (bigger refactors — incremental, each its own validated PR)
1. **`income_loop.py` (25k LOC) god-file** → dict-dispatch first (mechanical), then a
   `Strategy` protocol + `STRATEGY_REGISTRY` wired to the CapabilityRegistry, then move
   `_exec_*` into `income_loop/strategies/*.py` by domain.
2. **`autonomous_scheduler.py` (5.6k)**, **`routes/api.py` (2k)**, **`aria_mind.py`
   (1.7k)** god-files → split by domain; replace the `aria_mind._execute_tool` 860-line
   `if` chain with a dispatch table.
3. **Migrate the 107 direct publish sites to `broadcast()`** (capability already built).
4. **Connector interface:** a `BaseOAuthConnection` + wire live connector instances into
   `capabilities/catalog.py` so the registry is executable, not just descriptive; delete
   the unreachable `connections/` OAuth layer.
5. **Distributed lock** around the schedulers/income-loop (defense-in-depth vs scaling).
6. **Replace the 352 silent `except: pass`** with logged handlers (observability).
7. Connector hygiene: timeouts on shopify/square, guard `delete_all_products`, fix Etsy
   PKCE, consolidate duplicated webhook handlers.
