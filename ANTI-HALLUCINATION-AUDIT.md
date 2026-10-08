# ANTI-HALLUCINATION AUDIT — ARIA AI

**Date:** 2026-10-07 · **Ordered by:** Geremy Polanco (repo owner)
**Standard:** U2 (validate → retry ×3 → dead-letter, never invent) · U3 (LLM on the edges, math in the core) · U5 (provenance or not shown)
**Pattern source:** vendored from `@polanco/llm-contracts` + `@polanco/roi-engine` citations (`~/workspace/polanco-business-os`), reimplemented in Python/pydantic v2 — no TypeScript copied.

## Verdict

**YES — LLM call sites exist.** The central funnel is `AriaAIClient.complete()` / `complete_json()` in `apps/core/tools/ai_client.py` (5 providers: HuggingFace router → Groq → Gemini → OpenAI → Anthropic), consumed by **~50 call sites**. Before this audit, `complete_json` returned `{}` on failure (honest, never invented) but failures were **invisible** (one warning log) and **no output was ever schema-validated**. Prices proposed by the LLM flowed **raw** into real Gumroad/Stripe charges.

## Risk table

| File | What the LLM produces | Risk | Why |
|---|---|---|---|
| `apps/core/tools/ai_client.py` — `complete()` / `complete_json()` | Every structured + free-text output in the system | **HIGH** | Single funnel for ~50 call sites. Pre-audit: prompt-only "JSON mode" (regex bracket extraction), one repair attempt, then silent `{}`. No schema validation anywhere. → **HARDENED**: optional `schema=` gate (`validate_or_retry` ×3 + visible dead-letter queue, exposed in `get_health_summary()`). |
| `apps/core/tools/income_loop.py` — product factory (`complete_json` → `gumroad_create_product`) | `product_data.price_cents` → **real Gumroad product price** | **HIGH** | An hallucinated `price_cents` (e.g. 5¢ or $99,999) was published as the actual charge. → **HARDENED**: `schema=DigitalProductData` (price $1–$999) + deterministic `safe_price_cents` clamp at the Gumroad boundary. |
| `apps/core/tools/income_loop.py` — premium offer (`complete_json` → `gumroad_create_product`) | `offer.price_cents` → **real Gumroad offer price** | **HIGH** | Same money boundary, $500–$5,000 band. → **HARDENED**: `schema=OfferData` + `safe_price_cents` clamp at publish. |
| `apps/core/agents/cfo_agent.py` — `create_ebook` → `publish_to_gumroad` / `create_stripe_product` / `create_payment_link` | `price_usd` → **real Gumroad + Stripe charges** | **HIGH** | LLM-proposed `price_usd` went straight into `int(price*100)` unit amounts. → **HARDENED**: single deterministic choke point in `_execute` (`usd_to_cents`, $7–$27 band per the prompt) + idempotent re-guard at both HTTP boundaries. |
| `apps/core/support/support_agent.py` — `answer()` (Anthropic SDK direct) | Free-text support replies shown to users | **MED** | Direct `AsyncAnthropic` call outside the central client. Mitigated: system prompt already forbids inventing account-specific data; honest offline-FAQ fallback when the key is missing. Out of scope for schema gating (free text). |
| `apps/core/tools/huggingface_suite.py` — `generate_structured()` | Structured JSON via `response_format: json_schema` | **MED** | Provider-side JSON-schema is best-effort (not all routed providers honor strict decoding); values are parsed but never range-validated. Callers should pass an equivalent pydantic schema via the new gate when values matter. |
| `apps/core/agents/pydantic_agents.py` — `AriaTypedAgent._run_with_aria_client` | Typed agent outputs (`output_type.model_validate`) | **MED** | Already pydantic-validates; but on validation failure it falls back to a **synthetic default output** (`_get_default_output`) — deterministic and explicit, not a hallucination, but operators should know defaults are not model outputs. |
| `apps/core/safety/guardrails.py` — safety classifier (`complete_json`) | `{blocked, categories, confidence, reason}` | **MED** | Fail-closed policy is independent of the LLM call (keyword layer always blocks on its own), so a malformed classification degrades safely. Schema-gatable via the new `schema=` param (not yet applied — classifier shape is ad-hoc). |
| `apps/core/cognition/*`, `apps/core/engines/*`, `apps/core/agents/*` (planner, orchestrator, diagnostic_engine, hypothesis_manager, reasoning_engine, self_healer, code_reflector, auditor…) | Internal plans, diagnoses, hypotheses, code-review verdicts | **MED** | Outputs drive internal agent behavior, not user-facing facts or money. All flow through `complete_json` and can now opt into schemas (e.g. `AgentPlan`). Not wrapped yet — each needs its own schema defined from its prompt contract. |
| `apps/core/integrations/computer_agent.py`, `apps/core/integrations/mcp_agent.py` | Agentic tool-use loops (Anthropic SDK direct) | **LOW** | Outputs drive tool calls inside bounded loops, not facts shown to users. Both require explicit API keys; failures degrade to explicit errors. |
| `apps/core/webhooks/webhook_monitor_controller.py` | 200-token internal classification (Anthropic SDK direct) | **LOW** | Internal monitoring signal; short, bounded, non-user-facing. |
| `apps/core/llm/llm_client.py` (shim) | Pass-through to `complete_json` | **LOW** | `**kwargs` forwarding already carries the new `schema=` param — no change needed. |
| `apps/core/integrations/hf_connector.py` | Model-hub operations (no generation) | **NONE** | `huggingface_hub` used for downloads/metadata only — not an LLM call site. |

