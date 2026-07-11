# ARIA — 30-Day Go-To-Market & Monetization Master Plan

**Product:** ARIA — *"The AI that executes."* (aria-ai.fly.dev · brand SARAPH)
**Plans (real, from `BILLING_PLANS`):** Free · **Pro $29/mo** · **Business $99/mo**
**Window:** Day 0 (deploy) → Day 30. **Objective:** first paying cohort + a Product Hunt ignition, on a unit-economics-positive footing.

> **Honesty rule (non-negotiable, inherited from GROWTH_PLAYBOOK.md).** No fabricated users, revenue, testimonials, or "trusted by" logos. Every public asset either (a) shows ARIA *actually doing the work on camera*, or (b) states value as a **clearly-labeled estimate**. The moment we have real screen-recordings / before-afters, they replace the estimates.

> This plan is **operational, not theoretical** — it plugs into systems that already exist in this repo: the async **Missions API** (`POST /api/v1/missions`), the **worker** + scheduler, the **connectors** (LinkedIn/IG/YouTube), **Stripe checkout** (`/billing/checkout`), the **God Mode `/admin`** console (`/admin/api/overview`), and the **cost ledger** (`apps/core/ops/cost_ledger.py`). Where a step needs a connected account or an API key we don't have yet, it is marked **[gated]** and degrades to a human-approval step — nothing here is a broken placeholder.

---

## AXIS 1 — The ARIA Loop: an autonomous 24/7 marketing agency, run *by* ARIA

**Thesis:** ARIA's own output *is* the ad. We use ARIA to manufacture the content that sells ARIA, so every post is a live demo. The loop compounds: each new user's deliverables become tomorrow's proof.

### 1.1 The exact daily flow (one ARIA mission, human 30-sec approve)

```
DAILY 08:00 local — ARIA runs autonomously, founder approves from phone
 ┌───────────────────────────────────────────────────────────────────────┐
 │ 1. LISTEN   Scrape today's AI-automation trends on X + Instagram        │
 │             (hashtags, rising audios, spiky takes). Rank by velocity.   │
 │ 2. PICK     Choose the single highest-tension angle of the day.         │
 │ 3. SCRIPT   Write a 20–35s vertical script: hook → live ARIA demo →     │
 │             payoff → CTA. "Build in Public" framing.                    │
 │ 4. PRODUCE  Generate the vertical video (Short/Reel) + voiceover        │
 │             (ElevenLabs [gated] → honest stub if no key) + captions.    │
 │ 5. APPROVE  Push a preview to the founder (support-widget / email).     │
 │             Human taps ✅ or ✏️. NOTHING publishes without approval.     │
 │ 6. PUBLISH  Post to TikTok / Reels / Shorts via connectors [gated].     │
 │             Caption ends with the Bitly-shortened landing link + UTM.   │
 │ 7. MEASURE  Log post → clicks (Bitly) → signups (UTM) → activation.     │
 └───────────────────────────────────────────────────────────────────────┘
                 New Pro user's outputs → tomorrow's content → repeat
```

**Why a human approval gate (not full auto-post):** publishing to *real* branded social accounts is outward-facing and hard to reverse. The gate costs the founder ~30 seconds/day and protects the brand + the honesty rule. Flip to full-auto later once trust in the pipeline is earned.

### 1.2 Ready-to-run mission spec (drop into the Missions system)

Create a recurring mission. This is the literal payload the scheduler POSTs to the existing endpoint each morning:

```jsonc
// POST /api/v1/missions   (auth: founder session)  → 202 Accepted
{
  "message": "DAILY_GROWTH_LOOP",   // routed to the growth playbook below
  "provider": "default",
  "session_id": "aria-growth-loop"
}
```

**System prompt for the growth mission** (store as the mission's playbook; keep it in-repo so it's versioned):

