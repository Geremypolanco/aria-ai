# Saraph — Canonical Fact Sheet (source of truth for all grant applications)

> Every answer in the application kits is built from the facts below so they stay
> consistent across programs. **Honesty rule:** ARIA is pre-revenue. No metric,
> testimonial, or customer count is invented anywhere in this kit. Where a program
> asks for traction we describe what is genuinely true: a live product that can take
> a real payment and deliver a real product, built solo.

## Identity (you must fill the [BRACKETS] — I don't have these confirmed)

| Field | Value |
|---|---|
| Founder legal name | `[YOUR LEGAL NAME]` |
| Founder email | saraph.core@gmail.com |
| Country / city of residence | `[YOUR COUNTRY, CITY]` |
| Company / project name | Saraph (product: **ARIA by Saraph**) |
| Legal entity status | Not yet incorporated — solo founder / sole proprietor |
| Website (product, live) | https://aria-ai.fly.dev |
| Website (company page) | https://aria-ai.fly.dev/saraph |
| GitHub | https://github.com/geremypolanco/aria-ai |
| Founded | 2026 |
| Team size | 1 (solo founder, building with AI agents) |
| Funding raised | $0 (bootstrapped, pre-revenue) |
| Stage | Pre-seed / MVP live |

## One-liner (≤140 chars)
ARIA is an autonomous AI revenue operator: it runs marketing and growth actions for
small businesses and reports the work it did.

## Short description (≤300 chars)
ARIA by Saraph is an autonomous AI "revenue operator." Instead of another chatbot, it
executes real growth work — outreach, content, funnel and offer optimization — on the
accounts a business connects, then reports what it ran. Live product with real Stripe
checkout and instant digital delivery.

## What is genuinely built and live (verifiable)
- FastAPI / Python application deployed on Fly.io at https://aria-ai.fly.dev
- Public landing + company page, privacy & terms, FAQ
- Real Stripe checkout links (live mode) with post-payment delivery:
  digital products redirect to an access page, subscriptions to onboarding
- Two real downloadable digital products (prompt pack, automation playbook)
- An autonomous "income loop": a scheduler that selects from a library of growth
  strategies using a Thompson-sampling bandit and records each cycle
- A reusable Capability Registry and a social broadcaster module
- Public activity feed endpoint exposing the actions the loop has run
- CI with linting (black + ruff) and a test suite

## Tech stack
Python 3.11, FastAPI, Uvicorn, Redis (Upstash REST) for state, Stripe for payments,
deployed as a Docker image on Fly.io, CI/CD via GitHub Actions. AI via the Anthropic
Claude API.

## The problem
Small businesses and solo founders know they should be doing consistent marketing and
growth work, but they don't have time, and they can't afford an agency ($2–8k/mo) or a
full-time marketer. Existing "AI marketing tools" are chat assistants that give advice
but don't *do* the work — the human still has to execute everything.

## The solution / why it's different
ARIA is built to *execute*, not advise. It connects to the business's own accounts and
offers, runs a continuous loop of growth actions, and reports what it did — a
"done-with-you" operator rather than a copilot. Pricing targets the gap between
DIY tools and a $3k/mo agency.

## Why AI / why now
ARIA is only possible because frontier LLMs can now plan, write, and call tools
reliably enough to run multi-step growth workflows with a human approving direction
rather than doing every task. The whole company is built by one founder orchestrating
AI agents — which is itself the thesis: small teams operating at agency scale.

## Use of credits (honest, specific)
- **Cloud (Azure/AWS):** host the FastAPI app, background workers for the income loop,
  Redis/Postgres state, and a queue so each customer gets an isolated worker. Today
  this runs on a single small Fly.io machine; credits let us run real per-customer
  workers without burning the $0 budget.
- **AI model credits (Anthropic):** every ARIA action is an LLM call. Model credits
  directly fund the core product loop and let us raise quality (better planning,
  longer context) without per-call cost killing unit economics pre-revenue.

## Business model
- Free automated growth audit (lead magnet)
- One-time digital products ($)
- Monthly subscription "ARIA operates your growth" tiers
- Done-for-you setup builds

## The ask per program
Cloud + AI credits to run the product for real customers without a cash runway, while
we land the first paying customers.
