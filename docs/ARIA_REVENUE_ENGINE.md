# Aria Revenue Engine — Architecture & Consolidation Plan

Prospect discovery → business analysis → ROI-backed recommendations →
proposal/collateral generation → pipeline tracking → post-sale delivery.

**This is a consolidation-and-completion plan, not a from-scratch build.**
A survey of the codebase before writing a line of new code found that most
of the six capabilities below already exist, are wired into a live
conversation (`aria_mind.py`'s tool dispatcher), and already follow the
honesty/safety conventions this project has been hardening all session
(disclosed heuristics, no fabricated data presented as real, human review
before anything externally visible). Building a parallel system instead of
finishing this one would throw that away for no reason. The one capability
with **zero prior code** — post-sale delivery — is built in Phase 1 below.

---

## 1. What already exists, mapped to the six requested capabilities

### 1.1 Prospect discovery
- `apps/acquisition/scraper/lead_scraper.py` (`LeadScraper`) — real web
  discovery (DuckDuckGo instant-answer API), enriches by fetching the
  business's actual site and checking for missing meta description, no
  contact form, no analytics/tracking. Falls back to clearly-tagged
  synthetic archetype leads when live results run short — never presents
  a synthetic company as real (`source: "synthetic"` vs `"duckduckgo"`).
- `apps/acquisition/leads/lead_engine.py` (`LeadEngine`) — AI-scored lead
  qualification and status tracking (`new → contacted → qualified →
  proposal → closed/lost`).
- `apps/acquisition/linkedin/linkedin_outreach.py` — a parallel prospect
  pipeline scoped to LinkedIn specifically (relevance scoring, connection
  requests, 4-message sequences — draft generation only, see §2).
- Wired into chat as `discover_leads`, reachable and tested
  (`tests/unit/test_acquisition_wired_into_aria_mind.py`); the system
  prompt (`aria_mind.py` rule 19) explicitly instructs never to present an
  illustrative example as a real, contactable business.

### 1.2 Business/digital-presence analysis
- `LeadScraper.enrich_lead()` — real HTML-level analysis per prospect
  (meta description, contact form, web forms, analytics/tracking presence).
- `apps/market/opportunities/opportunity_finder.py` — template-driven
  opportunity synthesis (content/product/service/affiliate) with
  ease/revenue-range/time-to-first-revenue estimates per niche.
- **Gap:** no real traffic/SEO-ranking/ads-spend API integration (e.g.
  SimilarWeb, Ahrefs, SEMrush, Google Ads API) — analysis is limited to
  what a page's own HTML reveals. Queued as Phase 2 (§4).

### 1.3 ROI engine / recommendations
- `apps/economics/roi_tracker.py`, `apps/core/business/roi_engine.py`,
  `apps/learning/roi/roi_learner.py` — three modules; not yet reconciled
  into one canonical engine (see §3, consolidation debt).
- `track_roi` / `update_roi_returns` / `roi_summary` tools are pure
  bookkeeping on numbers the user supplies — the system prompt (rule 42)
  is explicit that ARIA must never estimate a return and log it as if the
  user provided it.

### 1.4 Proposal generation / commercial deliverables
- `apps/acquisition/leads/lead_engine.py`'s `generate_proposal_brief()` —
  AI-drafted subject/hook/pain/solution/social-proof/CTA, wired as
  `generate_sales_proposal`.
- **Gap:** output is a text brief, not a polished deliverable document
  (PDF/HTML). The manually-built Stripe-payment-link + hosted-guide-page
  flow used earlier this session (a real $79 product, real payment link,
  real public LinkedIn post) is the template for what this should become —
  see Phase 2.

### 1.5 Pipeline management / CRM
- `apps/acquisition/crm/crm_engine.py` (`CRMEngine`) — B2B sales pipeline
  (`new → contacted → qualified → proposal → negotiation → closed_won/
  lost`), weighted forecasting, AI `suggest_next_action`.
- `apps/business/crm/crm_engine.py` — **a deliberately different CRM**,
  not a duplicate: this is client-lifecycle memory for people ARIA already
  has a relationship with (`upsert_client_profile`, `record_client_
  interaction`, `segment_client` — system prompt rule 22 states this
  distinction explicitly). Confirmed intentional, not consolidation debt.
- `apps/core/connections/crm_connection.py` — full `HubSpotConnection` /
  `SalesforceConnection` OAuth clients (contact/deal/company CRUD) already
  built. **Unused** — nothing calls them today. Real opportunity: a
  prospect's own business may already run HubSpot; syncing outward means
  a human sales rep isn't limited to querying pipeline state through chat.

### 1.6 Post-sale delivery automation
- **Confirmed zero prior code.** `docs/ARCHITECTURE_REVIEW.md` and
  `apps/core/capabilities/catalog.py` both claimed a working `/access/{key}`
  Stripe-redirect fulfillment route existed (`status=ACTIVE, verified=True`).
  It does not — grepped the entire repo, no such route exists anywhere.
  That catalog entry has been corrected (see §5) rather than left standing;
  an operator trusting that catalog would have wrongly concluded delivery
  was solved.
- **Built this session — see Phase 1.**

---

## 2. A structural pattern worth naming: draft vs. dispatch

Every generation tool above (`generate_sales_proposal`,
`generate_linkedin_connection_request`, `generate_linkedin_outreach_
sequence`, `personalize_step` in `OutreachSequencer`) produces content and
stops. Nothing in the acquisition stack calls a real send/post action —
that's a deliberate property, not an oversight: it's already exactly the
human-control requirement in this task ("prepara el contenido... para
revisión humana antes del envío"). The one tool that *can* actually send —
`send_email` — already has its own two-layer gate (Layer 2 constitutional
review with fail-closed HITL escalation on an unsafe verdict, Layer 3
deterministic content firewall; see `tests/unit/
test_constitutional_review_covers_live_effect_tools.py` and
`test_layer3_content_firewall_wired_into_publish_tools.py`). `post_to_social`
uses a different, stricter gate (forced code-level preview + confirm_token)
because it carries a different risk profile — an unofficial session with
real account-ban exposure, not an official transactional API.

**Net finding: there is no missing human-review gate to retrofit.** The
actual gaps are fragmentation (§3) and the one capability with no send path
at all (§1.6 / Phase 1).

---

## 3. Consolidation debt (not urgent, tracked)

- **No shared prospect identity.** A single company can exist as an
  unrelated record in `LeadEngine`, `CRMEngine`, `LeadScraper`'s scrape
  history, and `LinkedInOutreach` simultaneously, each in its own Redis
  key. Nothing to fix today (each module works standalone), but a future
  phase should introduce a shared `prospect_id` a human or ARIA can use
  to pull the full picture across all four.
- **Three ROI modules** (`apps/economics/roi_tracker.py`,
  `apps/core/business/roi_engine.py`, `apps/learning/roi/roi_learner.py`)
  — worth an audit to confirm they serve genuinely different purposes
  (tracking realized ROI vs. predicting/learning ROI vs. calculating a
  recommendation) before assuming any should merge.
- **HubSpot/Salesforce connectors built, unused.** No integration work
  scheduled until a concrete need names which CRM to sync first.
- **No workspace-scoped state, anywhere in the acquisition suite.**
  `CRMEngine`, `LeadEngine`, `LeadScraper`, `OutreachSequencer`, and the new
  `DeliveryEngine` all share the identical pattern: one global Redis key,
  one process-global singleton, no `workspace_id_for(email)` derivation
  (contrast with `CashflowEngine`/`ROITracker`, which already take a
  workspace id — see `aria_mind.py`'s `cashflow_summary`/`track_roi`
  handlers). Flagged by CodeRabbit on this PR against `DeliveryEngine`
  specifically; true of every sibling module, not new here. Retrofitting
  one module in isolation wouldn't close the actual boundary (the others
  would still be crossable), so this needs a suite-wide pass, not a
  one-file patch — tracked as its own phase rather than folded into Phase 1.
- **Whole-document read-modify-write, same suite.** Every module above
  loads one JSON blob, mutates it in memory, and writes the whole thing
  back — no atomic Redis primitives or optimistic versioning, so two
  concurrent workers can clobber each other's writes. Same reasoning as
  above: a repo-wide pattern, best fixed once across all of them together.

---

## 4. Phase roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Post-sale delivery automation (`DeliveryEngine`) | **Done — this PR** |
| 2 | Proposal briefs → real deliverable documents (HTML/PDF), reusing the Stripe-payment-link + hosted-page pattern already proven this session | Planned |
| 3 | Wire a live Stripe webhook → `deliver_purchase`, so delivery fires on actual payment instead of a chat request | Planned |
| 4 | Real digital-presence analysis via an external SEO/traffic API | Planned |
| 5 | Shared prospect identity across the acquisition modules | Planned |
| 6 | HubSpot/Salesforce sync for prospects who already run a CRM | Planned (needs a concrete first user) |
| 7 | Workspace-scoped, atomically-persisted state across the whole acquisition suite (`CRMEngine`, `LeadEngine`, `LeadScraper`, `OutreachSequencer`, `DeliveryEngine`) | Planned (§3) |

---

## 5. Phase 1 — Post-Sale Delivery Automation (shipped)

**New:** `apps/acquisition/delivery/delivery_engine.py` (`DeliveryEngine`).

- `register_deliverable(sku, name, content, delivery_type, price_usd)` —
  the one point new content enters the system. Runs the same Layer 3
  content-safety firewall (`guardrails.check_content_safety`) used by
  `send_email`/`post_to_social`, once, at registration — this is the
  point a human is actually deciding what a SKU will send, so it's the
  right (and only) place to gate.
- `deliver(sku, buyer_email, buyer_name, order_ref)` — looks up what was
  registered and sends it via `PublishingTools.send_newsletter` (the same
  real Resend → SendGrid → Mailgun stack the wired `send_email` tool
  uses — no second bespoke send mechanism). Never invents content: a sku
  that was never registered returns `status="no_deliverable"`, logged and
  reported plainly, not silently skipped or filled with a guess.
- Wired into `aria_mind.py` as `register_deliverable` / `deliver_purchase`
  (system-prompt catalog entries + rule 19a), state persisted in Redis
  (`acquisition:delivery:v1`, 365-day TTL, following the same
  load/save-with-try/except convention as `CRMEngine`/`LeadEngine`).
- `apps/core/capabilities/catalog.py`'s `fulfillment.digital_delivery`
  entry corrected to describe this real mechanism instead of the
  nonexistent `/access/{key}` route.
- **Idempotency, hardened through CodeRabbit review:** `deliver()` is
  idempotent per `(sku, order_ref)` — a repeat call for an order already
  `sent` or `ambiguous` returns the stored record rather than acting again.
  The check-then-send-then-record sequence runs under a Redis lock fenced
  with a per-call token (release only deletes the lock if it still holds
  *this* call's token), so two genuinely concurrent calls can't both pass
  the dedup check and both send. A provider call that raises instead of
  cleanly failing is recorded as `"ambiguous"` (outcome genuinely unknown),
  never `"failed"` — the dispatcher phrases that outcome to deliberately
  avoid every substring `AriaMind._FAILURE_SIGNALS` matches on, so the
  generic tool-retry loop can't treat an unconfirmed send as safely
  retryable. Two things this does not fully close, documented in
  `deliver()`'s own docstring rather than assumed away: the lock's TTL is a
  fixed lease, not a renewable heartbeat, so a send slower than the lease
  can still race; and there's no idempotency key on the provider side, so
  "ambiguous" can only be flagged, not automatically resolved.

**Tests:** `tests/unit/test_delivery_engine.py` (registration validation,
content-safety blocking, send success/failure, sequential and concurrent
idempotency, ambiguous-outcome handling, refusal on an unregistered sku,
stats) and `tests/unit/test_delivery_tools_wired_into_aria_mind.py`
(dispatcher reachability, matching the `test_social_session_wired_into_
aria_mind.py` convention of exercising `AriaMind._execute_tool` directly
rather than the engine in isolation — including asserting the ambiguous/
in_progress responses don't trip `_looks_like_failure()`).

**Known limitation, disclosed rather than hidden:** delivery today is
triggered by asking ARIA to run `deliver_purchase` — it is not yet wired
to fire automatically the instant a Stripe payment lands (Phase 3). Until
then, closing a deal in the CRM does not by itself deliver anything; a
human (or ARIA, when asked) still has to call `deliver_purchase`.