```text
You are ARIA running your own 24/7 growth studio in "Build in Public" mode.
GOAL: produce ONE high-retention vertical video (20–35s) that demonstrates a
REAL ARIA capability and drives clicks to https://aria-ai.fly.dev.

STEPS:
1. Pull today's AI-automation trends from X and Instagram (rising hashtags,
   audios, and debates). Return the top 3 with a one-line "why it's spiky".
2. Pick the ONE angle where ARIA can show, not tell (e.g. "watch ARIA turn a
   URL into a finished Reel in 40s").
3. Write the script as: HOOK (0–3s, pattern-interrupt) → LIVE DEMO (screen of
   ARIA working, real output) → PAYOFF (the finished asset) → CTA ("Try it
   free — link in bio").
4. Generate the vertical video + voiceover + burned-in captions.
5. Output a preview bundle for human approval. Do NOT publish anything.

HARD RULES:
- Never fabricate metrics, testimonials, or user counts. If you cite a number,
  label it an estimate or show it happening on screen.
- Every claim must be something ARIA can actually do on camera right now.
- Keep the brand voice: confident, technical, no hype-slop.
```

### 1.3 Scheduling & wiring (uses what's already here)

- **Scheduler:** `apscheduler` (already a dependency) fires the mission daily at 08:00; the mission enqueues via the **task queue** and the **worker** processes it (see `SCALE_ARCH.md`). One line of cron config, zero new infra.
- **Approval channel:** reuse the **24/7 support widget** backend / founder email for the preview → ✅.
- **Publishing [gated]:** the **webhook/connector** layer posts to the platforms once LinkedIn/IG/YouTube tokens are connected in Settings → Connectors. Until then, step 6 hands the founder the finished file to post manually (still a 60-sec action).
- **Link tracking:** every caption link is a **Bitly** short link (Bitly connector is available) with a UTM: `?utm_source=reel&utm_medium=organic&utm_campaign=aria_loop&utm_content=YYYYMMDD`. Bitly click data + UTM landing hits = the top of the funnel dashboard (Axis 4).

### 1.4 High-retention format rules (so the videos actually perform)

- **Hook in ≤3s**, on-screen text + spoken, states the payoff up front ("I gave an AI a URL and it published a Reel in 40 seconds").
- **Show the screen.** Real ARIA UI doing the task > talking head. Proof beats promise.
- **One idea per video.** One capability, one CTA.
- **Native captions** burned in (sound-off viewing).
- **Cadence:** 1/day minimum on Reels + Shorts + TikTok (same asset, 3 platforms). Post the *best* performer's angle again 3 days later with a new hook.
- **CTA discipline:** "Try it free" → link in bio → `/` → `/login`. Never send cold traffic straight to checkout.

**Loop KPI (Axis 4 ties in):** Reels views → Bitly clicks → free signups → first-mission activation → Pro upgrade at the daily-limit wall.

---

## AXIS 2 — Aggressive B2B acquisition on LinkedIn

**Targets:** (A) Marketing-agency owners, (B) Content creators / creator-operators, (C) Product / Growth directors.
**Sell:** the ROI of delegating the *multimedia production workflow* to ARIA — research → generate → publish — safely, on Pro ($29) or Business ($99, multi-seat/workspaces).

> **Honesty framing:** we sell the **capability and the workflow it replaces**, framed as an **estimate you can verify in a live demo** — not a fabricated case study. The "~40 hours/week" figure is positioned as *the size of the workflow ARIA is designed to absorb*, an **illustrative estimate**, immediately followed by an offer to prove it live. Never invent a client result.

### 2.1 The 3-touch sequence (paste-ready)

Sequence rhythm: **T+0 connection note → T+2 days value message → T+5 days soft close.** Personalize the first line every time (their post/portfolio) — the sequence is a skeleton, not a spray.

**TOUCH 1 — Connection request (≤300 chars, no pitch):**
```
Hi {{first}} — I build ARIA, an AI that actually *executes* multimedia work
(research → video/voice → publish), not just chats. Following your work at
{{company}} because this is exactly the workflow it's built to take off your
plate. Would love to connect.
```

**TOUCH 2 — Value message (day 2, after they accept):**
```
Thanks for connecting, {{first}}.

Quick reason I reached out: teams like {{company}} burn an estimated 30–40
hrs/week on the produce-and-publish grind — scripting, cutting verticals,
captions, scheduling. ARIA runs that end-to-end: it pulls trends, generates
the video + voiceover, and publishes to your channels, with a human approval
tap before anything goes live.

Not asking you to take my word for it — I'll record ARIA doing one of YOUR
recurring posts, start to finish, and send you the file. If it's useful, Pro
is $29/mo; if you run a team, Business ($99/mo) adds multi-workspace + seats.

Want me to run one on the house?
```

