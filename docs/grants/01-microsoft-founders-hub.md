# Application Kit — Microsoft for Startups Founders Hub

**Why this one first:** highest credit value (up to ~$150K Azure over the program),
**no incorporation required**, **no equity, no funding requirement**, solo founders
eligible. Approval is fast and largely self-serve.

- Apply at: https://www.microsoft.com/en-us/startups
- Sign in with the Microsoft/GitHub account tied to **saraph.core@gmail.com**
- Benefits include Azure credits, Microsoft 365, GitHub Enterprise, and Anthropic/
  OpenAI model access through the Azure marketplace.

---

## Ready-to-paste answers

**Company / startup name**
> Saraph

**Company website**
> https://aria-ai.fly.dev

**Your role**
> Founder

**What stage is your startup?**
> Pre-seed — MVP live, pre-revenue

**Have you raised funding?**
> No (bootstrapped)

**Headcount**
> 1

**What are you building? (short)**
> ARIA by Saraph is an autonomous AI revenue operator. Instead of another chatbot that
> gives advice, ARIA executes real marketing and growth work on the accounts a small
> business connects — outreach, content, funnel and offer optimization — then reports
> exactly what it ran. It's the gap between a $20/mo DIY tool and a $3,000/mo agency.

**Describe your product and the problem it solves (long)**
> Small businesses and solo founders know they should run consistent marketing, but
> they have no time, and an agency costs $2,000–8,000/month. Today's "AI marketing
> tools" are chat assistants — they hand back advice and the human still has to do all
> the execution.
>
> ARIA is built to *execute*, not advise. It connects to the business's own accounts
> and offers and runs a continuous loop of growth actions, choosing what to do next
> with a multi-armed-bandit strategy selector and reporting every action it takes. The
> product is live at https://aria-ai.fly.dev: it has a real Stripe checkout, instantly
> delivers digital products after payment, and exposes a public feed of the actions
> its autonomous loop has run. It's a "done-with-you" growth operator priced for
> businesses that can't afford an agency.

**How does your startup use AI? (this gates the AI benefits)**
> AI is the product, not a feature. Every action ARIA takes is an LLM call: it plans
> the next growth action, writes the outreach/content, decides which strategy to run
> next, and summarizes what it did for the customer. The core engine is a scheduler
> that selects from a library of growth strategies using Thompson sampling and executes
> each one through model-driven tool calls. The entire company is built and operated by
> a single founder orchestrating AI agents — which is the thesis itself: one person
> running at the scale of a team.

**How will you use Azure credits?**
> 1) Host the FastAPI application and the always-on background workers that run the
> autonomous growth loop. 2) Run an isolated worker per customer (queue + container)
> so each business's automation runs independently — the single biggest cost we can't
> cover at $0 revenue. 3) Managed Redis/Postgres for state and job history. 4) Azure
> OpenAI / model endpoints for the LLM calls at the core of the product. Credits let us
> serve real paying customers without a cash runway while we land the first accounts.

**What's your tech stack?**
> Python 3.11, FastAPI, Uvicorn, Redis for state, Stripe for payments, Docker, GitHub
> Actions CI/CD, Anthropic Claude API for the AI. Currently deployed on Fly.io; Azure
> credits would let us move the per-customer worker fleet onto Azure Container Apps.

**What traction do you have? (be honest — pre-revenue)**
> Pre-revenue. What's real and verifiable: a live product that already takes a real
> payment and delivers a real digital product end-to-end, an autonomous action loop
> running in production, and the full funnel (landing → audit lead magnet → checkout →
> delivery) built and deployed. Current focus is landing the first paying customers.

**Anything else?**
> Built solo, fully bootstrapped, in the open at
> https://github.com/geremypolanco/aria-ai. We're applying for credits specifically to
> run real per-customer infrastructure and model calls during the zero-to-one revenue
> phase.

---

## What I (the AI) cannot do for you on this one
1. **Sign in as you.** The form is tied to your Microsoft identity — you click "Sign
   in", I can't impersonate that login.
2. **Assert your legal name / country.** Fill `[YOUR LEGAL NAME]` and `[YOUR COUNTRY]`
   — using your real legal identity is yours to do.
3. **Click "Submit".** A grant application is a legal representation by you; you press
   the final button.

Everything above the line is ready to paste verbatim. Estimated time for you: ~10 min.