## What was implemented (2026-10-07)

**New package `apps/core/llm/contracts/`** (vendored U2/U3/U5 pattern):
- `schemas.py` — pydantic v2 contracts. Mirrors of the TS package (`ExtractionResult`, `ExecutiveSummary`, `FindingClassification`, `RoadmapPhase`) + ARIA output schemas (`DigitalProductData`, `EbookMeta`, `OfferData`, `AgentPlan`/`MissionStep`).
- `validate.py` — `validate_or_retry(fn, schema, max_attempts=3, base_delay_s, schema_name)`: validate → exponential backoff retry → `DeadLetterEntry`. Never invents data.
- `dead_letter.py` — `DeadLetterEntry`, `DeadLetterQueue` (JSON round-trip), process-wide singleton `get_dead_letter_queue()`. Push logs a warning — the queue is **visible**, never silent.
- `citations.py` — U5: `fuente:id` format, `finding_citations()` derived from evidence provenance, `validate_citations()` **raises** when a finding has < 3 valid citations.
- `deterministic.py` — U3: `safe_price_cents()` / `usd_to_cents()` — pure, total (never raise), clamp + safe default + warning log.

**Wiring (behavior-preserving):**
- `AriaAIClient.complete_json(..., schema=None, schema_name=None)`: with a schema → gate + dead-letter → `{}` on persistent failure (same legacy failure contract); without → byte-identical legacy behavior.
- `get_health_summary()` now exposes `dead_letters: {count, recent[5]}`.
- Money boundaries hardened (see HIGH rows above).

**Tests:** `tests/unit/test_llm_contracts.py` — **28 tests**, all passing (venv: pydantic 2.13.4 + pytest + pytest-asyncio). Covers: every schema's accept/reject, retry-then-success, invalid JSON → dead-letter (attempts=3, errors recorded, data never padded), fn-raising → dead-letter, queue JSON round-trip, client gate wiring (valid passes / invalid → `{}` + queued), price clamps/rounding/garbage-never-raises, citation validation throw/pass.

**Verification:** `pytest tests/unit/test_llm_contracts.py` 28/28 green · `py_compile` on all touched files · `ruff check` clean on all touched files. Pre-existing `tests/unit/test_ai_client_fixes.py` collection errors in this sandbox are environmental (identical on pristine tree via `git stash`).

## How to harden the next call site

```python
from apps.core.llm.contracts import AgentPlan  # or define your own BaseModel

plan = await ai.complete_json(
    system=..., user=...,
    schema=AgentPlan, schema_name="AgentPlan",  # U2 gate
    agent_name="orchestrator",
)
# plan == {}  →  check get_dead_letter_queue() / health summary
```

For anything user-facing with numbers: derive citations via `finding_citations(evidence)` and call `validate_citations(findings)` **before** rendering (U5). For anything touching money: pass the raw LLM value through `safe_price_cents`/`usd_to_cents` (U3).

## Known limitations (honest)

- Only the 3 money-boundary call sites are schema-wrapped; the ~45 remaining `complete_json` callers keep legacy behavior until each gets its own schema (opt-in, no breakage).
- The dead-letter queue is in-memory (process lifetime); a persistent sink (Supabase table) is the natural next step for multi-worker deploys.
- Direct-SDK call sites (support/computer/mcp/webhook agents) bypass the central gate by design; they are free-text or tool loops, rated MED/LOW above.