**TOUCH 3 — Soft close (day 5, if no reply):**
```
No worries if the timing's off, {{first}}. One concrete thing before I go quiet:

I recorded ARIA turning a single prompt into a finished vertical video +
captions + voiceover. 40-second clip, no edit: {{bitly_demo_link}}

If you want the same run on your own content, reply "demo" and I'll set you up
free this week. Either way — rooting for {{company}}.
```

### 2.2 Persona micro-adjustments (swap the ROI line in Touch 2)

| Persona | The line that lands |
|---|---|
| **Agency owner** | "Bill it as a productized 'daily content' retainer — ARIA does the labor, your margin expands. Business ($99) gives you a workspace per client." |
| **Content creator** | "Stay daily on 3 platforms without living in CapCut. ARIA scripts, generates, and captions; you approve from your phone." |
| **Product / Growth director** | "Ship 'build-in-public' demand-gen without hiring a video editor. ARIA runs the loop; you keep brand control with an approval gate." |

### 2.3 Operating cadence & guardrails

- **Volume:** 15–20 hyper-targeted connects/day (stay well under LinkedIn's limits; quality > spray). ~300–400 touch-1s over the 30 days.
- **Personalization is mandatory** — the `{{first line}}` must reference something real about them, or don't send.
- **The "free live demo" is the whole strategy.** The recorded ARIA run *is* the proof; it replaces claims with a thing they can watch.
- **Route replies** to a booked 15-min call or a direct free-trial link. Warm B2B → **Business ($99)**; solo → **Pro ($29)**.
- **Track** reply rate and demo-accept rate (industry-typical cold-outreach reply rates are a low-single-digit % — treat any internal number as *measured*, never advertised).

---

## AXIS 3 — Product Hunt launch: "Product of the Day" attack plan

**Ignition event.** PH is one big day that seeds the top of the funnel and gives the LinkedIn + Loop engines social proof to point at.

### 3.1 Pre-launch (T-14 → T-1)

| When | Action |
|---|---|
| **T-14** | Create/'"upcoming"' page. Recruit a **hunter** with reach (optional; self-hunting is fine in 2026). Lock the launch date on a **Tue/Wed/Thu**. |
| **T-14→T-2** | Build a **"launch list"**: everyone who'll get a personal DM at 12:01am PT. Aim for 40–80 real people (LinkedIn connections from Axis 2, friends, communities you're *actually* in). Do **not** buy or fake upvotes — PH detects it and it violates the honesty rule. |
| **T-7** | Produce assets **with ARIA**: the gallery video (ARIA doing a real run), 3–5 screenshots, the thumbnail/logo. |
| **T-5** | Write & rehearse the copy (below). Prepare 6–8 FAQ answers for the comments. |
| **T-3** | Warm up: post the "launching Tuesday" teaser via the Axis-1 Loop and to your LinkedIn network. |
| **T-1** | Final checks: deploy is green, `/login` works, Stripe test purchase works, `/legal/*` live, support widget answering. Schedule the launch-list DMs. |

### 3.2 Launch day (hour-by-hour, Pacific Time — PH resets at 12:01am PT)

| Time (PT) | Move |
|---|---|
| **12:01 AM** | Go live. Post the **Maker's Comment** (below) as the first comment immediately. |
| **12:05–1:00 AM** | Send the personal launch-list DMs (a *link + one honest line*, never "upvote me" — ask for feedback). Reply to every early comment within minutes. |
| **6:00–9:00 AM** | US East wakes up — second DM wave + LinkedIn post + the day's ARIA Loop reel points to the PH page. |
| **All day** | **Reply to 100% of comments within 15 min.** Engagement velocity is the ranking signal. Post a mid-day update ("we're #X, here's what people are asking"). |
| **12:00 PM** | Founder goes live: a short "watch ARIA work" clip in the comments answering the most common question. |
| **6:00–9:00 PM** | West-coast evening push. Thank supporters publicly. Final ask to any warm contacts who haven't seen it. |
| **11:59 PM** | Screenshot the result (whatever it is) — it becomes honest content for Axis 1 & 2 tomorrow. |

### 3.3 Post-launch (T+1 → T+7)

