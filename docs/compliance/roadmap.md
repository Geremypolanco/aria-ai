# ARIA Compliance & Governance Roadmap

This document tracks, honestly, where ARIA stands on security, privacy, and AI
governance. It is an internal working map, not a compliance certificate or legal
advice. **Where a framework is not yet met, this document says so.** Before
making any external compliance claim, have it reviewed by qualified legal
counsel.

Status legend:

- **In place** — a control we actually run today.
- **In progress** — actively being built; not yet complete or audited.
- **Roadmap** — planned; not started or early.

---

## Operating boundaries (in place)

ARIA's behavioural limits are defined once in `apps/core/governance.py`
(`OPERATING_BOUNDARIES_PROMPT`) and injected into the system prompt in
`apps/core/cognition/aria_mind.py`, so they shape behaviour on every call rather
than living only in a policy page. The public version is on `/trust` and is
generated from the same module (`PUBLIC_BOUNDARIES`). Summary of what ARIA will
not do: copyright/IP infringement, counterfeit branding, illegal or
crime-facilitating content, deceptive impersonation / deepfakes / fake reviews,
harassment or exploitation, unlawful personal-data processing, posing as a
licensed professional, and platform-terms violations.

Follow-ups:

- [x] `apps/core/agents/compliance_agent.py` is wired into the action path via
      `BaseAgent.execute_with_approval()` — `cfo_agent.py`'s ebook-publish flow
      routes through it today (fail-closed: an unreachable/erroring reviewer
      blocks + requires human review rather than defaulting to allow). Only one
      agent action is wired so far; extending this to every high-risk action
      (outreach, code execution, future agent-initiated spend) is still open.
- [ ] Log boundary refusals for review.

## Security controls

| Control | Status | Where |
| --- | --- | --- |
| HTTPS everywhere + HSTS | In place | `_SECURITY_HEADERS` middleware, `main.py` |
| Security response headers (nosniff, frame, referrer, permissions, COOP, CSP frame-ancestors) | In place | `main.py` |
| OAuth-only sign-in (Google/GitHub) + email/password (PBKDF2-HMAC-SHA256, 200k iterations); signed HMAC session cookie | In place | `auth`, `auth_accounts` |
| Payments via Stripe; no card storage; checkout-session replay/account-mismatch guarded | In place | `main.py` billing routes |
| Secrets in environment, not in code; `.aria/secrets/` (local key store) gitignored, never committed | In place | `config.py`, `.gitignore` |
| Strict Content-Security-Policy (script-src) | Roadmap | needs inline-script refactor |
| CORS restricted to an explicit origin allowlist (not `*` — `allow_credentials=True` forbids that anyway) | In place | `main.py` CORS middleware |
| Rate limiting: shared distributed counter (Upstash) with in-process fallback, applied to every costed/abusable endpoint | In place | `main.py` `_rate_ok` |
| Centralized audit logging of security events | In progress | `execution_audit`, expand coverage |
| Dependency/vulnerability scanning in CI | In progress | CI "Security Audit" job; bandit + pip-audit run but are advisory-only (`continue-on-error`), not a merge gate |
| Raw shell execution tools (`InfraTools.execute_system_command`, `CodeExecutor.execute_shell_command`) disabled by default, opt-in via `ALLOW_SYSTEM_COMMANDS` | In place | `infra_tools.py`, `code_executor.py` |
| Documented access control & least privilege | Roadmap | — |

## SOC 2 Type II — In progress

Not certified. Building the control set and evidence.

- [ ] Formal security policies (access, change management, incident response).
- [ ] Access reviews and least-privilege enforcement.
- [ ] Centralized logging & monitoring with retention.
- [ ] Vendor/subprocessor inventory and risk review.
- [ ] Select an auditor and complete a readiness assessment before the Type II
      observation window.

## ISO/IEC 27001 — Roadmap

Not certified. Requires an Information Security Management System (ISMS).

- [ ] Scope the ISMS and run a risk assessment.
- [ ] Statement of Applicability against Annex A controls.
- [ ] Management review cadence and internal audit.

## HIPAA — Roadmap (NOT supported today)

ARIA is **not** a HIPAA-compliant service and we do **not** sign Business
Associate Agreements. The product must continue to tell users not to submit
protected health information (PHI). Reaching HIPAA would require, at minimum:

- [ ] Signed BAAs with every subprocessor that could touch PHI.
- [ ] Encryption of PHI in transit and at rest with documented key management.
- [ ] Access controls, audit trails, and breach-notification procedures.
- [ ] A risk analysis and workforce training.

Until all of that exists, the `/trust` page and product surfaces state plainly
that PHI is not supported.

## Privacy — GDPR & CCPA (In progress)

- [x] Privacy Policy published (`/legal/privacy`).
- [x] Data access & deletion available on request (email).
- [ ] Self-serve data export and account deletion endpoints.
- [ ] Records of processing activities (RoPA) and a data inventory / map.
- [ ] Data Processing Agreement (DPA) template for business customers.
- [ ] Cookie/consent review.

## AI governance — EU AI Act & transparency (In progress)

- [x] Published operating boundaries and Responsible AI section (`/trust`).
- [x] AI-generated-content disclosure guidance in ARIA's behaviour.
- [x] Human-in-the-loop / clarify-before-acting gate for consequential actions.
- [ ] Classify ARIA's use cases against EU AI Act risk tiers.
- [ ] Model/provider inventory and a basic transparency ("system card") page.
- [ ] Content provenance / watermarking review for generated media.

---

_Last reviewed: 2026-07-24. Owner: SARAPH. This is a living document; update the
statuses as controls land, and never let the public Trust Center claim more than
this file supports._