- **T+1:** Thank-you post (LinkedIn + PH) with the *real* outcome — rank, signups, feedback. Turn the launch into a build-in-public reel.
- **T+1→T+7:** Personally onboard every signup; convert PH's free traffic at the daily-limit wall. Ship one visible improvement from PH feedback and tell the commenters you did — that earns durable goodwill.
- **Feed the flywheel:** best PH feedback → product tweaks → new Loop content → LinkedIn proof.

### 3.4 Exact launch copy (paste-ready, honest)

**Name / Title (hook):**
> **ARIA — the AI that executes, not just chats**

**Tagline (≤60 chars options — pick one):**
> `Research → video, voice & posts → published. On autopilot.`
> `Delegate your whole content workflow to one autonomous AI.`
> `The AI agent that actually ships the work.`

**Maker's Comment (first official comment):**
```
Hey Product Hunt 👋 I'm {{maker}}, maker of ARIA.

Most "AI tools" hand you a suggestion and leave the work to you. I wanted the
opposite: an AI that *executes* the whole loop. So ARIA researches a topic,
generates the video + voiceover + captions, and publishes it to your channels
— with a human approval tap before anything goes live.

I've been running ARIA as its own marketing team in public: it makes the
content that markets it. The video in the gallery is a real, unedited run —
prompt in, finished vertical video out.

What's actually built today:
• Autonomous "missions" on a Redis-backed async worker fleet (built to scale)
• Multimedia generation (image / video / voice) + multi-channel publishing
• A 24/7 support agent, Chrome clipper, and HMAC-signed webhook automations
• Honest guardrails: it won't fabricate metrics or post without your approval

Pricing is simple and live: Free to try, Pro $29/mo, Business $99/mo
(multi-workspace for agencies).

I'm here ALL day. Tell me the most annoying, repetitive content task you have —
I'll try to make ARIA do it live in the comments. Brutal feedback welcome. 🙏
```

> **Rule for launch day:** if someone asks for a result we don't have, we *show a live run* or say "not yet — here's the roadmap." We never invent a stat to win a comment.

---

## AXIS 4 — The Founder's Dashboard: the 3 metrics that decide profitability & when to raise

These plug directly into the existing **God Mode `/admin`** (`/admin/api/overview` already returns `revenue_usd`, `estimated_api_spend_usd`, `net_margin_usd`, `user_count`, `frozen_users`, `fly_instances`) and the **cost ledger** (`apps/core/ops/cost_ledger.py`, real Anthropic pricing baked in). Monitor these **daily**.

### Metric 1 — Contribution margin per paying user (unit economics truth)

> **Are we making money on each user *after* the Anthropic bill?**

```
contribution_margin_user = plan_price − actual_api_cost_this_month(user)
```
- `plan_price`: $29 (Pro) / $99 (Business).
- `actual_api_cost_this_month(user)`: `CostLedger.month_cost(email)` — real, from `MODEL_PRICING`
  (Opus 4.8 $5/$25 per 1M in/out; Haiku 4.5 $1/$5; billed model = Haiku for the cap).
- **Margin is protected by design:** the ledger caps each plan's monthly API budget —
  **Pro $8.00**, **Business $28.00** (from `PLAN_API_BUDGET_USD`), throttling at **70%**.
  So the *floor* gross margin is **~$21 on Pro (72%)** and **~$71 on Business (72%)**.

**Daily read (already computed for you):** `/admin` → `net_margin_usd = revenue_usd − estimated_api_spend_usd`.
**Green:** blended gross margin **≥ 65%**. **Red:** any cohort dipping under 50% → tighten the cap or route more work to Haiku.

### Metric 2 — LTV : CAC (are we allowed to spend to grow?)

> **Every $1 of acquisition should return ≥ $3 of gross-margin lifetime value.**

```
ARPU            = MRR / paying_users
gross_margin%   = net_margin_usd / revenue_usd            // from /admin, real
avg_lifetime_mo = 1 / monthly_churn                        // see Metric 3
LTV             = ARPU × gross_margin% × avg_lifetime_mo
CAC             = (ad_spend + tool_spend + outreach_cost) / new_paying_users
LTV:CAC         = LTV / CAC          // target ≥ 3.0
```
- **Our structural advantage:** the Axis-1 Loop and Axis-2 LinkedIn engine are **near-zero paid CAC** (ARIA makes the content; outreach is founder time). Early CAC is dominated by *your hours*, not ad dollars — so LTV:CAC starts very high and only needs paid ads once organic saturates.
- **Green:** ≥ 3.0. **Red:** < 3.0 → fix activation/retention *before* buying traffic.

### Metric 3 — Net Revenue Retention & churn (the fundraise signal)

> **Do users stay and expand? This is the single number investors underwrite.**

```
logo_churn%   = cancelled_paying_users_this_month / paying_users_start_of_month
NRR           = (start_MRR + expansion − contraction − churn_MRR) / start_MRR
```
- **Leading indicator we already have:** `frozen_users` (burn-cap freezes) from `/admin` — a spike means heavy users are hitting limits and are *ripe for an upsell*, not churn.
- **Green:** monthly logo churn **< 5%**, NRR **≥ 100%** (expansion offsets churn). **Red:** churn > 7% → the product isn't sticky yet; do not scale spend, fix the core loop.

### The "when to raise capital" trigger table

Raise from strength, not desperation. Green-light a seed conversation when **all** hold for ~4–8 weeks:

| Signal | Raise-ready threshold |
|---|---|
| MRR trajectory | Consistent **week-over-week growth** (organic, not one-off) |
| Unit economics | Blended gross margin **≥ 65%** (Metric 1) |
| Efficiency | **LTV:CAC ≥ 3** (Metric 2), CAC payback < ~3 months |
| Retention | Logo churn **< 5%/mo**, **NRR ≥ 100%** (Metric 3) |
| Proof | A repeatable channel (Loop *or* LinkedIn) that reliably converts |

Until then, the same dashboard tells you exactly which lever is broken — and every number on it is **real or a labeled estimate**, never invented.

---

## The 30-day calendar (how the four axes interlock)

| Week | Loop (Axis 1) | LinkedIn (Axis 2) | Product Hunt (Axis 3) | Dashboard (Axis 4) |
|---|---|---|---|---|
| **W1 (Day 0–7)** | Turn on the daily mission; ship 1 video/day; establish the format that retains. | Build the 300-name list; start 15 connects/day; send first free-demo runs. | Create upcoming page; recruit launch list; produce PH assets *with ARIA*. | Wire `/admin` daily habit; baseline margin + activation. |
| **W2 (Day 8–14)** | Double down on the best-performing angle; start reposting winners. | Touch-2/Touch-3 rolling; book demo calls; first Pro/Business closes. | **Launch (mid-week).** Product-of-the-Day attack. Reply to every comment. | Watch signup spike → activation → first upgrades; check margin holds. |
| **W3 (Day 15–21)** | Feed PH feedback into new "build in public" content. | Scale to warm inbound from PH; convert agencies to Business. | Post-launch thank-you content; onboard every signup personally. | LTV:CAC first real read; identify the one winning channel. |
| **W4 (Day 22–30)** | Systematize: same asset → 3 platforms; test full-auto for the safest step. | Push to the North-star mix (Pro fills from Loop, Business from LinkedIn). | Turn the launch into an evergreen proof asset. | Churn/NRR read; check the raise-trigger table; decide scale-or-fix. |

**North-star (from GROWTH_PLAYBOOK.md):** ~**200 Pro + 50 Business ≈ $10K MRR**. This 30-day plan is the ignition — a repeatable channel + positive unit economics — not the finish line.

---

## Day-0 deploy checklist (must be green before any of the above)

- [ ] Deploy live on Fly, `/` and `/login` load; OAuth works.
- [ ] Stripe live keys set; a real test purchase flips the plan; `/legal/refund-policy` gate shows before checkout.
- [ ] `/admin/api/overview` returns real numbers; you can read margin daily.
- [ ] Support widget answers; missions enqueue → worker processes (see `SCALE_ARCH.md`).
- [ ] Connectors: connect at least LinkedIn (Axis 2) and one video platform (Axis 1) — or accept the manual-post gate until then.
- [ ] Bitly connected for link tracking; UTM scheme decided.

---

*Every claim here is either a real product capability, a real in-repo mechanism, or a **labeled estimate**. Replace estimates with measured results the moment the dashboard produces them.*
