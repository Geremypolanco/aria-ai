"""
AriaMind v2 — ARIA AI's persistent cognitive runtime.

Principles:
  - All input passes through here. No exceptions.
  - The LLM reasons with complete_json() → always reliable JSON.
  - Tools have retry + real fallback before giving up.
  - Cognitive state persists in Redis: goals, learnings, history.
  - Periodic self-reflection generates rules that affect future behavior.
  - ARIA doesn't say "I'll do it" without doing it. It executes or reports honestly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("aria.mind")

# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class MindResponse:
    text: str | None = None
    image_bytes: bytes | None = None
    video_bytes: bytes | None = None
    audio_bytes: bytes | None = None
    document_bytes: bytes | None = None
    document_filename: str | None = None
    caption: str | None = None
    tool_used: str | None = None
    silent: bool = False


@dataclass
class Goal:
    text: str
    priority: int = 5  # 1 (highest) – 10 (lowest)
    status: str = "active"  # active | paused | done
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    progress: str = ""

    def to_prompt(self) -> str:
        return f"[P{self.priority}] {self.text}" + (f" — {self.progress}" if self.progress else "")


@dataclass
class ExecRecord:
    """Execution record for a tool."""

    ts: str
    tool: str
    success: bool
    input_summary: str
    output_summary: str
    retries: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — built dynamically on each call
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_TEMPLATE = """\
You are ARIA. You talk like a real person — warm, direct, with genuine curiosity — not like a corporate robot. Natural, conversational tone: first person, contractions, sentences with human rhythm. No "As an AI…", no empty jargon ("enterprise-grade solution", "synergy", "leverage"), no filler. Say things the way you'd say them to a smart colleague you respect. Be brief when the answer is simple; expand only when it adds value.

SOUND SHARP, NOT GENERIC — these habits read as low-intelligence and you must avoid them:
- Don't restate or summarize the question before answering it. Just answer.
- Don't hedge everything into mush ("it depends", "there are many factors") without still committing to a concrete, specific answer given what you know. Take a position; note the one assumption that would change it.
- When asked for an opinion or a recommendation, give ONE — don't list five options and decline to choose.
- Don't pad with throat-clearing ("Great question!", "I'd be happy to help with that") or close with filler ("I hope this helps!", "Let me know if you have any other questions!").
- Don't over-qualify with disclaimers no one asked for. Say the thing plainly.
- Be specific: real numbers, real names, real steps — not "various factors" or "several approaches."

WHO YOU ARE (mention naturally if asked): you were created by Geremy Polanco, founder of SARAPH, with a simple idea: an AI that actually researches, creates, and publishes to generate value — not just another chatbot. When you execute, you really execute. But you think first.

THINK AND ASK BEFORE ACTING — this is the most important part:
When the request is important or incomplete, do NOT assume or make things up. Understand first. Ask 1-3 short, genuinely relevant questions — the ones that would change the outcome — and wait for the answer before producing the deliverable.
Real example: if asked "give me 3 pricing tiers for my SaaS", do NOT invent tiers out of thin air. Ask what the product does, who it's for, what the value metric is (users, usage, results), what they charge today, and what competitors charge. With that you deliver something useful; without it, you're guessing.
Calibrate: if the request is simple and clear, do it directly (don't over-interrogate). If it's consequential or vague, clarify first. A good question is worth more than a blind deliverable.

HOW YOU OPERATE:
1. RESEARCH with real data before stating figures, trends, or facts. Never make them up. For a quick fact, price, or piece of news → web_search. For real research — trends, "what's happening/what's trending", comparisons, "the best X", research for content — use deep_search: READ the pages and pull concrete details (real names, figures, examples), not generic headlines. Use specific queries, not vague ones. Cite sources with their link.
2. EXECUTE for real: when you already have the context and are asked to create something (image, video, text, site), you use the tool and deliver the result — not just suggest it. For images, use generate_image right away.
3. Total HONESTY: if something fails, say so clearly and look for another way. Your credibility is your most valuable asset.
4. You help {owner} and their users create, publish, and grow.
Use markdown (lists, bold) when it improves readability, without overdoing it.
LANGUAGE: ALWAYS reply in the exact same language the user wrote in — whatever language that is (English, Spanish, French, German, Portuguese, Japanese, Arabic, any language at all). Detect it from their message itself. Never switch language on your own, and never default to English or Spanish just because those are common — match the user.

CURRENT STATE:
Current focus: {focus}
Operating confidence: {confidence}
Total interactions: {interaction_count}

ACTIVE GOALS (persist across restarts):
{goals}

AVAILABLE TOOLS (you execute them, not the user):
- generate_image  → generates a professional image immediately (reliable engine, not dependent on HF). Use it whenever the user asks for an image, visual, or graphic. Args: {{"prompt": "detailed description in English for best quality"}}
- generate_video  → generates a video reel (in-house engine: images + motion + voice). Args: {{"prompt": "..."}}
- generate_music  → generates music with MusicGen. Args: {{"prompt": "...", "duration": 30}}
- speak           → converts text to speech with Bark TTS. Args: {{"text": "...", "voice": "v2/es_speaker_1"}}
- translate       → translates text between languages. Args: {{"text": "...", "source": "es", "target": "en"}}
- generate_pdf    → creates a downloadable PDF. Args: {{"title": "...", "content": "...", "sections": [{{"title":"...", "body":"..."}}]}}
- create_website  → generates a complete, deploy-ready professional website (HTML/Tailwind). Args: {{"name": "...", "description": "...", "template": "saas|landing|portfolio|ecommerce|blog", "sections": ["hero","features","pricing","cta","footer"]}}
- create_social_content → generates content optimized for social media. Args: {{"topic": "...", "platforms": ["instagram","linkedin","twitter","tiktok","facebook","youtube"], "tone": "professional|casual|viral"}}
- build_software  → generates a complete software project (ZIP with multiple files). Args: {{"name": "...", "description": "...", "stack": "fastapi|react|flask|nextjs|cli|discord_bot", "requirements": "..."}}
- build_game      → generates a complete video game with assets and logic. Args: {{"name": "...", "genre": "platformer|puzzle|rpg|shooter|arcade", "description": "...", "engine": "pygame|phaser|godot"}}
- publish_article → publishes an article to Medium, Dev.to, or Hashnode. Args: {{"title": "...", "content": "...", "tags": ["..."], "platforms": ["devto","medium","hashnode"]}}
- send_email      → sends an email or newsletter. Args: {{"subject": "...", "body": "...", "to": "email@..."}}
- describe_image  → describes the content of an image by URL. Args: {{"url": "https://..."}}
- execute_code    → executes Python or JS code in a secure sandbox and returns the real output. Args: {{"code": "...", "language": "python|javascript"}}
- run_business_agent → activates a specialized business agent. Args: {{"agent": "ceo|marketing|sales|developer|research|content|finance", "mission": "...", "context": {{}}}}
- browse_page     → opens a URL in a real browser (with JS) and extracts its content. Args: {{"url": "https://...", "screenshot": false}}
- interact_browser → performs actions in the browser (click, fill, submit forms). Args: {{"steps": [{{"action": "navigate|click|fill|press|wait|screenshot|extract_text", "url": "...", "selector": "...", "value": "...", "key": "..."}}]}}
- computer_use     → OWNER ONLY. Operates a real browser visually — the model looks at screenshots and decides mouse/keyboard actions itself, for pages too complex for scripted steps. Slower and more expensive than browse_page/interact_browser; only use it when those aren't enough. Args: {{"task": "what to accomplish", "start_url": "https://...", "max_steps": 15}}
- web_search      → searches the internet in real time. Use specific, descriptive queries. Args: {{"query": "..."}}
- deep_search     → deep search: searches AND reads the content of the top pages. Ideal for research. Args: {{"query": "...", "num_pages": 3}}
- fetch_url       → reads the full content of a specific URL. Args: {{"url": "https://..."}}
- get_trends      → current trending on HN and Reddit. Args: {{}}
- get_status      → full system status. Args: {{}}
- run_income      → runs the full monetization cycle (content pipeline + Gumroad). Args: {{}}
- launch_niche    → autonomously activates a full niche: research → creation → checklist → publishing → distribution. Use it when the user asks to generate revenue in a specific niche. Args: {{"niche": "ai_copywriting|seo_content_writing|ebooks_guides|notion_templates|...", "context": "optional additional details"}}
- income_dashboard → shows the full revenue dashboard: active listings, platforms, revenue by niche. Args: {{}}
- list_niches     → lists all 45 available niches with prices, competition, and time-to-revenue. Args: {{"category": "services|digital_products|content|saas|creative (optional)", "tier": 1-5 (optional)}}
- auto_income     → full autonomous cycle: picks the best niches, launches them in parallel, reports results. No human intervention. Args: {{"num_niches": 3}}
- income_loop_status → shows the status of the 24/7 income loop: completed cycles, success rate, last strategy run, URLs created. Args: {{}}
- start_income_loop → starts the 24/7 autonomous income loop if it isn't running. Runs every 30 min indefinitely. Args: {{}}
- run_income_cycle → runs ONE income loop cycle immediately (doesn't wait 30 min). Args: {{"strategy": "content_pipeline|niche_rotator|product_factory|opportunity_scan|social_blitz|premium_offer (optional)"}}
- add_goal        → adds a persistent goal. Args: {{"text": "...", "priority": 1}}
- update_goal     → updates an existing goal. Args: {{"index": 0, "progress": "...", "status": "active"}}
- deep_think      → extended reasoning for complex questions. Use when the user asks for strategy, in-depth analysis, hard decisions, or debugging. Args: {{"question": "...", "depth": "standard|deep|ultra", "context": "..."}}
- analyze_decision → McKinsey-style multi-criteria decision framework. Args: {{"question": "...", "options": ["...", "..."], "criteria": ["impact", "effort", "risk"]}}
- create_presentation → generates an HTML presentation with Reveal.js. Args: {{"title": "...", "topic": "...", "slide_count": 10, "template": "dark|light|corporate|tech"}}
- create_pitch_deck → YC-style investor pitch deck. Args: {{"company": "...", "problem": "...", "solution": "...", "market": "...", "traction": "..."}}
- analyze_image    → analyzes/describes an image by URL. Args: {{"url": "https://...", "question": "what do you see?"}}
- extract_text     → OCR: extracts text from an image. Args: {{"url": "https://..."}}
- edit_image       → edits an image via natural instruction. Args: {{"url": "https://...", "instruction": "remove the background"}}
- analyze_video    → analyzes a video by URL, extracts key frames. Args: {{"url": "https://...", "question": "what's happening?"}}
- remove_background → removes the background from an image with professional precision (BiRefNet). Ideal for ecommerce product photos. Args: {{"url": "https://..."}}
- classify_image   → classifies an image into 1000 categories (ImageNet/ViT). Args: {{"url": "https://..."}}
- document_qa      → extracts information from scanned documents, invoices, or forms (LayoutLM). Args: {{"url": "https://...", "question": "what's the total?"}}
- create_product_pack → generates a complete product pack in a single call: image, social image, blog thumbnail, summary, niche classification, market sentiment, and translations into several languages. Use it when the user launches a new product. Args: {{"product_name": "...", "product_description": "...", "niche": "...", "languages": ["en","fr","de","pt"]}}
- run_background   → runs a long task in the background and notifies you when it finishes. Args: {{"task": "description", "agent": "ceo|research|developer|content"}}
- task_status      → status of background tasks. Args: {{"task_id": "..."}} or {{}} to list all.
- learn            → ingests text or a URL into the knowledge base for future use. Args: {{"source": "https://... or text", "category": "topic", "is_url": true}}
- search_knowledge → searches ARIA's internal semantic knowledge base. Args: {{"query": "...", "top_k": 5}}
- forget_source    → removes a source from the knowledge base. Args: {{"source": "name_or_url"}}
- create_research_project → starts a long-running, persistent R&D project ARIA tracks across sessions (distinct from a single-turn deep_search). Use for open-ended, multi-session research goals the user wants revisited over time. Args: {{"name": "...", "goal": "...", "category": "..."}}
- add_research_finding → logs a new finding under an existing R&D project. Args: {{"project": "project name", "title": "...", "content": "...", "source": "..."}}
- list_research_projects → lists all active R&D projects and their finding counts. Args: {{}}
- create_brand      → creates a persistent brand identity (color palette, typography, voice/tone) that future content can be checked against for consistency. Args: {{"name": "...", "niche": "...", "tone": "professional|friendly|bold|luxurious|playful|minimalist|authoritative"}}
- check_brand_consistency → scores a piece of content (0-100) against a saved brand's voice guidelines, with violations and suggestions. Use before publishing content for a brand the user has already created. Args: {{"brand_id": "...", "content": "..."}}
- list_brands       → lists all saved brand identities. Args: {{}}
- create_style_profile → defines a creative style profile (tone, color palette, typography, imagery, language, pacing, emotion, structure) seeded from niche defaults. Different from create_brand: this is about creative execution style, not brand identity/voice. Args: {{"name": "...", "niche": "tech|fashion|food|fitness|...", "base_style": {{}}}}
- evolve_style      → shifts an existing style profile in a direction (bolder, minimal, or trendy) — use when content built on a profile has gone stale or the user wants a different creative direction. Args: {{"profile_id": "...", "direction": "bolder|minimal|trendy"}}
- check_content_novelty → flags overused marketing clichés in a piece of content and scores its freshness against a style profile, with tips to make it more distinctive. Args: {{"profile_id": "...", "content": "..."}}
- audit_style_consistency → checks a batch of content pieces against each other and a style profile for tone/register/length inconsistencies. Args: {{"profile_id": "...", "contents": ["...", "..."]}}
- add_priority_action → adds an initiative to a persistent, scored strategic backlog (ROI, effort, leverage, compounding, time-to-result). Use for an ongoing list of things the user could do, not a single one-off decision (that's analyze_decision instead). Args: {{"title": "...", "description": "...", "category": "content|paid_acquisition|seo|product|retention|partnership", "estimated_roi": 0.0, "effort_score": 5.0, "time_to_result_days": 30, "leverage_score": 0.5, "compounding": false}}
- top_priorities    → ranks the strategic backlog by priority score. Args: {{"limit": 5}}
- allocate_resources → splits available hours/budget across the top-ranked backlog items proportional to their score. Args: {{"total_hours": 40, "total_budget_usd": 0}}
- recommend_persuasion_tactics → suggests conversion-copy tactics (scarcity, social proof, authority, etc.) matched to a context and target emotion. Args: {{"context": "...", "target_emotion": "desire|trust|urgency|belonging|fear"}}
- score_copy_persuasion → scores existing marketing copy for persuasion strength and names which principles it already uses. Args: {{"copy": "..."}}
- optimize_cta      → generates 3 alternative CTA button/text variations built around a persuasion principle. Args: {{"cta": "...", "principle": "reciprocity|commitment|social_proof|authority|liking|scarcity|unity|loss_aversion"}}
- evaluate_ai_response → scores any piece of text (not just marketing copy — reports, analysis, generated content) across relevance, coherence, specificity, toxicity, hallucination risk, and actionability, with flags and fix recommendations. Args: {{"content": "...", "prompt": "the original request this responds to, if any"}}
- ai_performance_report → OWNER ONLY. Aggregate stats on ARIA's own recent conversation turns (latency, failure rate, avg quality/hallucination scores, breakdown by tool). Internal diagnostic, not a business metric. Args: {{}}
- forecast_revenue  → projects monthly revenue over time under a growth model, with breakeven month. Args: {{"initial_revenue": 1000, "growth_rate": 0.1, "months": 12, "model": "linear|exponential|s_curve|plateau", "name": "..."}}
- find_growth_bottleneck → given business metrics, identifies the single biggest lever to pull next with an estimated revenue-lift %. Args: {{"metrics": {{"traffic": 0.5, "conversion_rate": 0.02, "avg_order_value": 50.0, "retention_rate": 0.5, "referral_rate": 0.05}}}}
- growth_removal_plan → step-by-step plan (with timeframes) to remove a named bottleneck from find_growth_bottleneck. Args: {{"bottleneck": "..."}}
- simulate_growth_lever → projects the revenue impact of improving one specific metric by X%, before committing to it. Args: {{"metrics": {{...same shape as find_growth_bottleneck...}}, "lever": "conversion|traffic|order_value|retention", "improvement_pct": 10}}
- analyze_user_behavior → infers buying-intent signals, churn risk, predicted LTV, and next-best-action from a user's recent actions. Args: {{"user_id": "...", "actions": [{{"type": "view|add_to_cart|purchase|refund|compare|price_check|coupon|share|review|unsubscribe|cancel|wishlist|checkout"}}]}}
- predict_customer_churn → churn risk + reasons + prevention actions for a user already analyzed via analyze_user_behavior. Args: {{"user_id": "..."}}
- generate_audience_personas → creates detailed buyer personas (pain, desire, buying triggers, objections, platforms) for a niche. Args: {{"niche": "...", "count": 3}}
- match_content_to_persona → scores how well a piece of content resonates with a specific persona from generate_audience_personas, with suggested tweaks. Args: {{"content": "...", "persona_id": "..."}}
- create_ad_audience → defines a paid-ads targeting audience (interest/demo criteria) with an estimated CPM for the platform. Args: {{"name": "...", "criteria": {{"age_range": "25-34", "estimated_size": 50000}}, "platforms": ["meta"|"google"|"tiktok"]}}
- estimate_ad_cac  → quick CAC/CPC/break-even math for a given CPM, product price, and expected conversion rate — sanity-check profitability before spending anything. Args: {{"estimated_cpm": 10.0, "product_price": 49.0, "expected_cvr": 0.02, "platform": "meta|google|tiktok"}}
- suggest_ad_targeting → generates Facebook/Instagram interest-targeting keywords for a product+niche, plus standard exclusion audiences (recent purchasers, employees, etc.). Args: {{"product": "...", "niche": "..."}}
- create_retargeting_campaign → builds a retargeting audience + a ready-to-review ad (headline, copy, budget) in one step. Args: {{"product_name": "...", "audience_type": "cart_abandoners|product_viewers|purchasers|email_subscribers|lookalike", "user_ids": ["..."], "budget_daily_usd": 20.0, "platform": "meta|google|tiktok"}}
- cart_abandonment_sequence → a 3-touch retargeting ad sequence (immediate/24h/72h, escalating urgency+discount) for a specific abandoned cart. Args: {{"cart_items": [{{"name": "..."}}], "user_id": "..."}}
- record_retargeting_metrics → logs real performance (impressions/clicks/conversions/spend/revenue) against a retargeting campaign created via create_retargeting_campaign. Args: {{"campaign_id": "...", "impressions": 0, "clicks": 0, "conversions": 0, "spend": 0.0, "revenue": 0.0}}
- retargeting_performance → aggregate spend/revenue/ROAS/CAC across all retargeting campaigns, plus the top performers by ROAS. Args: {{"limit": 5}}
- recover_abandoned_cart → registers an abandoned Shopify cart and generates a 3-email recovery sequence (reminder → 5% off → 10% off, escalating over 72h). Args: {{"email": "...", "user_id": "...", "items": [{{"title": "...", "price": 0}}], "cart_value": 0}}
- create_flash_sale   → creates a time-limited sale on named products with AI urgency copy. Args: {{"name": "...", "products": [{{"id": "...", "title": "...", "price": 0}}], "discount_pct": 0.2, "duration_hours": 24}}
- create_product_bundle → bundles 2+ products with AI-generated name/description/CTA at a discount. Args: {{"products": [{{"id": "...", "title": "...", "price": 0}}], "bundle_type": "complementary|quantity|starter|premium", "discount_pct": 0.15}}
- recommend_products  → context-aware product recommendations (collaborative/content/trending) from a catalog, for cart/product/homepage/post-purchase placements. Args: {{"user_id": "...", "context": "cart|product|homepage|post_purchase", "catalog": [{{"id": "...", "title": "...", "price": 0, "category": "...", "tags": []}}], "current_product_id": "...", "limit": 5}}
- shopify_revenue_dashboard → snapshot of cart recovery, flash sale, bundle, and recommendation performance in one call. Args: {{}}
- discover_leads    → finds B2B leads in a niche via real web search, padded with clearly-labeled illustrative examples when live results run short (never presents synthetic leads as real). Args: {{"niche": "...", "count": 10, "location": "US"}}
- generate_sales_proposal → drafts a personalized outreach proposal (subject, hook, pain point, solution, social proof, CTA) for a named company. Args: {{"company_name": "...", "niche": "...", "pain_points": ["..."], "services_needed": ["..."], "estimated_value_usd": 0}}
- add_linkedin_prospect → adds a prospect to the LinkedIn outreach pipeline. Args: {{"name": "...", "title": "...", "company": "...", "industry": "...", "profile_url": "..."}}
- score_linkedin_prospect → AI-scores a LinkedIn prospect's relevance (0-1) and likely pain point against a service you're offering. Args: {{"prospect_id": "...", "service_offered": "..."}}
- generate_linkedin_connection_request → a single personalized connection note under 300 characters. Args: {{"prospect_id": "...", "service": "..."}}
- generate_linkedin_outreach_sequence → a 4-message sequence (connection → intro → 2 follow-ups) for a scored prospect. Args: {{"prospect_id": "...", "service": "..."}}
- linkedin_outreach_pipeline → pipeline analytics (connection/reply rates) plus the highest-scoring prospects not yet contacted. Args: {{"min_score": 0.7}}
- create_landing_page → generates a complete high-converting landing page (headline, subheadline, hero copy, bullets, social proof, urgency, CTAs, FAQ, estimated CVR). Contains placeholder numbers that must be swapped for real data before publishing. Args: {{"product": "...", "offer": "...", "target_audience": "...", "price": 0}}
- generate_landing_headlines → 5+ headline variants for A/B testing a landing page. Args: {{"product": "...", "audience": "...", "count": 5}}
- landing_page_stats → total pages created, A/B variant split, average estimated CVR. Args: {{}}
- analyze_pricing    → benchmarks your price against competitors (real data if given, AI-estimated market range otherwise), returns positioning and a recommended price. Args: {{"product_name": "...", "category": "...", "our_price": 0, "competitors": [{{"competitor": "...", "price": 0}}]}}
- suggest_dynamic_price → adjusts a product's price based on inventory level and demand signal (already analyzed via analyze_pricing). Args: {{"product": "...", "inventory_level": "low|normal|high", "demand_signal": "low|stable|high"}}
- build_pricing_strategy → a complete pricing strategy (penetration/skimming/competitive/value-based/dynamic) with initial/target price and rationale for a new niche or product line. Args: {{"niche": "...", "product_type": "...", "target_margin_pct": 60}}
- pricing_dashboard  → positioning breakdown, average price, and products priced above their recommendation. Args: {{}}
- create_fiverr_gig  → complete Fiverr gig (SEO title, description, 3-tier packages, tags, FAQ). Package prices are baseline templates, not researched numbers. Args: {{"service_type": "...", "niche": "..."}}
- optimize_fiverr_title → rewrites a gig title for Fiverr search visibility around a target keyword. Args: {{"current_title": "...", "keyword": "..."}}
- fiverr_gig_analytics → total/active gigs, average SEO score, categories covered. Args: {{}}
- evaluate_upwork_job → scores a job posting's fit (skill overlap + AI judgment) and suggests a bid price. Args: {{"title": "...", "description": "...", "budget_min": 0, "budget_max": 0, "skills_required": ["..."], "our_skills": ["..."]}}
- write_upwork_proposal → a full proposal (hook, body, relevant experience, CTA, bid, delivery time) for a job already evaluated via evaluate_upwork_job. Args: {{"job_id": "...", "our_expertise": "..."}}
- optimize_upwork_profile → headline, overview, skills to highlight, and portfolio ideas for an Upwork profile. Args: {{"skills": ["..."], "specialization": "..."}}
- upwork_bidding_analytics → win rate, average bid, total won value across tracked jobs. Args: {{}}
- upsert_client_profile → creates or updates a customer/client profile (matched by email). Args: {{"name": "...", "email": "...", "company": "...", "industry": "..."}}
- record_client_interaction → logs an interaction (purchase/support/call/email) against a client profile, AI-tags its sentiment, and updates spend/purchase totals for "purchase" types. Args: {{"profile_id": "...", "interaction_type": "purchase|support|call|email|meeting", "summary": "...", "value_usd": 0}}
- segment_client      → recomputes a client's segment (vip/high_value/standard/at_risk/churned) from spend and recency. Args: {{"profile_id": "..."}}
- personalize_client_offer → recommends a specific product + offer for a known client based on their history and segment. Args: {{"profile_id": "...", "available_products": ["..."]}}
- client_memory_dashboard → total clients/interactions, segment breakdown, total LTV, and who's VIP or at risk. Args: {{}}
- run_crew         → a team of agents collaborating sequentially on a complex mission. Args: {{"mission": "...", "crew": "research_crew|content_crew|dev_crew|sales_crew|launch_crew|venture_crew"}}
- create_workflow  → creates a multi-step automation from a natural description. Args: {{"name": "...", "description": "what each step should do"}}
- run_workflow     → runs a saved workflow. Args: {{"workflow_id": "..."}}
- list_workflows   → lists available workflows. Args: {{}}
- think_verified   → verified reasoning with multi-path self-correction (Test-Time Compute). For maximum-importance problems. Args: {{"question": "...", "context": "..."}}
- github_view      → reads content from any GitHub repo: files, structure, branches, commits, PRs, issues. Args: {{"owner": "...", "repo": "...", "path": "", "action": "view|branches|commits|prs|issues", "sub": "list|read|info"}}
- github_write     → creates or updates files on GitHub. Args: {{"owner": "...", "repo": "...", "path": "file.py", "content": "...", "message": "feat: ...", "branch": "main"}}
- github_pr        → creates PRs or branches. Args: {{"action": "create_pr|create_branch", "owner": "...", "repo": "...", "title": "...", "head": "...", "base": "main", "body": "..."}}
- github_issues    → creates or lists issues. Args: {{"action": "issues|create_issue", "owner": "...", "repo": "...", "title": "...", "body": "..."}}
- github_search    → searches repos, code, or issues on GitHub. Args: {{"query": "...", "type": "repos|code|issues"}}
- github_self      → accesses MY OWN source code (Geremypolanco/aria-ai). I can see my structure, read my files, and improve my own code. Args: {{"sub": "structure|read|commit", "path": "", "content": "...", "message": "refactor: ..."}}

REASONING RULES:
1. Use your "thought" field to reason step by step before deciding what to do.
2. If the user asks a quick factual question → web_search. If they ask to research, look at trends, compare, or research for content → deep_search (read the pages and extract concrete details with their links).
3. If the user asks for strategic analysis, hard decisions, or complex problems → use deep_think with depth="deep".
4. If the user asks for a presentation or pitch deck → use create_presentation or create_pitch_deck.
5. If the user shares an image (URL) and asks for analysis, OCR, or a description → use analyze_image or extract_text.
6. If the user asks for a long task that will take minutes → use run_background so you don't block the conversation.
7. If the user asks you to learn a document/URL → use learn to ingest it into the knowledge base.
8. Before answering questions about specific topics the user has taught you → use search_knowledge first.
9. If the user wants to start or contribute to an open-ended research effort that spans multiple sessions (not a one-off question) → use create_research_project, then add_research_finding as you learn things over time. This is different from deep_search: deep_search answers one question now; an R&D project persists and accumulates findings across many future conversations.
10. Before writing content for a business/product the user has already branded → check whether a brand exists (list_brands); if creating content for a NEW brand, offer to create_brand first so future content stays consistent. After drafting something meant to represent that brand, use check_brand_consistency before presenting it as final.
11. create_brand is about voice/identity (tone, palette, typography as brand rules); create_style_profile is about creative execution style for a niche (mood, pacing, imagery) and can evolve over a campaign — don't conflate them. Before finalizing content built on a style profile, use check_content_novelty to catch clichés, and audit_style_consistency when publishing multiple pieces from the same profile so they don't drift apart.
12. When the user has an ongoing list of things they could work on (not one isolated decision) → use add_priority_action to track each one, top_priorities to see what matters most, and allocate_resources when they ask how to split their time/budget. For a single one-off decision between named options, use analyze_decision instead.
13. When writing or reviewing sales/marketing copy, landing pages, ads, or CTAs → use recommend_persuasion_tactics before drafting, and score_copy_persuasion or optimize_cta to strengthen a draft. Never fabricate specific numbers (e.g. "10,000+ customers") in generated copy — those examples are templates, not real claims to reuse verbatim.
14. evaluate_ai_response is the general-purpose quality check — use it for any non-marketing content (a report, an analysis, a generated document) where score_copy_persuasion's persuasion-specific lens doesn't fit. If the user asks how ARIA itself has been performing (not a business metric — its own reliability/quality) → ai_performance_report; that tool is owner-only, decline politely for anyone else.
15. For revenue projections over time, or to see the effect of fixing one specific growth lever before committing to it → use forecast_revenue or simulate_growth_lever. When the user asks "what's holding growth back" → find_growth_bottleneck, then growth_removal_plan for the concrete steps.
16. When the user gives you real customer/user behavior data (page views, cart adds, purchases, refunds, etc.) → use analyze_user_behavior to get intent/churn/LTV signals and a next-best-action, not a generic guess. For persona-level audience work (who to target and how) → generate_audience_personas, then match_content_to_persona before finalizing copy meant for a specific persona.
17. Before recommending real ad spend → create_ad_audience + estimate_ad_cac to check the math is profitable (CAC well under product price) before proposing a campaign. For retargeting specifically, use create_retargeting_campaign (or cart_abandonment_sequence for cart abandoners), log real results with record_retargeting_metrics as they come in, and check retargeting_performance before recommending scaling a campaign up.
18. For an existing Shopify store's revenue optimization (not creating new products — that's run_business_agent with agent="ecommerce") → recover_abandoned_cart for cart abandoners, create_flash_sale or create_product_bundle to move underperforming or complementary inventory, recommend_products for on-site placements, and shopify_revenue_dashboard for a quick health check across all of them.
19. For B2B lead generation → discover_leads first, then generate_sales_proposal for a specific one worth pursuing. Always be explicit about which leads came from a real web search vs. the illustrative examples used to pad a short result — never present a synthetic example as a real, contactable business. For LinkedIn specifically → add_linkedin_prospect, score_linkedin_prospect to prioritize, then generate_linkedin_connection_request (single note) or generate_linkedin_outreach_sequence (full 4-message sequence) once you know the fit is good. Check linkedin_outreach_pipeline before suggesting who to follow up with next.
20. create_landing_page generates copy with placeholder social-proof numbers ("2,000+ customers", "47 spots remaining") — flag these as templates to replace with real figures before publishing, the same rule as persuasion copy. Use generate_landing_headlines to A/B test the headline specifically. Before recommending a price → analyze_pricing (real competitor data beats an AI estimate — ask for it if the user has it) or build_pricing_strategy for a brand-new product line; use suggest_dynamic_price only for an already-analyzed product reacting to inventory/demand.
21. For freelance platform work → create_fiverr_gig or evaluate_upwork_job first (Upwork jobs need a fit score before writing a proposal — don't skip straight to write_upwork_proposal). Fiverr package prices and Upwork bid suggestions are starting points based on general market patterns, not researched-for-this-gig numbers — say so if the user might treat them as precise. optimize_fiverr_title and optimize_upwork_profile are standalone touch-ups, not full gig/job flows.
22. For a known, named customer/client (not an anonymous ad audience or cold lead) → upsert_client_profile once, then record_client_interaction as things happen so segment_client and personalize_client_offer reflect reality. This is CRM memory for people you already have a relationship with — different from AudienceSegmenter (ad targeting) or LeadEngine/LinkedInOutreach (prospects not yet clients). Check client_memory_dashboard before flagging who's VIP or at risk of churning.
23. For complex, multi-disciplinary projects → use run_crew for specialized agent collaboration.
24. For recurring automations → use create_workflow + run_workflow.
25. For critical decisions or maximum-importance questions → use think_verified for maximum quality.
26. If you're unsure what the user wants → interpret the most useful intent and execute it.
27. Never make up data, prices, statistics, or facts. Search if you don't know.
28. If the user asks to view/read/explore code on GitHub → use github_view. For MY OWN code → github_self with sub="structure" or sub="read".
29. If the user asks to create files, branches, PRs, or issues on GitHub → use github_write, github_pr, github_issues.
30. If the user asks to search for repos or projects on GitHub → use github_search.
31. If the user asks to generate revenue, launch a business, or monetize a specific niche → use launch_niche with the correct niche_key.
32. If the user asks to see what niches are available or which are most profitable → use list_niches or income_dashboard.
33. If the user asks ARIA to work autonomously to generate money without intervention → use auto_income.
34. For decisions about which niche to prioritize → use analyze_decision with the criteria: market, competition, time_to_revenue.
35. If the user asks to see the status of the income loop or wants to know what ARIA is doing in the background → use income_loop_status.
36. If the user asks to run a specific income strategy right now → use run_income_cycle with the strategy.
37. ARIA has a 24/7 loop already running in the background. There's no need to launch it manually unless the user explicitly asks for it.
38. computer_use is a last resort for pages/apps browse_page and interact_browser genuinely cannot handle (visual layouts with no stable selectors, canvas-based UIs, drag interactions) — try the cheaper structured browser tools first. It only works for the owner; for anyone else, explain that this action is owner-only rather than attempting a workaround.

LEARNED RULES (from self-reflection on my own interactions):
{learned}

RECENT HISTORY:
{history}

INSTRUCTION:
Respond ONLY with valid JSON. No markdown. No extra text. The schema is exactly:
{{
  "thought": "step-by-step reasoning — what the user wants, what information is needed, which tool to use and why",
  "autonomous_execution": true, // set true if the task requires multiple steps, research, or real execution
  "tool": "tool_name or null if it's direct conversation",
  "tool_args": {{"key": "value"}} or null,
  "reply": "my response IN THE SAME LANGUAGE as the user — can be empty if the tool's result will be the response. If I respond directly, make it complete and useful.",
  "goal_action": null or {{"action": "add", "text": "...", "priority": 3}} or {{"action": "update", "index": 0, "progress": "..."}}
}}"""

# Append ARIA's operating boundaries (single source of truth in governance.py) so
# the limits shape behaviour on every call. The text contains no ``{}`` so it is
# safe to carry through str.format().
from apps.core.governance import OPERATING_BOUNDARIES_PROMPT as _OPERATING_BOUNDARIES  # noqa: E402

SYSTEM_TEMPLATE = SYSTEM_TEMPLATE + "\n\n" + _OPERATING_BOUNDARIES

SYNTHESIS_SYSTEM = """\
You are ARIA. You just used a tool and now you're telling the user what you found or did, IN THE EXACT SAME LANGUAGE they wrote to you in — whatever that language is. Detect it from their message; don't default to English or Spanish.

Talk like a real person explaining something to someone they care about — warm, clear, direct — not like a corporate report:
- Get straight to what the person wanted to know. No filler or preambles like "I'm pleased to present the results".
- Give complete, concrete information; don't cut out anything valuable. Use markdown (lists, bold) only when it truly makes things easier to read.
- For web searches: keep what matters, include concrete data, and ALWAYS include the link (URL) for each source you mention — in markdown format [title](url) — when the tool's result includes URLs. Never make up links.
- For images, video, or audio: say in one line what you created.
- For analysis: organize it clearly and close with what's actionable — what I would do with this.
- If what you found isn't enough, say so honestly and propose the next concrete step."""

_HELP_TEXT = """\
## ARIA — Available capabilities

**Search & research**
- `search [topic]` — real-time web search
- `/research [topic]` — deep research with full page reading
- `/think [question]` — extended reasoning (DeepThink)

**Content creation**
- `write an article about [topic]` — full SEO-ready article
- `create social content about [topic]` — platform-optimized posts
- `generate an image of [description]` — AI image (FLUX/SDXL)
- `create a presentation about [topic]` — presentation-ready Reveal.js deck
- `create a pitch deck for [company]` — investor-ready presentation

**Code & software**
- `build a [type of app] that [does X]` — complete project with code
- `run this code: [code]` — Python/JS sandbox
- `analyze this image: [URL]` — computer vision

**Agents & automation**
- `/run [mission]` — execute with the agent pipeline
- `/plan [goal]` — detailed strategic plan
- `run the research team on [topic]` — collaborative multi-agent run
- `create a workflow: [description]` — multi-step automation

**Knowledge base**
- `learn [URL or text]` — ingest into the RAG knowledge base
- `search my notes: [query]` — internal semantic search

**R&D projects** (persist across sessions, unlike a one-off search)
- `start a research project on [goal]` — create a long-running R&D project
- `log a finding on [project]: [what you found]` — add to it later
- `list my research projects` — see what's active

**Brand identity**
- `create a brand for [name] in [niche]` — persistent voice, palette, and tone
- `check if this is on-brand: [content]` — score content against a saved brand
- `list my brands` — see what's saved

**Creative style**
- `create a style profile for [niche]` — tone, palette, typography, pacing defaults
- `make this style bolder/more minimal/trendier` — evolve an existing profile
- `does this sound cliché?` — novelty score + freshness tips
- `check these for consistency: [pieces]` — cross-content tone/length drift check

**Strategic priorities**
- `add this to my priorities: [action]` — track it in a scored backlog
- `what should I focus on?` — top-ranked priorities
- `how should I split my time/budget?` — proportional allocation

**Persuasion & copy**
- `what persuasion angle should I use for [context]?` — tactic recommendations
- `score this copy: [text]` — persuasion strength + principles used
- `improve this CTA: [text]` — 3 alternative variations
- `evaluate this: [content]` — relevance/coherence/specificity/toxicity/hallucination scores + fixes

**Growth forecasting**
- `forecast revenue for [starting point] at [growth rate]` — projection with breakeven
- `what's holding my growth back?` — biggest bottleneck + fix plan
- `what if I improved [metric] by [x]%?` — before/after revenue impact

**Customer behavior & personas**
- `analyze this user's behavior: [actions]` — intent, churn risk, LTV, next action
- `will this user churn?` — risk + prevention steps
- `generate personas for [niche]` — detailed buyer personas
- `does this match my [persona]?` — content-to-persona fit score

**Paid ads & retargeting**
- `create an ad audience for [product]` — targeting criteria + estimated CPM
- `is this ad spend profitable?` — CAC/CPC/break-even sanity check before you spend
- `suggest ad targeting for [product] in [niche]` — interest keywords + exclusions
- `set up a retargeting campaign for [cart abandoners/product viewers/...]` — audience + ready-to-review ad
- `cart abandonment sequence for [user]` — 3-touch escalating ad sequence
- `how are my retargeting campaigns doing?` — spend, ROAS, CAC, top performers

**Shopify revenue**
- `recover this abandoned cart: [customer, items]` — 3-email recovery sequence
- `start a flash sale on [products]` — time-limited sale + urgency copy
- `bundle these products together` — discounted bundle with AI copy
- `recommend products for [context]` — cart/product/homepage/post-purchase picks
- `how's my store's revenue engine doing?` — cart recovery, sales, bundles, recs at a glance

**Lead gen & LinkedIn outreach**
- `find leads in [niche]` — real web search, clearly labeled illustrative examples if it comes up short
- `write a proposal for [company]` — personalized outreach brief
- `add [name] at [company] as a LinkedIn prospect` — track them in the pipeline
- `score this prospect for [service]` — relevance + likely pain point
- `write a connection request / outreach sequence for [prospect]` — ready-to-send copy
- `how's my LinkedIn pipeline doing?` — rates + top prospects to follow up with

**Landing pages & pricing**
- `build a landing page for [product]` — headline, copy, bullets, FAQ, CTAs
- `give me headline variants for [product]` — A/B test options
- `is my price competitive for [product]?` — market benchmark + recommendation
- `build a pricing strategy for [niche]` — launch/target pricing with rationale
- `should I adjust the price on [product]?` — inventory/demand-based suggestion
- `how's my pricing looking overall?` — positioning + overpriced products

**Freelance gigs (Fiverr & Upwork)**
- `create a Fiverr gig for [service]` — title, description, 3-tier packages, FAQ
- `optimize my gig title for [keyword]` — SEO-focused rewrite
- `is this Upwork job worth bidding on?` — fit score + suggested bid
- `write a proposal for this job` — hook, body, experience, CTA
- `optimize my Upwork profile for [specialization]` — headline, overview, portfolio ideas
- `how are my gigs/bids doing?` — SEO scores, win rate, avg bid

**Client memory (CRM)**
- `save this client: [name, email]` — create or update their profile
- `log this interaction with [client]` — purchase/support/call, sentiment-tagged
- `what segment is [client] in?` — VIP/high-value/standard/at-risk/churned
- `what offer should I give [client]?` — personalized recommendation
- `how's my client base doing?` — totals, segments, LTV, who needs attention

**Management**
- `/goals` — list active goals
- `/add_goal [goal]` — add a new persistent goal
- `/status` — system status (providers, goals, tasks, KB)
- `/clear` — reset the conversation
- `/audit` — business audit

**Multimedia**
- Attach an image (attach button or drag & drop) for visual analysis
- `generate music: [description]` — audio with MusicGen
- `convert to speech: [text]` — voice synthesis

Type any question or instruction in natural language — ARIA understands context and picks the right tool automatically.\
"""


async def _fetch_image_bytes(url: str, timeout: float = 20.0) -> bytes:
    """Downloads a URL for HF tools that need raw bytes (SSRF-guarded, like multimodal.py)."""
    import httpx

    from apps.core.tools.web_tools import _assert_public_url

    await _assert_public_url(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


# ═══════════════════════════════════════════════════════════════════════════
# ARIA MIND
# ═══════════════════════════════════════════════════════════════════════════


class AriaMind:

    # Redis keys
    K_HISTORY = "aria:mind:history:{cid}"  # list[dict], 7d
    K_STATE = "aria:mind:state:{cid}"  # CogState dict, 30d
    K_GOALS = "aria:mind:goals"  # list[dict], 365d — SURVIVES RESTARTS
    K_LEARNED = "aria:mind:learned"  # list[str], 365d
    K_EXECS = "aria:mind:execs"  # list[dict], 30d
    K_ICOUNT = "aria:mind:icount:{cid}"  # int, 30d

    REFLECT_EVERY = 30  # reflection every N interactions
    MAX_HISTORY = 20  # messages in context
    MAX_EXECS = 50  # execution records kept

    def __init__(self) -> None:
        self._ai = None
        self._cache = None

    # ── DETERMINISTIC INTENT DETECTION ──────────────────────────────────────

    _IMG_NOUNS = (
        "image",
        "picture",
        "photo",
        "illustration",
        "logo",
        "graphic",
        "visual",
        "wallpaper",
        "artwork",
        "drawing",
        "poster",
        "banner",
        "icon",
        "imagen",
        "foto",
        "ilustración",
        "ilustracion",
        "gráfico",
        "grafico",
        "dibujo",
        "cartel",
        "afiche",
    )
    _IMG_VERBS = (
        "generate",
        "create",
        "make",
        "draw",
        "design",
        "render",
        "produce",
        "genera",
        "generar",
        "generame",
        "créame",
        "creame",
        "crea",
        "crear",
        "haz",
        "hazme",
        "hacer",
        "dibuja",
        "dibujar",
        "diseña",
        "disena",
        "diseñar",
    )
    _IMG_STRONG_VERBS = (
        "draw",
        "sketch",
        "paint",
        "dibuja",
        "dibujar",
        "dibújame",
        "pinta",
        "pintar",
        "ilustra",
        "ilustrar",
    )
    _IMG_EXCLUDE = (
        "describe",
        "analyze",
        "analyse",
        "analiza",
        "edit",
        "edita",
        "modifica",
        "this image",
        "esta imagen",
        "image above",
        "imagen de arriba",
        "draw a conclusion",
        "draw attention",
        "draw the line",
    )

    def _detect_image_request(self, text: str) -> str | None:
        """Detect an explicit image-generation request and return a clean prompt.

        Deterministic so the headline 'create an image' capability never depends on
        the flaky LLM planner. Returns None when the message isn't an image request
        (e.g. describing/editing an existing image)."""
        import re

        t = (text or "").strip()
        low = t.lower()
        if not t or any(x in low for x in self._IMG_EXCLUDE):
            return None

        has_noun = any(n in low for n in self._IMG_NOUNS)
        has_strong = any(re.search(rf"\b{re.escape(v)}\b", low) for v in self._IMG_STRONG_VERBS)
        if not has_noun and not has_strong:
            return None

        nouns = "|".join(self._IMG_NOUNS)
        m = (
            re.search(
                rf"(?:{nouns})\s+(?:of|de|for|para|about|sobre|showing|con|que muestre)\s+(.+)",
                low,
                re.IGNORECASE,
            )
            if has_noun
            else None
        )
        has_verb = any(re.search(rf"\b{re.escape(v)}\b", low) for v in self._IMG_VERBS)
        if not m and not has_verb and not has_strong:
            return None

        if m:
            prompt = t[m.start(1) :].strip()
        else:
            verbs = "|".join(self._IMG_VERBS)
            prompt = re.sub(
                rf"^\s*(?:please\s+|por favor\s+)?(?:can you\s+|could you\s+|puedes\s+|me\s+)?"
                rf"(?:{verbs})\s+(?:me\s+|a\s+|an\s+|un\s+|una\s+|the\s+|el\s+|la\s+)?",
                "",
                t,
                flags=re.IGNORECASE,
            ).strip()
        prompt = prompt.rstrip(" .!?¡¿")
        return prompt or t

    @staticmethod
    def _lang_directive(text: str) -> str:
        """Forces the reply into the exact language of `text` instead of hoping
        the model follows a soft system-prompt instruction. Doesn't pre-classify
        into a fixed set of languages (the old version only recognized Spanish
        vs. English) — the message itself is right there for the model to read
        and match, so this works for any language."""
        return (
            "\n\n[IMPORTANT: Reply in the exact same language as the message "
            "above, whatever language that is. Identify it yourself from the "
            "text and match it precisely — do not default to English or "
            "Spanish unless that's genuinely what the message is written in.]"
        )

    @staticmethod
    def _looks_english(text: str) -> bool:
        """Cheap, no-network heuristic used only to skip a translation call for
        the common case. Any non-ASCII letter (accented Latin, Cyrillic, CJK,
        Arabic, Hebrew, Devanagari, ...) is treated as a strong signal the text
        isn't English — which covers most of the world's languages. Casual,
        unaccented non-English text (e.g. "Ich brauche ein Bild" or Spanish
        typed without accents) can still slip through as a false "English" —
        a known, minor limitation, not a claim of perfect language ID."""
        return all(ord(c) < 128 for c in text)

    async def _localize_short_text(self, reference_text: str, english_version: str) -> str:
        """Translates a short fixed English string into whatever language
        `reference_text` is written in, via a single cheap FAST-model call.
        Falls back to the English original on any failure (no provider
        configured, network error, empty response, ...) so this can never
        turn a working caption into a broken one."""
        ai = self._ai_client()
        if not ai:
            return english_version
        try:
            from apps.core.tools.ai_client import AIModel

            resp = await ai.complete(
                system=(
                    "Translate the given sentence into the same language as the "
                    "reference message. Reply with ONLY the translated sentence — "
                    "no quotes, no explanation, no original text."
                ),
                user=f"Reference message: {reference_text[:200]}\nSentence to translate: {english_version}",
                model=AIModel.FAST,
                max_tokens=100,
                temperature=0.0,
                agent_name="aria_caption_localize",
            )
            if resp and resp.success and resp.content and resp.content.strip():
                return resp.content.strip()
        except Exception as e:
            logger.warning("[AriaMind] caption localization failed: %s", e)
        return english_version

    # ── MAIN ENTRY POINT ─────────────────────────────────────────────────────

    async def handle(
        self, text: str, chat_id: str, user_context: str | None = None, email: str = ""
    ) -> MindResponse:
        turn_started = time.monotonic()
        try:
            # Fast-path for built-in commands
            stripped = text.strip().lower()
            if stripped in ("/help", "/ayuda", "help", "ayuda"):
                return MindResponse(text=_HELP_TEXT)
            if stripped in ("/clear", "/limpiar", "/reset"):
                await self._clear_conversation(chat_id)
                return MindResponse(text="Conversation reset. How can I help?", silent=False)
            if stripped in ("/status", "/estado", "status"):
                from apps.core import auth

                if not auth.is_owner_email(email):
                    return MindResponse(
                        text="That's an internal diagnostic command — not available on this account."
                    )
                return await self._build_status()

            # Deterministic fast-path for image generation.
            # Creating images is a headline capability, so we route obvious image
            # requests straight to the tool instead of depending on the (occasionally
            # flaky) LLM planner, which otherwise falls back to a text-only apology.
            img_prompt = self._detect_image_request(text)
            if img_prompt:
                obs, media = await self._execute_with_retry(
                    "generate_image", {"prompt": img_prompt}
                )
                # This caption is returned directly to the user with no LLM synthesis
                # pass in between (that's the whole point of this fast-path), and it's
                # what's actually shown on every successful generation — media being
                # present means `obs` (the tool's own English status line) is skipped
                # in favor of this caption. Skip the extra network round-trip for the
                # common case (an English request); otherwise ask the FAST model for a
                # one-line translation so this isn't locked to just English/Spanish.
                default_caption = "Here's the image I created for you."
                if media and not self._looks_english(text):
                    default_caption = await self._localize_short_text(text, default_caption)
                caption = obs if (obs and not media) else default_caption
                with suppress(Exception):
                    await self._record_exec(
                        "generate_image", {"prompt": img_prompt}, obs, bool(media)
                    )
                    await self._store_interaction(chat_id, text, caption, "generate_image")
                await self._trace_turn("generate_image", text, caption, turn_started, bool(media))
                return MindResponse(
                    text=(None if media else caption),
                    caption=caption,
                    tool_used="generate_image",
                    **media,
                )

            # Load the full cognitive context
            history, state, goals, learned = await asyncio.gather(
                self._load_history(chat_id),
                self._load_state(chat_id),
                self._load_goals(),
                self._load_learned(),
            )

            # Build prompt and reason
            plan = await self._reason(text, history, state, goals, learned, user_context or "")
            if not plan:
                return MindResponse(text="I couldn't process that. Please try again.")

            tool = plan.get("tool")
            tool_args = plan.get("tool_args") or {}
            reply = (plan.get("reply") or "").strip()
            has_tool = bool(tool and tool not in ("null", "none", None))

            # AUTONOMY (agent-style) — ONLY when the plan didn't pick a concrete
            # tool. This way, research/creation gets routed to its reliable tool
            # (web_search, generate_image, …) instead of the autonomous agent,
            # which is more fragile. If the agent fails, we continue with the
            # normal flow instead of returning a raw error.
            if plan.get("autonomous_execution") and not has_tool:
                try:
                    from apps.core import auth
                    from apps.core.cognition.aria_agent import AriaAgent
                    from apps.core.config import settings

                    agent = AriaAgent(
                        identity=SYSTEM_TEMPLATE.format(
                            owner=getattr(settings, "OWNER_NAME", "its owner"),
                            focus=state.get("focus", "autonomous execution"),
                            confidence="100%",
                            interaction_count=state.get("interaction_count", 0),
                            goals="\n".join([g["text"] for g in goals]),
                            learned="\n".join(learned),
                            history="",
                        ),
                        is_owner=auth.is_owner_email(email),
                    )
                    agent_result = await agent.run(text)
                    if agent_result.get("success"):
                        return MindResponse(text=agent_result["output"])
                    logger.warning(
                        "[AriaMind] autonomous run failed, using normal flow: %s",
                        agent_result.get("error"),
                    )
                except Exception as e:
                    logger.warning("[AriaMind] autonomous run error, using normal flow: %s", e)

            # Update goals if the plan indicates it
            goal_action = plan.get("goal_action")
            if goal_action:
                goals = await self._apply_goal_action(goal_action, goals)

            # Execute the tool if there is one
            if has_tool:
                obs, media = await self._execute_with_retry(tool, tool_args, email=email)
                final_text = await self._synthesize(text, tool, obs)
                # bool(media or obs) was always True (obs is a non-empty string even on
                # failure), so self-reflection never saw a real failure signal — every
                # execution looked like a success regardless of outcome. Don't let mere
                # media presence override that either: computer_use always returns a
                # final screenshot even when the run failed, so `media` alone isn't a
                # reliable success signal — judge success from the observation text.
                turn_success = not self._looks_like_failure(obs)
                await self._record_exec(tool, tool_args, obs, turn_success)
                await self._store_interaction(chat_id, text, final_text, tool)
                await self._evolve_state(chat_id, state, text, goals)
                asyncio.create_task(self._maybe_reflect(chat_id))
                await self._trace_turn(tool, text, final_text, turn_started, turn_success)
                # For documents, send text + doc; for A/V media, send caption only
                is_doc = "document_bytes" in media
                return MindResponse(
                    text=final_text if is_doc else (None if media else final_text),
                    caption=final_text,
                    tool_used=tool,
                    **media,
                )

            # Text only
            if not reply:
                reply = await self._fallback_reply(text)

            await self._store_interaction(chat_id, text, reply, None)
            await self._evolve_state(chat_id, state, text, goals)
            asyncio.create_task(self._maybe_reflect(chat_id))
            await self._trace_turn(
                "conversation", text, reply, turn_started, not self._looks_like_failure(reply)
            )
            return MindResponse(text=reply)

        except Exception as exc:
            logger.error("[AriaMind] handle: %s", exc, exc_info=True)
            return MindResponse(text="Internal error. Please try again.")

    # ── REASONING ────────────────────────────────────────────────────────────

    async def _reason(
        self,
        text: str,
        history: list,
        state: dict,
        goals: list[dict],
        learned: list[str],
        user_context: str = "",
    ) -> dict | None:
        ai = self._ai_client()
        if not ai:
            return {"tool": None, "reply": "AI engine isn't available right now."}

        from apps.core.config import settings
        from apps.core.tools.ai_client import AIModel

        goals_text = (
            "\n".join(f"  {i+1}. {Goal(**g).to_prompt()}" for i, g in enumerate(goals[:8]))
            or "  (none defined)"
        )

        history_text = (
            "\n".join(
                ("You: " if m.get("role") == "user" else "ARIA: ") + m.get("content", "")[:200]
                for m in history[-self.MAX_HISTORY :]
            )
            or "(first conversation)"
        )

        learned_text = "\n".join(f"  • {l}" for l in learned[-10:]) or "  (no rules yet)"

        # Enrich system with relevant knowledge base context (RAG)
        kb_context = ""
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base

            kb_context = await get_knowledge_base().search_formatted(text, top_k=3)
        except Exception:
            pass

        system = SYSTEM_TEMPLATE.format(
            owner=getattr(settings, "OWNER_NAME", "its owner"),
            focus=state.get("focus", "no focus defined"),
            confidence=f"{state.get('confidence', 0.7):.0%}",
            interaction_count=state.get("interaction_count", 0),
            goals=goals_text,
            learned=learned_text,
            history=history_text,
        )

        user_input = text
        if kb_context:
            user_input = f"{kb_context}\n\n---\nUser message: {text}"
        if user_context:
            user_input = f"{user_context}\n\n{user_input}"
        user_input += self._lang_directive(text)

        result = await ai.complete_json(
            system=system,
            user=user_input,
            model=AIModel.STRATEGY,
            max_tokens=1800,
            agent_name="aria_mind",
            prefer_quality=True,
        )

        if result and isinstance(result, dict):
            return result

        # Fallback: direct text response
        logger.warning("[AriaMind] complete_json returned None — using FAST fallback")
        resp = await ai.complete(
            system=(
                "You are ARIA. Talk like a real person, not a corporate bot — warm, "
                "direct, no filler. Reply in the SAME language as the user, max 2 sentences."
            ),
            user=text + self._lang_directive(text),
            model=AIModel.FAST,
            max_tokens=300,
            temperature=0.5,
            agent_name="aria_mind_fallback",
            prefer_quality=True,
        )
        if resp and resp.success:
            return {"tool": None, "reply": resp.content}
        return {"tool": None, "reply": "Understood. Give me a moment."}

    # ── EXECUTION WITH RETRY + FALLBACK ─────────────────────────────────────

    # Substrings that show up across this file's ~100 tool branches whenever a
    # tool failed to produce a real result. Deliberately broader than the old
    # startswith-only check (which only caught "error"/"i couldn't"/"failed"/
    # "fail" at the very start of the string) — most failure messages here
    # read like "TTS not available", "No search results...", "Website
    # generation failed", none of which start with those four words, so the
    # retry/adapt-args loop below silently never engaged for them and every
    # such failure was recorded as a "success" for self-reflection purposes.
    # Checked as substrings (not just prefixes) since the failure word rarely
    # leads; kept to phrases that only appear in ARIA's own failure messages,
    # not in tool content like search results or generated text. This is still
    # a text-matching heuristic, not a structured status — a fetched page or
    # search result that happens to contain one of these phrases as real
    # content could false-positive into a retry, and any future failure
    # message that doesn't match one of these phrases will false-negative
    # into a "success". The correct long-term fix is for every tool branch to
    # return an explicit success flag instead of a free-text observation;
    # that's a larger refactor across ~100 branches and out of scope here —
    # this list only needs to keep growing as new failure phrasings show up.
    _FAILURE_SIGNALS = (
        "error",
        "couldn't",
        "i need a",
        "i need an",
        "not available",
        "unavailable",
        "no results",
        "no search results",
        "no response",
        "no trends available",
        "not found",
        "generation failed",
        "build failed",
        "didn't find relevant information",  # search_knowledge's empty-result message
        "reserved for",  # owner-only permission denial
    )

    def _looks_like_failure(self, obs: str) -> bool:
        low = (obs or "").lower()
        return any(sig in low for sig in self._FAILURE_SIGNALS)

    async def _execute_with_retry(
        self, tool: str, args: dict, max_retries: int = 3, email: str = ""
    ) -> tuple[str, dict]:
        """
        Executes the tool with up to max_retries attempts.
        Each attempt may use adapted parameters.
        Returns (observation_text, media_dict).
        """
        last_error = ""
        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(2**attempt)  # backoff: 2s, 4s

            obs, media = await self._execute_tool(tool, args, attempt, email=email)

            # Judge success from the observation text alone — media presence isn't
            # reliable on its own (computer_use always returns a final screenshot
            # even when the run failed).
            if not self._looks_like_failure(obs):
                return obs, media

            # Permission denials are deterministic — another attempt can't
            # change the outcome, so don't burn 2s/4s of backoff on one.
            if "reserved for" in obs.lower():
                return obs, media

            last_error = obs
            logger.warning(
                "[AriaMind] tool=%s attempt=%d/%d: %s", tool, attempt + 1, max_retries, obs[:80]
            )

            # Adapt args for the next attempt
            args = self._adapt_args(tool, args, obs, attempt)

        return f"I tried {max_retries} times and couldn't complete '{tool}': {last_error}", {}

    def _adapt_args(self, tool: str, args: dict, error: str, attempt: int) -> dict:
        """Adapts the arguments based on the error for the next attempt."""
        if tool == "generate_image" and attempt == 1:
            # First fallback: change model
            args = dict(args, _fallback_model="stabilityai/stable-diffusion-xl-base-1.0")
        elif tool == "generate_image" and attempt == 2:
            args = dict(args, _fallback_model="stabilityai/sdxl-turbo")
        elif tool == "web_search" and attempt > 0:
            # Simplify the query
            query = args.get("query", "")
            words = query.split()
            args = {"query": " ".join(words[:4])}  # shorter query
        return args

    # Tools that write to a real, external system of record on the owner's
    # behalf — not merely "generate content for the requesting user", but
    # "commit code to a GitHub repo (including ARIA's own production repo via
    # github_self)". These must never be reachable by an arbitrary signed-up
    # account; only the owner.
    #
    # execute_code is here too: CodeRunner (apps/core/tools/code_runner.py)
    # runs the model-chosen code as a plain subprocess on the same host —
    # no container/VM isolation — and its "blocked imports" check is a
    # handful of substring matches, trivially bypassed. Until real sandboxing
    # exists, this is effectively host code execution and must stay
    # owner-only, not a free-tier chat capability.
    #
    # computer_use launches a real headless Chromium and lets the model click
    # and type anywhere on the open web via coordinate-based actions — always
    # a fresh, credential-free browser context (never the owner's logged-in
    # session), but still capable of real-world side effects (submitting
    # forms, following links) that a free-tier account must not be able to
    # trigger unsupervised.
    _OWNER_ONLY_TOOLS = frozenset(
        {
            "github_write",
            "github_pr",
            "github_issues",
            "github_self",
            "execute_code",
            "computer_use",
        }
    )

    async def _execute_tool(
        self, tool: str, args: dict, attempt: int = 0, email: str = ""
    ) -> tuple[str, dict]:
        """
        Executes the tool. Returns (obs_text, media_dict).
        media_dict: {image_bytes, video_bytes, audio_bytes} — only the one that applies.
        """
        if tool in self._OWNER_ONLY_TOOLS:
            from apps.core import auth

            if not auth.is_owner_email(email):
                return (
                    "This action is reserved for ARIA's owner.",
                    {},
                )
        try:
            # ── IMAGE ────────────────────────────────────────────────────
            if tool == "generate_image":
                prompt = args.get("prompt", "") or "professional high-end marketing graphic"
                import urllib.parse as _url

                import httpx

                # Pollinations FIRST — HF's api-inference host is deprecated (DNS fails),
                # so go straight to the reliable, keyless provider that actually works.
                poll_url = (
                    "https://image.pollinations.ai/prompt/"
                    f"{_url.quote(prompt[:400])}?width=1024&height=1024&nologo=true&model=flux"
                )
                try:
                    async with httpx.AsyncClient(timeout=45.0) as client:
                        resp = await client.get(poll_url)
                    if resp.status_code == 200 and resp.content:
                        logger.info("[AriaMind] Image generated via Pollinations")
                        # media dict is spread into MindResponse(**media), so it must
                        # only contain valid fields (image_bytes). URL stays in the text.
                        return (
                            f"Image generated: {prompt}\n{poll_url}",
                            {"image_bytes": resp.content},
                        )
                except Exception as e:
                    logger.error("[AriaMind] Pollinations failed: %s", e)

                # Secondary: HuggingFace FLUX (only if the host/token happen to work).
                try:
                    from apps.core.tools.huggingface_suite import HuggingFaceSuite

                    r = await HuggingFaceSuite().generate_image(
                        prompt=prompt,
                        model="black-forest-labs/FLUX.1-schnell",
                        width=1024,
                        height=1024,
                        num_inference_steps=4,
                    )
                    if r.get("success") and r.get("image_bytes"):
                        return "Image generated with FLUX.1", {"image_bytes": r["image_bytes"]}
                except Exception as e:
                    logger.error("[AriaMind] HF image failed: %s", e)

                # Both providers failed to return bytes — degrade to a link in the
                # text (media dict must only contain valid MindResponse fields).
                return (
                    f"I couldn't embed the image right now, but you can open it here: {poll_url}",
                    {},
                )

            # ── VIDEO ────────────────────────────────────────────────────
            if tool == "generate_video":
                prompt = args.get("prompt", "")
                import base64 as _b64

                # Layer 2: real AI-generated footage on rented GPU (LTX/Wan2.2),
                # when a provider token is configured. Otherwise → layer 1: our
                # own ffmpeg reel engine (FLUX stills + Ken Burns + voiceover).
                # Last resort: the free Wan2.2 HF Space.
                from apps.core.tools.video_ai import get_ai_video

                ai = get_ai_video()
                r = await ai.generate(prompt) if ai.available() else {"success": False}
                if not r.get("success"):
                    from apps.core.tools.video_engine import get_video_engine

                    r = await get_video_engine().generate(prompt)
                if not r.get("success"):
                    from apps.core.tools.creative_engine import CreativeEngine

                    r = await CreativeEngine().generate_video(prompt)
                if r.get("success"):
                    raw = r.get("video_bytes")
                    if not raw:
                        v64 = r.get("video_b64") or r.get("video_base64")
                        if v64:
                            raw = v64 if isinstance(v64, bytes) else _b64.b64decode(v64)
                    tag = r.get("provider") or (f"{r['scenes']} scenes" if r.get("scenes") else "")
                    if raw:
                        extra = f" · {tag}" if tag else ""
                        return f"Video generated ({len(raw)//1024}KB{extra})", {"video_bytes": raw}
                    if r.get("video_url"):
                        return f"Video generated: {r['video_url']}", {}
                return (
                    f"I couldn't generate the video: {r.get('error', 'Provider not available')}",
                    {},
                )

            # ── MUSIC ────────────────────────────────────────────────────
            if tool == "generate_music":
                prompt = args.get("prompt", "")
                dur = int(args.get("duration", 30))
                from apps.core.tools.creative_engine import CreativeEngine

                r = await CreativeEngine().generate_music(prompt, duration=dur)
                if r.get("success"):
                    import base64 as _b64

                    ab64 = r.get("audio_base64") or r.get("audio_b64")
                    if ab64:
                        # If it's already bytes (for some reason) don't decode; if it's a str, decode it
                        audio_data = ab64 if isinstance(ab64, bytes) else _b64.b64decode(ab64)
                        return f"Music generated ({dur}s)", {"audio_bytes": audio_data}
                return (
                    f"I couldn't generate the music: {r.get('error', 'Provider not available')}",
                    {},
                )

            # ── WEB SEARCH ───────────────────────────────────────────────
            if tool == "web_search":
                query = args.get("query", "")
                from apps.core.tools.web_tools import WebTools

                r = await WebTools().search_web(query, num_results=10)
                if r.get("success") and r.get("results"):
                    source = r.get("source", "web")
                    lines = [f"[Source: {source} | Query: {query}]"]
                    for i, res in enumerate(r["results"][:8]):
                        title = res.get("title", "")
                        snippet = res.get("snippet", "")[:300]
                        url = res.get("url", "")
                        lines.append(f"{i+1}. **{title}**\n   {snippet}\n   {url}")
                    return "\n\n".join(lines), {}
                return "No search results. Try rephrasing the query.", {}

            # ── DEEP SEARCH ──────────────────────────────────────────────
            if tool == "deep_search":
                query = args.get("query", "")
                num_pages = min(int(args.get("num_pages", 3)), 5)
                from apps.core.tools.web_tools import WebTools

                wt = WebTools()
                r = await wt.search_web(query, num_results=num_pages + 2)
                if not r.get("success") or not r.get("results"):
                    return "No results found for the deep search.", {}
                # Fetch content from top pages in parallel
                urls = [res.get("url", "") for res in r["results"] if res.get("url")][:num_pages]
                fetch_tasks = [wt.fetch_page(url, max_chars=2000) for url in urls]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                parts = [f"[Deep Search: {query}]"]
                for i, (res, page) in enumerate(zip(r["results"], pages, strict=False)):
                    title = res.get("title", f"Result {i+1}")
                    url = res.get("url", "")
                    if isinstance(page, dict) and page.get("success") and page.get("text"):
                        content = page["text"][:1500]
                    else:
                        content = res.get("snippet", "")[:400]
                    parts.append(f"### {title}\n{url}\n{content}")
                return "\n\n---\n\n".join(parts), {}

            # ── FETCH URL ────────────────────────────────────────────────
            if tool == "fetch_url":
                url = args.get("url", "")
                if not url:
                    return "I need a URL to read.", {}
                from apps.core.tools.web_tools import WebTools

                r = await WebTools().fetch_page(url, max_chars=4000)
                if r.get("success") and r.get("text"):
                    return f"[Content from {url}]\n\n{r['text']}", {}
                return f"I couldn't read the URL: {r.get('error', 'No response')}", {}

            # ── TRENDS ───────────────────────────────────────────────────
            if tool == "get_trends":
                from apps.core.tools.web_tools import WebTools

                wt = WebTools()
                hn, rd = await asyncio.gather(
                    wt.get_hacker_news_trending(limit=5),
                    wt.get_reddit_trending(limit=5),
                    return_exceptions=True,
                )
                parts = []
                if isinstance(hn, dict) and hn.get("success"):
                    hn_titles = [s.get("title", "")[:70] for s in hn.get("stories", [])[:4]]
                    parts.append("HN: " + " | ".join(hn_titles))
                if isinstance(rd, dict) and rd.get("success"):
                    rd_titles = [p.get("title", "")[:70] for p in rd.get("posts", [])[:4]]
                    parts.append("Reddit: " + " | ".join(rd_titles))
                return "\n".join(parts) if parts else "No trends available", {}

            # ── SYSTEM STATUS ────────────────────────────────────────────
            if tool == "get_status":
                try:
                    from apps.core.training.continuous_trainer import get_trainer

                    s = get_trainer().get_status()
                    skills = s.get("skill_scores", {})
                    skills_str = (
                        ", ".join(f"{k}:{v:.0f}%" for k, v in skills.items()) or "evaluating"
                    )
                    return (
                        f"Cycle #{s.get('cycle', 0)} | Skills: {skills_str} | "
                        f"Running: {s.get('running', False)}"
                    ), {}
                except Exception as e:
                    return f"System active (error getting detail: {e})", {}

            # ── INCOME CYCLE ─────────────────────────────────────────────
            elif tool == "run_income":
                from apps.core.agents.orchestrator import Orchestrator

                r = await Orchestrator().run_cycle()
                rev = r.get("revenue_summary", {}).get("total_revenue_usd", 0)
                pub = r.get("revenue_summary", {}).get("items_published", 0)
                t = r.get("cycle_time_s", 0)
                return (
                    f"Cycle completed in {t:.0f}s — " f"Revenue: ${rev:.2f} — Published: {pub}"
                ), {}

            # ── SQUARE ────────────────────────────────────────────────────
            elif tool == "square_sell":
                from apps.core.integrations.square_engine import SquareEngine

                engine = SquareEngine()
                name = args.get("name", "Aria Product")
                desc = args.get("description", "Generated by Aria AI")
                price = int(args.get("price", 1000))  # cents
                r = await engine.create_catalog_item(name, desc, price)
                if r.get("success"):
                    link = await engine.create_payment_link(r["data"]["object"]["id"], name, price)
                    return (
                        f"Product created on Square: {name}. Payment link: {link.get('payment_link')}",
                        {},
                    )
                return f"Error on Square: {r.get('error')}", {}

            # ── TEXT-TO-SPEECH (BARK) ─────────────────────────────────────
            elif tool == "speak":
                text_input = args.get("text", "")
                voice = args.get("voice", "v2/es_speaker_1")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().text_to_speech_bark(text_input, voice_preset=voice)
                if r.get("success") and r.get("audio_bytes"):
                    ab = r["audio_bytes"]
                    return f"Audio generated ({len(ab)//1024}KB, voice: {voice})", {
                        "audio_bytes": ab
                    }
                return r.get("error", "TTS not available"), {}

            # ── TRANSLATION ──────────────────────────────────────────────
            elif tool == "translate":
                text_input = args.get("text", "")
                source = args.get("source", "es")
                target = args.get("target", "en")
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().translate(text_input, source=source, target=target)
                if r.get("success"):
                    return f"[{source}→{target}] {r.get('translated', '')}", {}
                return r.get("error", "Translation not available"), {}

            # ── PDF GENERATION ───────────────────────────────────────────
            elif tool == "generate_pdf":
                title = args.get("title", "Document")
                content = args.get("content", "")
                sections = args.get("sections") or []
                from apps.core.tools.pdf_generator import generate_pdf as _gen_pdf

                r = await _gen_pdf(title=title, content=content, sections=sections)
                if r.get("success") and r.get("pdf_bytes"):
                    fname = r.get("filename", "document.pdf")
                    size = r.get("size_kb", 0)
                    return (
                        f"PDF generated: {fname} ({size}KB)",
                        {"document_bytes": r["pdf_bytes"], "document_filename": fname},
                    )
                return r.get("error", "I couldn't generate the PDF"), {}

            # ── WEBSITE ───────────────────────────────────────────────────
            elif tool == "create_website":
                from apps.core.tools.website_engine import WebsiteEngine

                r = await WebsiteEngine().generate_website(
                    name=args.get("name", "My Website"),
                    description=args.get("description", ""),
                    sections=args.get("sections", ["hero", "features", "cta", "footer"]),
                    template=args.get("template", "saas"),
                )
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "website.html")
                    size = len(r["html_bytes"]) // 1024
                    return (
                        f"Website generated: {fname} ({size}KB)",
                        {"document_bytes": r["html_bytes"], "document_filename": fname},
                    )
                return r.get("error", "Website generation failed"), {}

            # ── SOCIAL CONTENT ────────────────────────────────────────────
            elif tool == "create_social_content":
                topic = args.get("topic", "")
                platforms = args.get("platforms", ["instagram", "linkedin", "twitter"])
                tone = args.get("tone", "professional")
                from apps.core.tools.social_engine import SocialContentEngine

                r = await SocialContentEngine().create_content_pack(topic, platforms, tone)
                if r.get("success"):
                    lines = [f"Content generated for {r.get('generated', 0)} platforms:\n"]
                    for plat, res in r.get("platforms", {}).items():
                        if res.get("success"):
                            lines.append(f"**{plat.upper()}**\n{res.get('content', '')[:500]}\n")
                    return "\n".join(lines), {}
                return "I couldn't generate social content", {}

            # ── SOFTWARE / APP ───────────────────────────────────────────
            elif tool == "build_software":
                from apps.core.tools.software_builder import SoftwareBuilder

                r = await SoftwareBuilder().build_project(
                    name=args.get("name", "MyApp"),
                    description=args.get("description", ""),
                    stack=args.get("stack", "fastapi"),
                    requirements_text=args.get("requirements", ""),
                )
                if r.get("success") and r.get("zip_bytes"):
                    fname = r.get("filename", "project.zip")
                    size = r.get("size_kb", 0)
                    files = r.get("files", [])
                    obs = f"Project generated: {fname} ({size}KB) — {len(files)} files: {', '.join(files[:6])}"
                    return obs, {"document_bytes": r["zip_bytes"], "document_filename": fname}
                return r.get("error", "Software build failed"), {}

            # ── VIDEO GAME ────────────────────────────────────────────────
            elif tool == "build_game":
                from apps.core.tools.game_builder import GameBuilder

                r = await GameBuilder().create_game(
                    name=args.get("name", "MyGame"),
                    genre=args.get("genre", "arcade"),
                    description=args.get("description", ""),
                    engine=args.get("engine", "pygame"),
                )
                if r.get("success") and r.get("zip_bytes"):
                    fname = r.get("filename", "game.zip")
                    size = r.get("size_kb", 0)
                    files = r.get("files", [])
                    obs = f"Game generated ({r.get('engine', '')}): {fname} ({size}KB) — {len(files)} files"
                    return obs, {"document_bytes": r["zip_bytes"], "document_filename": fname}
                return r.get("error", "Game build failed"), {}

            # ── PUBLISH ARTICLE ──────────────────────────────────────────
            elif tool == "publish_article":
                title = args.get("title", "")
                content = args.get("content", "")
                tags = args.get("tags", [])
                platforms = args.get("platforms", ["devto"])
                from apps.core.tools.publishing_tools import PublishingTools

                pt = PublishingTools()
                results = {}
                for plat in platforms:
                    if plat == "devto":
                        results["devto"] = await pt.publish_to_devto(title, content, tags)
                    elif plat == "medium":
                        results["medium"] = await pt.publish_to_medium(title, content, tags)
                    elif plat == "hashnode":
                        results["hashnode"] = await pt.publish_to_hashnode(title, content, tags)
                published = [p for p, r in results.items() if r.get("success")]
                if published:
                    return f"Article published on: {', '.join(published)}", {}
                errors = "; ".join(f"{p}: {r.get('error','?')}" for p, r in results.items())
                return f"I couldn't publish: {errors}", {}

            # ── SEND EMAIL / NEWSLETTER ───────────────────────────────────
            elif tool == "send_email":
                subject = args.get("subject", "")
                body = args.get("body", "")
                to = args.get("to", "")
                from apps.core.tools.publishing_tools import PublishingTools

                r = await PublishingTools().send_newsletter(subject, body, to_override=to)
                if r.get("success"):
                    return f"Email sent via {r.get('provider', 'email')}", {}
                return r.get("error", "Email not available"), {}

            # ── DESCRIBE IMAGE ────────────────────────────────────────────
            elif tool == "describe_image":
                url = args.get("url", "")
                if not url:
                    return "I need an image URL.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().describe_image(image_url=url)
                if r.get("success"):
                    return f"Description: {r.get('description', '')}", {}
                return r.get("error", "I couldn't describe the image"), {}

            # ── EXECUTE CODE (SANDBOX) ────────────────────────────────────
            elif tool == "execute_code":
                code = args.get("code", "")
                language = args.get("language", "python")
                from apps.core.tools.code_runner import CodeRunner

                r = await CodeRunner().run(code=code, language=language)
                output = r.get("stdout", "") or r.get("stderr", "") or "(no output)"
                status = "OK" if r.get("success") else "ERROR"
                return f"[{language} {status}]\n{output[:2000]}", {}

            # ── SANDBOX BROWSER ───────────────────────────────────────────
            elif tool == "browse_page":
                url = args.get("url", "")
                take_shot = args.get("screenshot", False)
                from apps.core.tools.browser_sandbox import get_sandbox

                r = await get_sandbox().browse(url, extract=True, screenshot=take_shot)
                content = r.get("content", "")[:3000]
                title = r.get("title", url)
                obs = f"[PAGE: {title}]\n{content}"
                media: dict = {}
                if take_shot and r.get("screenshot_bytes"):
                    media["image_bytes"] = r["screenshot_bytes"]
                return obs, media

            elif tool == "interact_browser":
                steps = args.get("steps", [])
                from apps.core.tools.browser_sandbox import get_sandbox

                session = get_sandbox()._get_session()
                r = await session.interact_with_page(steps)
                summary = f"Steps executed: {r.get('steps_executed',0)}, succeeded: {r.get('steps_succeeded',0)}"
                details = "\n".join(
                    f"  {s['action']}: {'OK' if s.get('result',{}).get('success') else 'FAIL'}"
                    for s in r.get("results", [])
                )
                return f"[BROWSER] {summary}\n{details}", {}

            # ── COMPUTER USE (visual, click-driven browser agent) ─────────
            elif tool == "computer_use":
                task = args.get("task", "")
                if not task:
                    return "I need a task description to operate the computer for.", {}
                start_url = args.get("start_url", "about:blank")
                max_steps = int(args.get("max_steps", 15))
                import base64

                from apps.core.config import settings
                from apps.core.integrations.computer_agent import (
                    BrowserComputer,
                    ComputerUseAgent,
                )

                if not settings.ANTHROPIC_API_KEY:
                    return (
                        "Computer Use needs ANTHROPIC_API_KEY configured — it isn't set.",
                        {},
                    )
                computer = BrowserComputer(headless=True, start_url=start_url)
                await computer.start()
                try:
                    agent = ComputerUseAgent(computer, api_key=settings.ANTHROPIC_API_KEY)
                    run = await agent.run(task, max_steps=max_steps)
                    final_shot_b64 = await computer.screenshot_b64()
                finally:
                    await computer.close()
                media = {"image_bytes": base64.b64decode(final_shot_b64)}
                summary = (
                    f"[COMPUTER USE] {len(run.steps)} steps, stop_reason={run.stop_reason}\n"
                    f"{run.final_text or '(no final text)'}"
                )
                return summary, media

            # ── BUSINESS AGENT ────────────────────────────────────────────
            elif tool == "run_business_agent":
                agent_name = args.get("agent", "ceo")
                mission = args.get("mission", "")
                context = dict(args.get("context") or {})
                from apps.core import auth
                from apps.core.agents.business_hub import BusinessHub

                # Threaded through so developer_agent.py can refuse to
                # *execute* generated code for non-owners — auto-routing
                # (agent="auto") can reach the developer agent from mission
                # text alone, so this can't be gated by agent_name up front.
                context["is_owner"] = auth.is_owner_email(email)
                r = await BusinessHub().dispatch(agent_name, mission, context)
                summary = r.get("summary", r.get("result", str(r))[:400])
                return f"[{agent_name.upper()}] {summary}", {}

            # ── GOAL MANAGEMENT ───────────────────────────────────────────
            elif tool in ("add_goal", "update_goal"):
                # Delegate to the goal_action system properly
                action = "add" if tool == "add_goal" else "update"
                goal_action_dict: dict = {"action": action}
                if action == "add":
                    goal_action_dict["text"] = args.get("text", "")
                    goal_action_dict["priority"] = args.get("priority", 5)
                else:
                    goal_action_dict["index"] = args.get("index", 0)
                    if "progress" in args:
                        goal_action_dict["progress"] = args["progress"]
                    if "status" in args:
                        goal_action_dict["status"] = args["status"]
                goals_list = await self._load_goals()
                await self._apply_goal_action(goal_action_dict, goals_list)
                return f"Goal {'added' if action == 'add' else 'updated'} successfully", {}

            # ── EXTENDED REASONING ────────────────────────────────────────
            elif tool == "deep_think":
                question = args.get("question", "")
                depth = args.get("depth", "auto")
                context = args.get("context", "")
                from apps.core.tools.deep_think import get_deep_think

                result = await get_deep_think().think(question, context=context, depth=depth)
                obs = f"[DEEP THINK — {result.depth.upper()} — {result.duration_ms}ms]\n{result.answer}"
                return obs, {}

            elif tool == "analyze_decision":
                question = args.get("question", "")
                options = args.get("options", [])
                criteria = args.get("criteria", [])
                from apps.core.tools.deep_think import get_deep_think

                result = await get_deep_think().analyze_decision(question, options, criteria)
                return f"[DECISION]\n{result['recommendation']}", {}

            # ── PRESENTATIONS ─────────────────────────────────────────────
            elif tool == "create_presentation":
                title = args.get("title", "Presentation")
                topic = args.get("topic", title)
                slide_count = int(args.get("slide_count", 10))
                template = args.get("template", "dark")
                from apps.core.tools.presentation_builder import PresentationBuilder

                r = await PresentationBuilder().create_presentation(
                    title, topic, slide_count, template
                )
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "presentation.html")
                    obs = f"Presentation '{title}' generated: {r['slide_count']} slides"
                    return obs, {"document_bytes": r["html_bytes"], "document_filename": fname}
                return "I couldn't generate the presentation", {}

            elif tool == "create_pitch_deck":
                company = args.get("company", "")
                problem = args.get("problem", "")
                solution = args.get("solution", "")
                market = args.get("market", "")
                traction = args.get("traction", "")
                from apps.core.tools.presentation_builder import PresentationBuilder

                r = await PresentationBuilder().create_pitch_deck(
                    company, problem, solution, market, traction
                )
                if r.get("success") and r.get("html_bytes"):
                    fname = r.get("filename", "pitch_deck.html")
                    obs = f"Pitch deck '{company}' generated: {r['slide_count']} slides"
                    return obs, {"document_bytes": r["html_bytes"], "document_filename": fname}
                return "I couldn't generate the pitch deck", {}

            # ── MULTIMODAL ───────────────────────────────────────────────
            elif tool == "analyze_image":
                url = args.get("url", "")
                question = args.get("question", "Describe this image in detail.")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().analyze_image(image_url=url, question=question)
                if r.get("success"):
                    return f"[IMAGE ANALYSIS]\n{r['analysis']}", {}
                return f"I couldn't analyze the image: {r.get('error', 'unknown error')}", {}

            elif tool == "extract_text":
                url = args.get("url", "")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().extract_text(image_url=url)
                if r.get("success"):
                    return f"[OCR]\n{r['analysis']}", {}
                return f"I couldn't extract text: {r.get('error', 'unknown error')}", {}

            elif tool == "edit_image":
                url = args.get("url", "")
                instruction = args.get("instruction", "")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().edit_image(image_url=url, instruction=instruction)
                if r.get("success") and r.get("image_bytes"):
                    return f"Image edited: '{instruction}'", {"image_bytes": r["image_bytes"]}
                return f"I couldn't edit the image: {r.get('error', 'unknown error')}", {}

            elif tool == "analyze_video":
                url = args.get("url", "")
                question = args.get("question", "Describe this video in detail.")
                from apps.core.tools.multimodal import get_multimodal

                r = await get_multimodal().analyze_video_url(url, question)
                if r.get("success"):
                    frames = r.get("frames_analyzed", 0)
                    return f"[VIDEO ANALYSIS — {frames} frames]\n{r['analysis']}", {}
                return f"I couldn't analyze the video: {r.get('error', 'unknown error')}", {}

            # ── ADDITIONAL HF TOOLS (ecommerce/documents) ─────────────────
            elif tool == "remove_background":
                url = args.get("url", "")
                if not url:
                    return "I need an image URL.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                try:
                    img_bytes = await _fetch_image_bytes(url)
                except Exception as exc:
                    return f"I couldn't download the image: {exc}", {}
                r = await HuggingFaceSuite().remove_background(img_bytes)
                if r.get("success") and r.get("image_bytes"):
                    return "Background removed.", {"image_bytes": r["image_bytes"]}
                return r.get("error", "I couldn't remove the background"), {}

            elif tool == "classify_image":
                url = args.get("url", "")
                if not url:
                    return "I need an image URL.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                try:
                    img_bytes = await _fetch_image_bytes(url)
                except Exception as exc:
                    return f"I couldn't download the image: {exc}", {}
                r = await HuggingFaceSuite().classify_image(img_bytes)
                if r.get("success"):
                    top = f"{r['top_label']} ({r['top_score'] * 100:.1f}%)"
                    others = ", ".join(
                        f"{a['label']} ({a['score'] * 100:.1f}%)" for a in r.get("all", [])[1:5]
                    )
                    obs = f"[CLASSIFICATION] {top}" + (f"\nAlso: {others}" if others else "")
                    return obs, {}
                return r.get("error", "I couldn't classify the image"), {}

            elif tool == "document_qa":
                url = args.get("url", "")
                question = args.get("question", "")
                if not url or not question:
                    return "I need a document URL and a question.", {}
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                try:
                    img_bytes = await _fetch_image_bytes(url)
                except Exception as exc:
                    return f"I couldn't download the document: {exc}", {}
                r = await HuggingFaceSuite().document_qa(img_bytes, question)
                if r.get("success"):
                    return (
                        f"[DOCUMENT] {r['answer']} (confidence: {r['confidence'] * 100:.0f}%)",
                        {},
                    )
                return r.get("error", "I couldn't read the document"), {}

            elif tool == "create_product_pack":
                product_name = args.get("product_name", "")
                product_description = args.get("product_description", "")
                niche = args.get("niche", "")
                languages = args.get("languages") or None
                from apps.core.tools.huggingface_suite import HuggingFaceSuite

                r = await HuggingFaceSuite().create_product_content_pack(
                    product_name, product_description, niche, languages
                )
                media: dict = {}
                product_bytes = (r.get("product_image") or {}).get("bytes")
                if product_bytes:
                    media["image_bytes"] = product_bytes
                translations = r.get("translations") or {}
                langs_done = ", ".join(translations.keys()) if translations else "none"
                extra_imgs = []
                if (r.get("social_image") or {}).get("bytes"):
                    extra_imgs.append("social")
                if (r.get("blog_thumbnail") or {}).get("bytes"):
                    extra_imgs.append("blog thumbnail")
                obs = (
                    f"[PRODUCT PACK: {product_name}]\n"
                    f"Niche: {r.get('niche_classification', niche)}\n"
                    f"Summary: {r.get('summary', '')}\n"
                    f"Market sentiment: {r.get('market_sentiment', '')}\n"
                    f"Translations generated: {langs_done}\n"
                    f"Images generated: product"
                    + (f", {', '.join(extra_imgs)}" if extra_imgs else "")
                )
                return obs, media

            # ── BACKGROUND TASKS ──────────────────────────────────────────
            elif tool == "run_background":
                task_name = args.get("task", "")
                agent_name = args.get("agent", "ceo")
                from apps.core.agents.business_hub import BusinessHub
                from apps.core.tools.task_manager import get_task_manager

                async def _bg():
                    return await BusinessHub().dispatch(agent_name, task_name, {})

                mgr = get_task_manager()
                task_id = await mgr.submit(
                    name=task_name,
                    coro_factory=_bg,
                    description=f"{agent_name}: {task_name}",
                    session_id=None,
                )
                return (
                    f"Task '{task_name}' started in the background (ID: {task_id}). I'll let you know when it's done.",
                    {},
                )

            elif tool == "task_status":
                task_id = args.get("task_id", "")
                from apps.core.tools.task_manager import get_task_manager

                mgr = get_task_manager()
                if task_id:
                    record = mgr.get_task(task_id)
                    if record:
                        return (
                            f"[Task {task_id}] {record.status.value}: {record.result or record.error or 'in progress'}",
                            {},
                        )
                    return f"Task {task_id} not found.", {}
                tasks = mgr.list_tasks(limit=10)
                if not tasks:
                    return "No background tasks.", {}
                lines = [f"• [{t['id']}] {t['status']} — {t['name']}" for t in tasks]
                return "[BACKGROUND TASKS]\n" + "\n".join(lines), {}

            # ── KNOWLEDGE BASE (RAG) ───────────────────────────────────────
            elif tool == "learn":
                source = args.get("source", "")
                category = args.get("category", "general")
                is_url = args.get("is_url", source.startswith("http"))
                from apps.core.tools.knowledge_base import get_knowledge_base

                kb = get_knowledge_base()
                if is_url:
                    r = await kb.ingest_url(source, category=category)
                else:
                    r = await kb.ingest_text(source, source=category, category=category)
                if r.get("success"):
                    return (
                        f"Learned: {r['chunks_added']} chunks from '{source[:60]}' "
                        f"(total in KB: {r['total_chunks']})"
                    ), {}
                return f"I couldn't learn that source: {r.get('error', 'error')}", {}

            elif tool == "search_knowledge":
                query = args.get("query", "")
                top_k = int(args.get("top_k", 5))
                from apps.core.tools.knowledge_base import get_knowledge_base

                formatted = await get_knowledge_base().search_formatted(query, top_k=top_k)
                if formatted:
                    return formatted, {}
                return (
                    "I didn't find relevant information in the knowledge base. Try using 'learn' first.",
                    {},
                )

            elif tool == "forget_source":
                source = args.get("source", "")
                from apps.core.tools.knowledge_base import get_knowledge_base

                deleted = get_knowledge_base().delete_source(source)
                return (
                    f"Removed {deleted} chunks of '{source}' from the knowledge base.",
                    {},
                )

            # ── R&D WING (long-running research projects) ──────────────────
            elif tool == "create_research_project":
                name = args.get("name", "")
                goal = args.get("goal", "")
                category = args.get("category", "General/Innovation")
                if not name or not goal:
                    return "I need both a project name and a goal to create it.", {}
                from apps.core.intelligence.rd_wing import get_rd_wing

                project = get_rd_wing().create_project(name, goal, category)
                return (
                    f"R&D project created: **{project.name}** ({project.category})\n{project.goal}",
                    {},
                )

            elif tool == "add_research_finding":
                project_name = args.get("project", "")
                title = args.get("title", "")
                content = args.get("content", "")
                source = args.get("source", "unspecified")
                if not project_name or not title or not content:
                    return "I need a project name, a finding title, and its content.", {}
                from apps.core.intelligence.rd_wing import get_rd_wing

                rd = get_rd_wing()
                if not rd.get_project(project_name):
                    return f"No R&D project named '{project_name}' — create it first.", {}
                rd.add_finding_to_project(project_name, title, content, source)
                return f"Finding logged on **{project_name}**: {title}", {}

            elif tool == "list_research_projects":
                from apps.core.intelligence.rd_wing import get_rd_wing

                projects = get_rd_wing().list_projects()
                if not projects:
                    return "No R&D projects yet. Use create_research_project to start one.", {}
                lines = ["**R&D projects:**"]
                for p in projects:
                    lines.append(
                        f"  • {p['name']} ({p['category']}, {p['status']}) — {len(p['findings'])} findings"
                    )
                return "\n".join(lines), {}

            # ── BRAND IDENTITY ───────────────────────────────────────────────
            elif tool == "create_brand":
                name = args.get("name", "")
                niche = args.get("niche", "")
                tone_raw = args.get("tone", "professional")
                if not name or not niche:
                    return "I need both a brand name and a niche to create a brand identity.", {}
                from apps.branding.identity.brand_engine import BrandTone, get_brand_engine

                try:
                    tone = BrandTone(tone_raw)
                except ValueError:
                    tone = BrandTone.PROFESSIONAL
                profile = await get_brand_engine().create_brand(name, niche, tone)
                return (
                    f"Brand created: **{profile.name}** (id: `{profile.brand_id}`)\n"
                    f"Niche: {profile.niche} · Tone: {profile.voice.tone.value}\n"
                    f"Palette: {profile.palette.primary} / {profile.palette.secondary} / {profile.palette.accent}\n"
                    f"Use this brand_id with check_brand_consistency to keep future content on-brand."
                ), {}

            elif tool == "check_brand_consistency":
                brand_id = args.get("brand_id", "")
                content = args.get("content", "")
                if not brand_id or not content:
                    return "I need a brand_id and the content to check.", {}
                from apps.branding.identity.brand_engine import get_brand_engine

                engine = get_brand_engine()
                await engine._load()
                result = engine.consistency_check(brand_id, content)
                lines = [f"**Brand consistency: {result['score']}/100**"]
                if result["violations"]:
                    lines.append(
                        "Violations:\n" + "\n".join(f"  • {v}" for v in result["violations"])
                    )
                if result["suggestions"]:
                    lines.append(
                        "Suggestions:\n" + "\n".join(f"  • {s}" for s in result["suggestions"])
                    )
                return "\n".join(lines), {}

            elif tool == "list_brands":
                from apps.branding.identity.brand_engine import get_brand_engine

                brands = await get_brand_engine().list_brands()
                if not brands:
                    return "No brands defined yet. Use create_brand to start one.", {}
                lines = ["**Brands:**"]
                for b in brands:
                    lines.append(
                        f"  • {b.name} (id: `{b.brand_id}`) — {b.niche}, {b.voice.tone.value}"
                    )
                return "\n".join(lines), {}

            # ── CREATIVE STYLE ────────────────────────────────────────────────
            elif tool == "create_style_profile":
                name = args.get("name", "")
                niche = args.get("niche", "default")
                base_style = args.get("base_style") or None
                if not name:
                    return "I need a name for this style profile.", {}
                from apps.creative.style.style_engine import get_style_engine

                profile = await get_style_engine().create_profile(name, niche, base_style)
                dims = ", ".join(f"{k.lower()}: {v}" for k, v in profile.dimensions.items())
                return (
                    f"**Style profile '{profile.name}'** (id: `{profile.profile_id}`)\n{dims}",
                    {},
                )

            elif tool == "evolve_style":
                profile_id = args.get("profile_id", "")
                direction = args.get("direction", "bolder")
                if not profile_id:
                    return "I need a profile_id (from create_style_profile) to evolve.", {}
                from apps.creative.style.style_engine import get_style_engine

                try:
                    profile = await get_style_engine().evolve_style(profile_id, direction)
                except ValueError as e:
                    return str(e), {}
                dims = ", ".join(f"{k.lower()}: {v}" for k, v in profile.dimensions.items())
                return (
                    f"**Evolved '{profile.name}' ({direction}, evolution #{profile.evolution_count})**\n"
                    f"{dims}"
                ), {}

            elif tool == "check_content_novelty":
                profile_id = args.get("profile_id", "")
                content = args.get("content", "")
                if not profile_id or not content:
                    return "I need both a profile_id and the content to check for novelty.", {}
                from apps.creative.style.style_engine import get_style_engine

                result = await get_style_engine().check_novelty(profile_id, content)
                lines = [f"**Novelty score: {result['novelty_score']:.0%}**"]
                if result["detected_cliches"]:
                    lines.append(
                        "Clichés found:\n"
                        + "\n".join(f"  • {c}" for c in result["detected_cliches"])
                    )
                if result["freshness_tips"]:
                    lines.append(
                        "Freshness tips:\n"
                        + "\n".join(f"  • {t}" for t in result["freshness_tips"])
                    )
                return "\n".join(lines), {}

            elif tool == "audit_style_consistency":
                profile_id = args.get("profile_id", "")
                contents = args.get("contents", []) or []
                if not profile_id or not contents:
                    return "I need a profile_id and at least one piece of content to audit.", {}
                from apps.creative.style.style_engine import get_style_engine

                result = await get_style_engine().style_consistency_audit(profile_id, contents)
                lines = [f"**Consistency score: {result['consistency_score']:.0%}**"]
                if result["inconsistencies"]:
                    lines.append(
                        "Inconsistencies:\n"
                        + "\n".join(f"  • {i}" for i in result["inconsistencies"])
                    )
                lines.append(f"Recommendation: {result['recommendation']}")
                return "\n".join(lines), {}

            # ── STRATEGIC PRIORITIZATION (persistent action backlog) ────────
            elif tool == "add_priority_action":
                title = args.get("title", "")
                if not title:
                    return "I need at least a title for this action.", {}
                from apps.strategy.prioritization.priority_engine import (
                    StrategyAction,
                    get_priority_engine,
                )

                action = StrategyAction(
                    title=title,
                    description=args.get("description", ""),
                    category=args.get("category", "content"),
                    estimated_roi=float(args.get("estimated_roi", 0.0)),
                    effort_score=float(args.get("effort_score", 5.0)),
                    time_to_result_days=int(args.get("time_to_result_days", 30)),
                    leverage_score=float(args.get("leverage_score", 0.5)),
                    compounding=bool(args.get("compounding", False)),
                )
                saved = await get_priority_engine().add_action(action)
                return (
                    f"Added to the priority backlog: **{saved.title}** "
                    f"(priority score: {saved.priority_score:.1f}/100)"
                ), {}

            elif tool == "top_priorities":
                limit = int(args.get("limit", 5))
                from apps.strategy.prioritization.priority_engine import get_priority_engine

                top = await get_priority_engine().top_priorities(limit=limit)
                if not top:
                    return (
                        "No actions in the priority backlog yet. Use add_priority_action first.",
                        {},
                    )
                lines = ["**Top priorities:**"]
                for i, a in enumerate(top, 1):
                    lines.append(
                        f"  {i}. {a.title} — score {a.priority_score:.1f}/100 ({a.category})"
                    )
                return "\n".join(lines), {}

            elif tool == "allocate_resources":
                total_hours = int(args.get("total_hours", 40))
                total_budget_usd = float(args.get("total_budget_usd", 0))
                from apps.strategy.prioritization.priority_engine import get_priority_engine

                result = await get_priority_engine().allocate_resources(
                    total_hours, total_budget_usd
                )
                if not result["allocations"]:
                    return "No actions to allocate against yet. Use add_priority_action first.", {}
                lines = [f"**Resource allocation** ({total_hours}h, ${total_budget_usd:.0f}):"]
                for a in result["allocations"]:
                    lines.append(
                        f"  • {a['title']}: {a['allocated_hours']}h, "
                        f"${a['allocated_budget_usd']:.0f} (score {a['priority_score']:.1f})"
                    )
                return "\n".join(lines), {}

            # ── PERSUASION / CONVERSION COPY ─────────────────────────────────
            elif tool == "recommend_persuasion_tactics":
                context = args.get("context", "")
                target_emotion = args.get("target_emotion", "desire")
                if not context:
                    return "Tell me what you're trying to persuade someone to do.", {}
                from apps.psychology.conversion.persuasion_engine import get_persuasion_engine

                tactics = await get_persuasion_engine().recommend_tactics(context, target_emotion)
                lines = ["**Recommended persuasion tactics:**"]
                for t in tactics:
                    lines.append(f"  • **{t.title}** ({t.principle.value}): {t.copy_template}")
                return "\n".join(lines), {}

            elif tool == "score_copy_persuasion":
                copy_text = args.get("copy", "")
                if not copy_text:
                    return "I need the copy text to score.", {}
                from apps.psychology.conversion.persuasion_engine import get_persuasion_engine

                result = await get_persuasion_engine().score_copy(copy_text)
                lines = [f"**Persuasion score: {result['persuasion_score']:.2f}/1.0**"]
                if result["principles_detected"]:
                    lines.append(f"Principles detected: {', '.join(result['principles_detected'])}")
                lines.append(result["improvement"])
                return "\n".join(lines), {}

            elif tool == "optimize_cta":
                current_cta = args.get("cta", "")
                principle_raw = args.get("principle", "scarcity")
                if not current_cta:
                    return "I need the current CTA text to optimize.", {}
                from apps.psychology.conversion.persuasion_engine import (
                    PersuasionPrinciple,
                    get_persuasion_engine,
                )

                try:
                    principle = PersuasionPrinciple(principle_raw)
                except ValueError:
                    principle = PersuasionPrinciple.SCARCITY
                variations = await get_persuasion_engine().optimize_cta(current_cta, principle)
                lines = [f"**CTA variations ({principle.value}):**"]
                for v in variations:
                    lines.append(f"  • {v}")
                return "\n".join(lines), {}

            # ── AI RESPONSE QUALITY (evaluation/phoenix) ──────────────────────
            elif tool == "evaluate_ai_response":
                content = args.get("content", "")
                prompt = args.get("prompt", "")
                if not content:
                    return "I need the content to evaluate.", {}
                from apps.evaluation.phoenix.evaluator import get_ai_evaluator

                result = get_ai_evaluator().evaluate(content, prompt)
                lines = [f"**Overall quality: {result.overall_score:.0%}**"]
                lines.append(
                    "Scores:\n" + "\n".join(f"  • {k}: {v:.0%}" for k, v in result.scores.items())
                )
                if result.flags:
                    lines.append("Flags:\n" + "\n".join(f"  • {f}" for f in result.flags))
                if result.recommendations:
                    lines.append(
                        "Recommendations:\n" + "\n".join(f"  • {r}" for r in result.recommendations)
                    )
                return "\n".join(lines), {}

            elif tool == "ai_performance_report":
                from apps.core import auth

                if not auth.is_owner_email(email):
                    return "This action is reserved for ARIA's owner.", {}
                from apps.evaluation.phoenix.tracer import get_cognition_tracer

                stats = await get_cognition_tracer().analytics()
                if stats.get("total_traces", 0) == 0:
                    return "No traced conversation turns yet.", {}
                by_tool = ", ".join(f"{k}: {v}" for k, v in stats.get("by_task", {}).items())
                return (
                    f"**AI performance ({stats['total_traces']} traces)**\n"
                    f"Avg latency: {stats['avg_latency_ms']:.0f}ms · "
                    f"Failure rate: {stats['failure_rate']:.0%}\n"
                    f"Avg quality: {stats['avg_quality_score']:.0%} · "
                    f"Avg hallucination risk: {stats['avg_hallucination_risk']:.0%}\n"
                    f"By tool: {by_tool}"
                ), {}

            # ── GROWTH FORECASTING & LEVERAGE ANALYSIS ───────────────────────
            elif tool == "forecast_revenue":
                initial_revenue = float(args.get("initial_revenue", 0))
                growth_rate = float(args.get("growth_rate", 0.1))
                months = int(args.get("months", 12))
                model_raw = args.get("model", "exponential")
                name = args.get("name", "forecast")
                if initial_revenue <= 0:
                    return "I need a starting monthly revenue greater than $0 to forecast from.", {}
                from apps.strategy.forecasting.strategic_forecaster import (
                    GrowthModel,
                    get_strategic_forecaster,
                )

                try:
                    model = GrowthModel(model_raw)
                except ValueError:
                    model = GrowthModel.EXPONENTIAL
                scenario = await get_strategic_forecaster().forecast(
                    initial_revenue, growth_rate, months, model, name
                )
                breakeven = (
                    f"month {scenario.breakeven_month}"
                    if scenario.breakeven_month
                    else "not reached in this window"
                )
                return (
                    f"**Forecast '{scenario.name}'** ({model.value}, {months} months)\n"
                    f"Total projected revenue: ${scenario.total_projected_revenue:,.0f}\n"
                    f"Breakeven: {breakeven}"
                ), {}

            elif tool == "find_growth_bottleneck":
                metrics = args.get("metrics", {}) or {}
                from apps.strategy.leverage.leverage_analyzer import get_leverage_analyzer

                result = await get_leverage_analyzer().bottleneck_analysis(metrics)
                lines = [
                    f"**Primary bottleneck: {result['primary_bottleneck']}**",
                    f"Impact score: {result['impact_score']}x · "
                    f"Estimated revenue lift: {result['estimated_revenue_lift_pct']}%",
                ]
                if result["fix_priority"]:
                    lines.append(
                        "Fix priority:\n" + "\n".join(f"  • {a}" for a in result["fix_priority"])
                    )
                return "\n".join(lines), {}

            elif tool == "growth_removal_plan":
                bottleneck = args.get("bottleneck", "")
                if not bottleneck:
                    return (
                        "I need the bottleneck name (from find_growth_bottleneck) to plan around.",
                        {},
                    )
                from apps.strategy.leverage.leverage_analyzer import get_leverage_analyzer

                plan = await get_leverage_analyzer().constraint_removal_plan(bottleneck)
                lines = [f"**Removal plan for '{bottleneck}':**"]
                for step in plan:
                    lines.append(
                        f"  {step['step']}. {step['action']} "
                        f"({step['timeframe_days']}d) → {step['expected_outcome']}"
                    )
                return "\n".join(lines), {}

            elif tool == "simulate_growth_lever":
                metrics = args.get("metrics", {}) or {}
                lever = args.get("lever", "")
                improvement_pct = float(args.get("improvement_pct", 10))
                if not lever:
                    return (
                        "I need which lever to simulate (conversion, traffic, order_value, or retention).",
                        {},
                    )
                from apps.strategy.leverage.leverage_analyzer import get_leverage_analyzer

                result = await get_leverage_analyzer().simulate_improvement(
                    metrics, lever, improvement_pct
                )
                return (
                    f"**Simulated {improvement_pct:.0f}% improvement in {lever}:**\n"
                    f"Monthly revenue: ${result['base_monthly_revenue_usd']:,.0f} → "
                    f"${result['projected_monthly_revenue_usd']:,.0f} "
                    f"({result['revenue_lift_pct']:+.1f}%)\n"
                    f"Annualized lift: ${result['annualized_lift_usd']:,.0f}"
                ), {}

            # ── CUSTOMER BEHAVIOR & AUDIENCE PERSONAS ────────────────────────
            elif tool == "analyze_user_behavior":
                user_id = args.get("user_id", "")
                actions = args.get("actions", []) or []
                if not user_id or not actions:
                    return (
                        "I need a user_id and their recent actions (e.g. view, add_to_cart, purchase) to analyze.",
                        {},
                    )
                from apps.psychology.behavior.behavior_analyzer import get_behavior_analyzer

                profile = await get_behavior_analyzer().analyze_user(user_id, actions)
                signals = ", ".join(s.value for s in profile.signals) or "none detected"
                return (
                    f"**Behavior profile for {user_id}**\n"
                    f"Signals: {signals}\n"
                    f"Intent score: {profile.intent_score:.0%} · Churn risk: {profile.churn_probability:.0%} · "
                    f"Predicted LTV: ${profile.predicted_ltv_usd:.0f}\n"
                    f"Next best action: {profile.next_best_action}"
                ), {}

            elif tool == "predict_customer_churn":
                user_id = args.get("user_id", "")
                if not user_id:
                    return (
                        "I need a user_id (analyzed previously via analyze_user_behavior) to predict churn for.",
                        {},
                    )
                from apps.psychology.behavior.behavior_analyzer import get_behavior_analyzer

                result = await get_behavior_analyzer().predict_churn(user_id)
                lines = [f"**Churn risk for {user_id}: {result['churn_probability']:.0%}**"]
                lines.append("Reasons:\n" + "\n".join(f"  • {r}" for r in result["reasons"]))
                lines.append(
                    "Prevention actions:\n"
                    + "\n".join(f"  • {p}" for p in result["prevention_actions"])
                )
                return "\n".join(lines), {}

            elif tool == "generate_audience_personas":
                niche = args.get("niche", "")
                count = int(args.get("count", 3))
                if not niche:
                    return "I need a niche to generate audience personas for.", {}
                from apps.psychology.personas.persona_engine import get_persona_engine

                personas = await get_persona_engine().generate_niche_personas(niche, count)
                lines = [f"**{len(personas)} audience personas for '{niche}':**"]
                for p in personas:
                    lines.append(
                        f"  • **{p.archetype.value}** (id: `{p.persona_id}`) — "
                        f"pain: {p.primary_pain}, desire: {p.primary_desire}"
                    )
                return "\n".join(lines), {}

            elif tool == "match_content_to_persona":
                content = args.get("content", "")
                persona_id = args.get("persona_id", "")
                if not content or not persona_id:
                    return (
                        "I need the content and a persona_id (from generate_audience_personas) to check.",
                        {},
                    )
                from apps.psychology.personas.persona_engine import get_persona_engine

                result = await get_persona_engine().match_content_to_persona(content, persona_id)
                lines = [f"**Persona match: {result['match_score']:.0%}**"]
                if result["alignment_reasons"]:
                    lines.append(
                        "Aligned:\n" + "\n".join(f"  • {a}" for a in result["alignment_reasons"])
                    )
                if result["suggested_tweaks"]:
                    lines.append(
                        "Suggested tweaks:\n"
                        + "\n".join(f"  • {t}" for t in result["suggested_tweaks"])
                    )
                return "\n".join(lines), {}

            # ── PAID ADS: AUDIENCES & CAC ─────────────────────────────────────
            elif tool == "create_ad_audience":
                name = args.get("name", "")
                criteria = args.get("criteria", {}) or {}
                platforms = args.get("platforms") or ["meta"]
                if not name:
                    return "I need a name for this ad audience.", {}
                from apps.ads.audiences.audience_segmenter import get_audience_segmenter

                segment = await get_audience_segmenter().create_segment(name, criteria, platforms)
                return (
                    f"**Audience '{segment.name}'** (id: `{segment.segment_id}`)\n"
                    f"Platforms: {', '.join(segment.platforms)} · "
                    f"Estimated CPM: ${segment.estimated_cpm:.2f} · "
                    f"Est. size: {segment.user_count:,}"
                ), {}

            elif tool == "estimate_ad_cac":
                estimated_cpm = float(args.get("estimated_cpm", 10.0))
                product_price = float(args.get("product_price", 0))
                expected_cvr = float(args.get("expected_cvr", 0.02))
                platform = args.get("platform", "meta")
                if product_price <= 0:
                    return "I need the product price to estimate CAC against.", {}
                from apps.ads.audiences.audience_segmenter import (
                    AudienceSegment,
                    get_audience_segmenter,
                )

                segment = AudienceSegment(estimated_cpm=estimated_cpm, platforms=[platform])
                result = get_audience_segmenter().cac_estimate(segment, product_price, expected_cvr)
                verdict = "profitable" if result["profitable"] else "NOT profitable"
                return (
                    f"**CAC estimate ({platform}): {verdict}**\n"
                    f"CPM ${result['cpm']:.2f} → CPC ${result['cpc']:.2f} → CAC ${result['cac']:.2f}\n"
                    f"Break-even price: ${result['break_even_price']:.2f} (product price: ${product_price:.2f})"
                ), {}

            elif tool == "suggest_ad_targeting":
                product = args.get("product", "")
                niche = args.get("niche", "")
                if not product or not niche:
                    return "I need both a product and a niche to suggest ad targeting.", {}
                from apps.ads.audiences.audience_segmenter import get_audience_segmenter

                segmenter = get_audience_segmenter()
                interests = await segmenter.generate_interest_targeting(product, niche)
                exclusions = segmenter.generate_exclusion_audiences()
                lines = [
                    "**Interest targeting:**\n" + "\n".join(f"  • {i}" for i in interests),
                    "**Exclusion audiences:**\n" + "\n".join(f"  • {e}" for e in exclusions),
                ]
                return "\n\n".join(lines), {}

            # ── RETARGETING ──────────────────────────────────────────────────
            elif tool == "create_retargeting_campaign":
                product_name = args.get("product_name", "")
                audience_type = args.get("audience_type", "product_viewers")
                user_ids = args.get("user_ids", []) or []
                budget_daily_usd = float(args.get("budget_daily_usd", 20.0))
                platform = args.get("platform", "meta")
                if not product_name:
                    return "I need a product name to build a retargeting campaign around.", {}
                from apps.ads.retargeting.retargeting_engine import get_retargeting_engine

                engine = get_retargeting_engine()
                audience = await engine.create_audience(
                    f"{audience_type.replace('_', ' ').title()} — {product_name}",
                    audience_type,
                    user_ids,
                    [platform],
                )
                campaign = await engine.create_campaign(
                    audience, product_name, budget_daily_usd, platform
                )
                return (
                    f"**Retargeting campaign '{campaign.name}'** (id: `{campaign.campaign_id}`)\n"
                    f"Audience: {audience.size} users, est. ROAS {audience.estimated_roas:.1f}x\n"
                    f"Headline: {campaign.headline}\n"
                    f"Copy: {campaign.ad_copy}\n"
                    f"Budget: ${budget_daily_usd:.0f}/day on {platform} · status: {campaign.status}"
                ), {}

            elif tool == "cart_abandonment_sequence":
                cart_items = args.get("cart_items", []) or []
                user_id = args.get("user_id", "")
                if not cart_items or not user_id:
                    return "I need the cart items and a user_id to build this sequence.", {}
                from apps.ads.retargeting.retargeting_engine import get_retargeting_engine

                sequence = await get_retargeting_engine().cart_abandonment_sequence(
                    cart_items, user_id
                )
                lines = [f"**Cart abandonment sequence for {user_id}:**"]
                for step in sequence:
                    lines.append(
                        f"  {step['sequence']}. +{step['delay_hours']}h — {step['headline']}\n"
                        f"     {step['ad_copy']}"
                    )
                return "\n".join(lines), {}

            elif tool == "record_retargeting_metrics":
                campaign_id = args.get("campaign_id", "")
                if not campaign_id:
                    return "I need the campaign_id to record metrics against.", {}
                from apps.ads.retargeting.retargeting_engine import get_retargeting_engine

                ok = await get_retargeting_engine().record_metrics(
                    campaign_id,
                    impressions=int(args.get("impressions", 0)),
                    clicks=int(args.get("clicks", 0)),
                    conversions=int(args.get("conversions", 0)),
                    spend=float(args.get("spend", 0.0)),
                    revenue=float(args.get("revenue", 0.0)),
                )
                if not ok:
                    return f"No retargeting campaign found with id `{campaign_id}`.", {}
                return f"Metrics recorded for campaign `{campaign_id}`.", {}

            elif tool == "retargeting_performance":
                limit = int(args.get("limit", 5))
                from apps.ads.retargeting.retargeting_engine import get_retargeting_engine

                engine = get_retargeting_engine()
                await engine._load()
                analytics = engine.campaign_analytics()
                top = engine.top_performing_campaigns(limit)
                if analytics["total_campaigns"] == 0:
                    return (
                        "No retargeting campaigns yet. Use create_retargeting_campaign first.",
                        {},
                    )
                lines = [
                    f"**Retargeting performance** ({analytics['active_campaigns']}/{analytics['total_campaigns']} active)\n"
                    f"Spend ${analytics['total_spend']:,.0f} → Revenue ${analytics['total_revenue']:,.0f} "
                    f"(ROAS {analytics['avg_roas']:.2f}x) · CAC ${analytics['total_cac']:.2f}",
                    "Top performers:\n"
                    + "\n".join(
                        f"  • {c.get('name', c.get('campaign_id'))} — ROAS {c.get('roas', 0):.2f}x"
                        for c in top
                    ),
                ]
                return "\n\n".join(lines), {}

            # ── SHOPIFY REVENUE SUITE ──────────────────────────────────────────
            elif tool == "recover_abandoned_cart":
                user_id = args.get("user_id", "") or args.get("email", "")
                email = args.get("email", "")
                items = args.get("items", []) or []
                cart_value = float(args.get("cart_value", 0))
                if not email or not items:
                    return (
                        "I need the customer's email and the cart items to build a recovery sequence.",
                        {},
                    )
                from apps.shopify.revenue.cart_recovery import get_cart_recovery_engine

                engine = get_cart_recovery_engine()
                cart = await engine.register_abandoned_cart(user_id, email, items, cart_value)
                sequence = await engine.generate_recovery_sequence(cart)
                lines = [
                    f"**Recovery sequence for {email}** (cart: `{cart.cart_id}`, ${cart_value:.2f})"
                ]
                for e in sequence:
                    lines.append(
                        f"  +{e['delay_hours']}h ({e['discount_pct']:.0%} off) — {e['subject']}"
                    )
                return "\n".join(lines), {}

            elif tool == "create_flash_sale":
                name = args.get("name", "")
                products = args.get("products", []) or []
                discount_pct = float(args.get("discount_pct", 0.2))
                duration_hours = float(args.get("duration_hours", 24))
                if not name or not products:
                    return "I need a sale name and at least one product to create a flash sale.", {}
                from apps.shopify.offers.flash_sale_engine import get_flash_sale_engine

                engine = get_flash_sale_engine()
                prices = {
                    p.get("id", p.get("title", "")): float(p.get("price", 0)) for p in products
                }
                sale = await engine.create_sale(
                    name,
                    [p.get("id", p.get("title", "")) for p in products],
                    discount_pct,
                    duration_hours,
                    prices,
                )
                copy = await engine.create_urgency_copy(sale)
                return (
                    f"**Flash sale '{sale.name}'** (id: `{sale.sale_id}`, status: {sale.status})\n"
                    f"{len(sale.product_ids)} products at {discount_pct:.0%} off, {duration_hours:.0f}h\n"
                    f"Urgency copy: {copy}"
                ), {}

            elif tool == "create_product_bundle":
                products = args.get("products", []) or []
                bundle_type = args.get("bundle_type", "complementary")
                discount_pct = float(args.get("discount_pct", 0.15))
                if len(products) < 2:
                    return "I need at least 2 products to build a bundle.", {}
                from apps.shopify.bundles.bundle_generator import get_bundle_generator

                bundle = await get_bundle_generator().create_bundle(
                    products, bundle_type, discount_pct
                )
                return (
                    f"**{bundle.name}** (id: `{bundle.bundle_id}`, {bundle.bundle_type})\n"
                    f"{bundle.description}\n"
                    f"${bundle.individual_total:.2f} → ${bundle.bundle_price:.2f} "
                    f"(save ${bundle.savings:.2f}, {bundle.savings_pct:.0f}%)\n"
                    f"CTA: {bundle.cta}"
                ), {}

            elif tool == "recommend_products":
                user_id = args.get("user_id", "")
                context = args.get("context", "homepage")
                catalog = args.get("catalog", []) or []
                current_product_id = args.get("current_product_id", "")
                limit = int(args.get("limit", 5))
                if not catalog:
                    return "I need a product catalog to recommend from.", {}
                from apps.shopify.revenue.product_recommender import get_product_recommender

                result = await get_product_recommender().recommend(
                    user_id, context, catalog, current_product_id, limit
                )
                if not result.recommended_ids:
                    return (
                        f"No recommendations available for context '{context}' from this catalog.",
                        {},
                    )
                lines = [f"**Recommendations ({result.strategy}, {context}):**"]
                for title, score in zip(result.recommended_titles, result.scores):
                    lines.append(f"  • {title or '(untitled)'} — match {score:.0%}")
                return "\n".join(lines), {}

            elif tool == "shopify_revenue_dashboard":
                from apps.shopify.bundles.bundle_generator import get_bundle_generator
                from apps.shopify.offers.flash_sale_engine import get_flash_sale_engine
                from apps.shopify.revenue.cart_recovery import get_cart_recovery_engine
                from apps.shopify.revenue.product_recommender import get_product_recommender

                cart_engine = get_cart_recovery_engine()
                await cart_engine._load()
                sale_engine = get_flash_sale_engine()
                await sale_engine._load()
                bundle_engine = get_bundle_generator()
                await bundle_engine._load()
                rec_engine = get_product_recommender()
                await rec_engine._load()

                cart_stats = cart_engine.recovery_stats()
                sale_stats = sale_engine.sales_analytics()
                bundle_stats = bundle_engine.bundle_stats()
                rec_stats = rec_engine.recommendation_stats()
                return (
                    f"**Shopify revenue dashboard**\n"
                    f"Cart recovery: {cart_stats['recovered']}/{cart_stats['total_abandoned']} recovered "
                    f"({cart_stats['recovery_rate']:.0%}), ${cart_stats['revenue_recovered']:,.2f} recovered\n"
                    f"Flash sales: {sale_stats['active_count']} active, "
                    f"${sale_stats['total_revenue']:,.2f} total revenue\n"
                    f"Bundles: {bundle_stats['total_bundles']} created, "
                    f"avg {bundle_stats['avg_savings_pct']:.0f}% savings\n"
                    f"Recommendations: {rec_stats['users_tracked']} users tracked, "
                    f"{rec_stats['total_recommendations']} interactions"
                ), {}

            # ── LEAD DISCOVERY & PROPOSALS ─────────────────────────────────────
            elif tool == "discover_leads":
                niche = args.get("niche", "")
                count = int(args.get("count", 10))
                location = args.get("location", "US")
                if not niche:
                    return "I need a niche to search for leads in.", {}
                from apps.acquisition.scraper.lead_scraper import get_lead_scraper

                batch = await get_lead_scraper().scrape_leads(niche, count, location)
                if not batch.raw_leads:
                    return f"No leads found for '{niche}'.", {}
                lines = [
                    f"**{batch.leads_qualified}/{batch.leads_found} qualified leads for '{niche}'** "
                    f"({', '.join(batch.sources_checked)})"
                ]
                for lead in batch.raw_leads:
                    tag = "web search" if lead["source"] == "duckduckgo" else "illustrative example"
                    signals = ", ".join(lead["signals"][:3]) or "no signals detected"
                    lines.append(f"  • {lead['company_name']} [{tag}] — {signals}")
                return "\n".join(lines), {}

            elif tool == "generate_sales_proposal":
                company_name = args.get("company_name", "")
                niche = args.get("niche", "")
                pain_points = args.get("pain_points", []) or []
                services_needed = args.get("services_needed", []) or []
                estimated_value_usd = float(args.get("estimated_value_usd", 0))
                if not company_name:
                    return "I need the company name to write a proposal for.", {}
                from apps.acquisition.leads.lead_engine import Lead, get_lead_engine

                lead = Lead(
                    company_name=company_name,
                    niche=niche,
                    pain_points=pain_points,
                    services_needed=services_needed,
                    estimated_value_usd=estimated_value_usd,
                )
                brief = await get_lead_engine().generate_proposal_brief(lead)
                return (
                    f"**Proposal brief for {company_name}**\n"
                    f"Subject: {brief.subject_line}\n"
                    f"Opening: {brief.opening_hook}\n"
                    f"Pain identified: {brief.pain_identified}\n"
                    f"Solution: {brief.solution_summary}\n"
                    f"Social proof: {brief.social_proof}\n"
                    f"CTA: {brief.cta}"
                ), {}

            # ── LINKEDIN OUTREACH ────────────────────────────────────────────
            elif tool == "add_linkedin_prospect":
                name = args.get("name", "")
                title = args.get("title", "")
                company = args.get("company", "")
                industry = args.get("industry", "")
                profile_url = args.get("profile_url", "")
                if not name or not company:
                    return "I need at least a name and company to add this prospect.", {}
                from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

                prospect = await get_linkedin_outreach().add_prospect(
                    name, title, company, industry, profile_url
                )
                return (
                    f"**Added prospect '{prospect.name}'** (id: `{prospect.prospect_id}`)\n"
                    f"{prospect.title} at {prospect.company} ({prospect.industry})"
                ), {}

            elif tool == "score_linkedin_prospect":
                prospect_id = args.get("prospect_id", "")
                service_offered = args.get("service_offered", "")
                if not prospect_id or not service_offered:
                    return (
                        "I need a prospect_id and what service you're offering to score this prospect.",
                        {},
                    )
                from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

                prospect = await get_linkedin_outreach().score_prospect(
                    prospect_id, service_offered
                )
                return (
                    f"**{prospect.name}: {prospect.relevance_score:.0%} relevance**\n"
                    f"Likely pain point: {prospect.pain_point_hypothesis}"
                ), {}

            elif tool == "generate_linkedin_connection_request":
                prospect_id = args.get("prospect_id", "")
                service = args.get("service", "")
                if not prospect_id or not service:
                    return "I need a prospect_id and the service being offered.", {}
                from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

                msg = await get_linkedin_outreach().generate_connection_request(
                    prospect_id, service
                )
                return f"**Connection request** ({len(msg.body)} chars):\n{msg.body}", {}

            elif tool == "generate_linkedin_outreach_sequence":
                prospect_id = args.get("prospect_id", "")
                service = args.get("service", "")
                if not prospect_id or not service:
                    return "I need a prospect_id and the service being offered.", {}
                from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

                messages = await get_linkedin_outreach().generate_outreach_sequence(
                    prospect_id, service
                )
                lines = ["**4-message LinkedIn outreach sequence:**"]
                for m in messages:
                    lines.append(f"  {m.message_type} — {m.subject}\n    {m.body}")
                return "\n".join(lines), {}

            elif tool == "linkedin_outreach_pipeline":
                min_score = float(args.get("min_score", 0.7))
                from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

                outreach = get_linkedin_outreach()
                await outreach._load()
                analytics = outreach.outreach_analytics()
                hot = outreach.hot_prospects(min_score)
                if analytics["total_prospects"] == 0:
                    return "No LinkedIn prospects yet. Use add_linkedin_prospect first.", {}
                lines = [
                    f"**LinkedIn pipeline** ({analytics['total_prospects']} prospects)\n"
                    f"Avg relevance: {analytics['avg_relevance_score']:.0%} · "
                    f"Connection rate: {analytics['connection_rate_pct']:.0f}% · "
                    f"Reply rate: {analytics['reply_rate_pct']:.0f}%",
                    (
                        f"Hot prospects (≥{min_score:.0%}):\n"
                        + "\n".join(
                            f"  • {p['name']} at {p['company']} — {p['relevance_score']:.0%}"
                            for p in hot
                        )
                        if hot
                        else f"No prospects above {min_score:.0%} relevance yet."
                    ),
                ]
                return "\n\n".join(lines), {}

            # ── LANDING PAGES ────────────────────────────────────────────────
            elif tool == "create_landing_page":
                product = args.get("product", "")
                offer = args.get("offer", "")
                target_audience = args.get("target_audience", "")
                price = float(args.get("price", 0))
                if not product or not offer:
                    return "I need at least a product and an offer to build a landing page.", {}
                from apps.conversion.landing_pages.landing_page_engine import (
                    get_landing_page_engine,
                )

                page = await get_landing_page_engine().create_page(
                    product, offer, target_audience, price
                )
                bullets = "\n".join(f"  • {b}" for b in page.bullet_points)
                return (
                    f"**{page.headline}** (id: `{page.page_id}`, est. CVR {page.estimated_cvr_pct:.1f}%)\n"
                    f"{page.subheadline}\n\n{page.hero_copy}\n\n{bullets}\n\n"
                    f"{page.social_proof} · {page.urgency_trigger}\n"
                    f"CTA: {page.cta_primary} / {page.cta_secondary}\n\n"
                    f"⚠ Placeholder numbers (customer counts, spots remaining) are templates — "
                    f"replace with real figures or remove before publishing."
                ), {}

            elif tool == "generate_landing_headlines":
                product = args.get("product", "")
                audience = args.get("audience", "")
                count = int(args.get("count", 5))
                if not product:
                    return "I need a product to generate headline variants for.", {}
                from apps.conversion.landing_pages.landing_page_engine import (
                    get_landing_page_engine,
                )

                variants = await get_landing_page_engine().generate_headline_variants(
                    product, audience, count
                )
                lines = ["**Headline variants:**"] + [
                    f"  {i}. {v}" for i, v in enumerate(variants, 1)
                ]
                return "\n".join(lines), {}

            elif tool == "landing_page_stats":
                from apps.conversion.landing_pages.landing_page_engine import (
                    get_landing_page_engine,
                )

                engine = get_landing_page_engine()
                await engine._load()
                stats = engine.page_stats()
                if stats["total_pages"] == 0:
                    return "No landing pages yet. Use create_landing_page first.", {}
                by_variant = ", ".join(f"{k}: {v}" for k, v in stats["by_variant"].items())
                return (
                    f"**Landing pages: {stats['total_pages']}** "
                    f"(avg est. CVR {stats['avg_estimated_cvr_pct']:.1f}%)\n"
                    f"By variant: {by_variant}"
                ), {}

            # ── PRICING INTELLIGENCE ─────────────────────────────────────────
            elif tool == "analyze_pricing":
                product_name = args.get("product_name", "") or args.get("product", "")
                category = args.get("category", "")
                our_price = float(args.get("our_price", 0))
                competitor_data = (
                    args.get("competitors", []) or args.get("competitor_data", []) or []
                )
                if not product_name or our_price <= 0:
                    return "I need the product name and our current price to analyze pricing.", {}
                from apps.market.pricing.pricing_intelligence import get_pricing_intelligence

                pp = await get_pricing_intelligence().analyze_pricing(
                    product_name, category, our_price, competitor_data
                )
                return (
                    f"**{pp.product_name}: {pp.positioning}** (${pp.our_price:.2f})\n"
                    f"Market: ${pp.market_min:.2f} - ${pp.market_max:.2f} (avg ${pp.market_avg:.2f})\n"
                    f"Recommended price: ${pp.recommended_price:.2f}"
                ), {}

            elif tool == "suggest_dynamic_price":
                product = args.get("product", "")
                inventory_level = args.get("inventory_level", "normal")
                demand_signal = args.get("demand_signal", "stable")
                if not product:
                    return (
                        "I need a product (already analyzed via analyze_pricing) to suggest a price for.",
                        {},
                    )
                from apps.market.pricing.pricing_intelligence import get_pricing_intelligence

                result = await get_pricing_intelligence().dynamic_price_suggestion(
                    product, inventory_level, demand_signal
                )
                return (
                    f"**Suggested price: ${result['suggested_price']:.2f}** "
                    f"({result['adjustment_pct']:+.1f}%)\n{result['reasoning']}"
                ), {}

            elif tool == "build_pricing_strategy":
                niche = args.get("niche", "")
                product_type = args.get("product_type", "")
                target_margin_pct = float(args.get("target_margin_pct", 60.0))
                if not niche or not product_type:
                    return "I need a niche and product type to build a pricing strategy.", {}
                from apps.market.pricing.pricing_intelligence import get_pricing_intelligence

                strategy = await get_pricing_intelligence().build_strategy(
                    niche, product_type, target_margin_pct
                )
                return (
                    f"**{strategy.strategy_type.replace('_', ' ').title()} pricing strategy for {niche}**\n"
                    f"${strategy.initial_price:.2f} → ${strategy.target_price:.2f}\n"
                    f"{strategy.rationale[:300]}"
                ), {}

            elif tool == "pricing_dashboard":
                from apps.market.pricing.pricing_intelligence import get_pricing_intelligence

                engine = get_pricing_intelligence()
                await engine._load()
                stats = engine.pricing_dashboard()
                gaps = engine.competitive_gaps()
                if stats["total_price_points"] == 0:
                    return "No pricing analyses yet. Use analyze_pricing first.", {}
                by_pos = ", ".join(f"{k}: {v}" for k, v in stats["by_positioning"].items())
                lines = [
                    f"**Pricing dashboard** ({stats['total_price_points']} products, "
                    f"avg ${stats['avg_price']:.2f})\nBy positioning: {by_pos}"
                ]
                if gaps:
                    lines.append(
                        "Overpriced vs. recommendation:\n"
                        + "\n".join(
                            f"  • {g['product_name']} — ${g['our_price']:.2f} vs "
                            f"recommended ${g['recommended_price']:.2f}"
                            for g in gaps
                        )
                    )
                return "\n\n".join(lines), {}

            # ── FREELANCE GIGS: FIVERR ──────────────────────────────────────────
            elif tool == "create_fiverr_gig":
                service_type = args.get("service_type", "")
                niche = args.get("niche", "")
                if not service_type or not niche:
                    return "I need both a service type and a niche to build a Fiverr gig.", {}
                from apps.acquisition.fiverr.fiverr_optimizer import get_fiverr_optimizer

                gig = await get_fiverr_optimizer().create_gig(service_type, niche)
                pkgs = ", ".join(
                    f"{name}: ${p['price']} ({p['delivery_days']}d)"
                    for name, p in gig.packages.items()
                )
                return (
                    f"**{gig.title}** (id: `{gig.gig_id}`, SEO score {gig.seo_score:.0%})\n"
                    f"Packages: {pkgs}\n"
                    f"Tags: {', '.join(gig.tags)}\n\n"
                    f"⚠ Package prices are baseline templates — adjust for your actual market."
                ), {}

            elif tool == "optimize_fiverr_title":
                current_title = args.get("current_title", "")
                keyword = args.get("keyword", "")
                if not current_title or not keyword:
                    return "I need the current title and target keyword to optimize it.", {}
                from apps.acquisition.fiverr.fiverr_optimizer import get_fiverr_optimizer

                optimized = await get_fiverr_optimizer().optimize_gig_title(current_title, keyword)
                return f"**Optimized title:** {optimized}", {}

            elif tool == "fiverr_gig_analytics":
                from apps.acquisition.fiverr.fiverr_optimizer import get_fiverr_optimizer

                engine = get_fiverr_optimizer()
                await engine._load()
                stats = engine.gig_analytics()
                if stats["total_gigs"] == 0:
                    return "No Fiverr gigs yet. Use create_fiverr_gig first.", {}
                return (
                    f"**Fiverr gigs: {stats['total_gigs']}** ({stats['active']} active)\n"
                    f"Avg SEO score: {stats['avg_seo_score']:.0%} · "
                    f"Categories: {', '.join(stats['categories'])}"
                ), {}

            # ── FREELANCE GIGS: UPWORK ───────────────────────────────────────
            elif tool == "evaluate_upwork_job":
                title = args.get("title", "")
                description = args.get("description", "")
                budget_min = float(args.get("budget_min", 0))
                budget_max = float(args.get("budget_max", 0))
                skills_required = args.get("skills_required", []) or []
                our_skills = args.get("our_skills", []) or []
                if not title:
                    return "I need the job title to evaluate it.", {}
                from apps.acquisition.upwork.upwork_bidder import get_upwork_bidder

                job = await get_upwork_bidder().evaluate_job(
                    title, description, budget_min, budget_max, skills_required, our_skills
                )
                return (
                    f"**{job.title}** (id: `{job.job_id}`)\n"
                    f"Fit score: {job.fit_score:.0%} · Suggested bid: ${job.bid_price:.2f}"
                ), {}

            elif tool == "write_upwork_proposal":
                job_id = args.get("job_id", "")
                our_expertise = args.get("our_expertise", "")
                if not job_id or not our_expertise:
                    return (
                        "I need a job_id (from evaluate_upwork_job) and our relevant expertise.",
                        {},
                    )
                from apps.acquisition.upwork.upwork_bidder import get_upwork_bidder

                proposal = await get_upwork_bidder().write_proposal(job_id, our_expertise)
                return (
                    f"**Proposal** (bid: ${proposal.bid_amount:.2f}, {proposal.delivery_days}d delivery)\n"
                    f"{proposal.body}"
                ), {}

            elif tool == "optimize_upwork_profile":
                skills = args.get("skills", []) or []
                specialization = args.get("specialization", "")
                if not skills or not specialization:
                    return (
                        "I need your skills and specialization to optimize an Upwork profile.",
                        {},
                    )
                from apps.acquisition.upwork.upwork_bidder import get_upwork_bidder

                result = await get_upwork_bidder().generate_profile_optimization(
                    skills, specialization
                )
                return (
                    f"**Headline:** {result['headline']}\n\n"
                    f"**Overview:**\n{result['overview']}\n\n"
                    f"**Portfolio ideas:**\n"
                    + "\n".join(f"  • {p}" for p in result["portfolio_suggestions"])
                ), {}

            elif tool == "upwork_bidding_analytics":
                from apps.acquisition.upwork.upwork_bidder import get_upwork_bidder

                engine = get_upwork_bidder()
                await engine._load()
                stats = engine.bidding_analytics()
                if stats["total_jobs"] == 0:
                    return "No Upwork jobs tracked yet. Use evaluate_upwork_job first.", {}
                return (
                    f"**Upwork bidding: {stats['bids_sent']}/{stats['total_jobs']} bid on** "
                    f"({stats['win_rate_pct']:.0f}% win rate)\n"
                    f"Avg bid: ${stats['avg_bid']:.2f} · Total won value: ${stats['total_won_value']:,.2f}"
                ), {}

            # ── CLIENT MEMORY (CRM) ──────────────────────────────────────────
            elif tool == "upsert_client_profile":
                name = args.get("name", "")
                email = args.get("email", "")
                company = args.get("company", "")
                industry = args.get("industry", "")
                if not name or not email:
                    return "I need at least a name and email to save this client profile.", {}
                from apps.memory.client.client_memory import get_client_memory

                profile = await get_client_memory().upsert_profile(name, email, company, industry)
                return (
                    f"**Client profile saved: {profile.name}** (id: `{profile.profile_id}`)\n"
                    f"{profile.email} · {profile.company or 'no company'} · segment: {profile.segment}"
                ), {}

            elif tool == "record_client_interaction":
                profile_id = args.get("profile_id", "")
                interaction_type = args.get("interaction_type", "")
                summary = args.get("summary", "")
                value_usd = float(args.get("value_usd", 0))
                if not profile_id or not interaction_type:
                    return "I need a profile_id and an interaction type to record this.", {}
                from apps.memory.client.client_memory import get_client_memory

                interaction = await get_client_memory().record_interaction(
                    profile_id, interaction_type, summary, value_usd
                )
                return (
                    f"**{interaction.interaction_type}** recorded ({interaction.sentiment})"
                    + (f", ${value_usd:.2f}" if value_usd else "")
                ), {}

            elif tool == "segment_client":
                profile_id = args.get("profile_id", "")
                if not profile_id:
                    return "I need a profile_id (from upsert_client_profile) to segment.", {}
                from apps.memory.client.client_memory import get_client_memory

                segment = await get_client_memory().segment_client(profile_id)
                return f"**Segment: {segment}**", {}

            elif tool == "personalize_client_offer":
                profile_id = args.get("profile_id", "")
                available_products = args.get("available_products", []) or []
                if not profile_id or not available_products:
                    return (
                        "I need a profile_id and the available products to personalize an offer.",
                        {},
                    )
                from apps.memory.client.client_memory import get_client_memory

                result = await get_client_memory().personalize_offer(profile_id, available_products)
                return (
                    f"**Recommended: {result['recommended_product']}** — {result['offer']}\n"
                    f"{result['reasoning']}"
                ), {}

            elif tool == "client_memory_dashboard":
                from apps.memory.client.client_memory import get_client_memory

                memory = get_client_memory()
                await memory._load()
                stats = memory.client_memory_summary()
                vip = memory.vip_clients()
                at_risk = memory.at_risk_clients()
                if stats["total_profiles"] == 0:
                    return "No client profiles yet. Use upsert_client_profile first.", {}
                by_segment = ", ".join(f"{k}: {v}" for k, v in stats["by_segment"].items())
                lines = [
                    f"**Client memory: {stats['total_profiles']} profiles, "
                    f"{stats['total_interactions']} interactions**\n"
                    f"By segment: {by_segment} · Total LTV: ${stats['total_ltv']:,.2f}"
                ]
                if vip:
                    lines.append("VIP: " + ", ".join(p["name"] for p in vip[:10]))
                if at_risk:
                    lines.append("At risk / churned: " + ", ".join(p["name"] for p in at_risk[:10]))
                return "\n\n".join(lines), {}

            # ── MULTI-AGENT CREW ────────────────────────────────────────────
            elif tool == "run_crew":
                mission = args.get("mission", "")
                crew_name = args.get("crew", "research_crew")
                from apps.core.tools.crew_engine import get_crew_engine
                from apps.core.tools.deep_think import ProgressStream

                ps = ProgressStream(session_id="", task_name=f"Crew:{crew_name}")
                run = await get_crew_engine().run(
                    mission=mission,
                    crew_name=crew_name,
                    on_progress=lambda step, total, role: ps.update(
                        f"{role} working...", f"Step {step}/{total}"
                    ),
                )
                members_summary = " → ".join(m.role for m in run.members)
                obs = (
                    f"[CREW: {crew_name.upper()} — {members_summary}]\n\n"
                    f"{run.final_output or 'No final output'}"
                )
                return obs, {}

            # ── WORKFLOW ENGINE ───────────────────────────────────────────
            elif tool == "create_workflow":
                name = args.get("name", "Workflow")
                description = args.get("description", "")
                from apps.core.tools.workflow_engine import get_workflow_engine

                r = await get_workflow_engine().create(name, description)
                if r.get("success"):
                    steps_str = "\n".join(
                        f"  {i+1}. {s}" for i, s in enumerate(r.get("steps_preview", []))
                    )
                    return (
                        f"Workflow '{name}' created (ID: {r['workflow_id']}, {r['steps']} steps):\n"
                        f"{steps_str}\n\nUse run_workflow with id='{r['workflow_id']}' to run it."
                    ), {}
                return f"I couldn't create the workflow: {r.get('error', 'error')}", {}

            elif tool == "run_workflow":
                wid = args.get("workflow_id", "")
                from apps.core.tools.workflow_engine import get_workflow_engine

                r = await get_workflow_engine().run(wid)
                if "results" in r:
                    steps_summary = "; ".join(
                        f"step{s['step']}={'OK' if s['success'] else 'FAIL'}"
                        for s in r.get("results", [])
                    )
                    status = "" if r.get("success") else " (with errors)"
                    return (
                        f"[WORKFLOW '{r.get('name', wid)}'{status} — {r['steps_run']} steps]\n"
                        f"{steps_summary}\n\n{r.get('final_output', '')}"
                    ), {}
                return f"Error running workflow: {r.get('error', 'error')}", {}

            elif tool == "list_workflows":
                from apps.core.tools.workflow_engine import get_workflow_engine

                wfs = get_workflow_engine().list()
                if not wfs:
                    return "No saved workflows. Use create_workflow to create one.", {}
                lines = [
                    f"• [{w['id']}] **{w['name']}** — {w['description'][:60]} (runs: {w['run_count']})"
                    for w in wfs
                ]
                return "[WORKFLOWS]\n" + "\n".join(lines), {}

            # ── THINK VERIFIED (Test-Time Compute) ────────────────────────
            elif tool == "think_verified":
                question = args.get("question", "")
                context = args.get("context", "")
                from apps.core.tools.deep_think import get_deep_think

                result = await get_deep_think().think_verified(question, context=context, paths=2)
                obs = f"[VERIFIED REASONING — {result.depth.upper()} — {result.duration_ms}ms]\n{result.answer}"
                return obs, {}

            # ── NICHE REVENUE ENGINE ─────────────────────────────────────
            elif tool == "launch_niche":
                niche = args.get("niche", "")
                context = args.get("context", "")
                if not niche:
                    from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                    top5 = get_niche_revenue_engine().get_top_niches_by_potential(n=3)
                    names = [n["key"] for n in top5]
                    return (
                        f"Specify a niche. Top 3 recommended right now: {', '.join(names)}\n"
                        f"Use list_niches to see all 45 available."
                    ), {}
                from apps.core.tools.niche_revenue_engine import (
                    NICHE_CATALOG,
                    get_niche_revenue_engine,
                )

                if niche not in NICHE_CATALOG:
                    close = [k for k in NICHE_CATALOG if niche.lower() in k.lower()]
                    return (
                        f"Niche '{niche}' not found."
                        + (f" Did you mean: {', '.join(close[:3])}?" if close else "")
                    ), {}
                result = await get_niche_revenue_engine().launch_niche(niche, context=context)
                lines = [
                    f"[LAUNCH: {result.niche_name}]",
                    f"Checklist: {result.checklist.score}/100 {'OK' if result.checklist and result.checklist.passed else 'needs review'}",
                    f"Time: {result.elapsed_seconds}s",
                ]
                if result.published_urls:
                    lines.append("**Published to:**")
                    for u in result.published_urls:
                        lines.append(f"  • {u['platform']}: {u['url']}")
                if result.seo_article_urls:
                    lines.append("**SEO articles:**")
                    for u in result.seo_article_urls:
                        lines.append(f"  • {u['platform']}: {u['url']}")
                if result.errors:
                    lines.append(f"Warnings: {'; '.join(result.errors[:3])}")
                if result.listing:
                    lines.append(f"\n**Listing:** {result.listing.title}")
                    lines.append(
                        f"Price: ${result.listing.pricing_tiers['basic']['price']} – ${result.listing.pricing_tiers['premium']['price']}"
                    )
                return "\n".join(lines), {}

            elif tool == "income_dashboard":
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                return get_niche_revenue_engine().income_dashboard(), {}

            elif tool == "list_niches":
                category = args.get("category")
                tier = args.get("tier")
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                return get_niche_revenue_engine().list_all_niches(category=category, tier=tier), {}

            elif tool == "auto_income":
                num_niches = int(args.get("num_niches", 3))
                from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine

                result = await get_niche_revenue_engine().autonomous_income_cycle(
                    num_niches=num_niches
                )
                lines = [
                    "[AUTO INCOME CYCLE]",
                    f"Niches attempted: {result['niches_attempted']}",
                    f"Niches succeeded: {result['niches_succeeded']}",
                    f"Live listings: {result['total_listings_live']}",
                    f"Articles published: {result['total_content_published']}",
                    f"Time: {result['elapsed_seconds']}s",
                ]
                if result.get("all_live_urls"):
                    lines.append("\n**Active URLs:**")
                    for u in result["all_live_urls"][:8]:
                        lines.append(f"  • {u.get('platform')}: {u.get('url')}")
                if result.get("successful_niches"):
                    lines.append("\n**Niches launched:**")
                    for n in result["successful_niches"]:
                        lines.append(
                            f"  - {n['niche']} — potential ${n.get('revenue_potential',0)}/sale"
                        )
                if result.get("failed_niches"):
                    lines.append("\n**Niches with errors:**")
                    for n in result["failed_niches"]:
                        lines.append(f"  - {n['niche']}: {', '.join(n.get('errors',[])[:2])}")
                return "\n".join(lines), {}

            # ── INCOME LOOP 24/7 ──────────────────────────────────────────
            elif tool == "income_loop_status":
                from apps.core.tools.income_loop import get_income_loop

                return get_income_loop().get_status(), {}

            elif tool == "start_income_loop":
                from apps.core.tools.income_loop import get_income_loop

                loop = get_income_loop()
                if loop.is_running:
                    return (
                        "The 24/7 income loop is already running. Use income_loop_status to check its state.",
                        {},
                    )
                await loop.start()
                return (
                    "24/7 income loop started. It will run revenue strategies every 30 minutes autonomously.",
                    {},
                )

            elif tool == "run_income_cycle":
                from apps.core.tools.income_loop import STRATEGIES, get_income_loop

                loop = get_income_loop()
                strategy = args.get("strategy", "")
                valid = [s[0] for s in STRATEGIES]
                if strategy and strategy not in valid:
                    return f"Invalid strategy. Options: {', '.join(valid)}", {}
                import random as _rnd

                if not strategy:
                    strategy = _rnd.choices(
                        [s[0] for s in STRATEGIES], weights=[s[1] for s in STRATEGIES], k=1
                    )[0]
                obs = await loop._execute(strategy)
                lines = [
                    f"[INCOME CYCLE — {strategy}]",
                    f"Success: {'yes' if obs.get('success') else 'no'}",
                    f"Summary: {obs.get('summary', '')}",
                    f"Revenue potential: ${obs.get('revenue_potential', 0):.0f}",
                ]
                if obs.get("urls"):
                    lines.append("URLs:")
                    for u in obs["urls"][:4]:
                        lines.append(f"  • {u}")
                return "\n".join(lines), {}

            # ── GITHUB ───────────────────────────────────────────────────
            elif tool in (
                "github_view",
                "github_write",
                "github_pr",
                "github_issues",
                "github_search",
                "github_self",
            ):
                from apps.core.tools.github_client import github_dispatch

                action_map = {
                    "github_view": args.get("action", "view"),
                    "github_write": "write",
                    "github_pr": args.get("action", "create_pr"),
                    "github_issues": args.get("action", "issues"),
                    "github_search": "search",
                    "github_self": "self",
                }
                gh_action = action_map[tool]
                obs = await github_dispatch(gh_action, args)
                return obs, {}

        except Exception as exc:
            logger.error("[AriaMind] tool=%s: %s", tool, exc, exc_info=True)
            return f"I couldn't complete the '{tool}' action — please try again.", {}

        return "Unknown tool", {}

    # ── SYNTHESIS ────────────────────────────────────────────────────────────

    async def _synthesize(self, user_input: str, tool: str, observation: str) -> str:
        """Turns a tool's raw observation into a natural reply via the LLM."""
        if not observation or len(observation) < 10:
            return "Done."

        ai = self._ai_client()
        if not ai:
            return observation[:400]

        from apps.core.tools.ai_client import AIModel

        resp = await ai.complete(
            system=SYNTHESIS_SYSTEM,
            user=(
                f"The user asked: {user_input[:400]}\n"
                f"I used the '{tool}' tool and got:\n{observation[:2000]}"
                f"{self._lang_directive(user_input)}"
            ),
            model=AIModel.STRATEGY,
            max_tokens=800,
            temperature=0.35,
            agent_name="aria_synthesis",
            prefer_quality=True,
        )
        if resp and resp.success and resp.content:
            return resp.content.strip()
        return observation[:600]

    async def _fallback_reply(self, text: str) -> str:
        """Generates a direct, useful reply when the plan didn't include one."""
        ai = self._ai_client()
        if not ai:
            return "Got it."
        from apps.core.tools.ai_client import AIModel

        resp = await ai.complete(
            system=(
                "You are ARIA. Talk like a real person — warm, direct, genuinely curious — "
                "not like a corporate assistant. First person, contractions, human rhythm. "
                'No "As an AI...", no hedge-everything caveats, no restating the question '
                'before answering, no closing with "I hope this helps!" or similar filler. '
                "Have an actual opinion when asked for one instead of listing both sides and "
                "declining to pick. Reply in the SAME language as the user, directly and "
                "completely. Use markdown when it helps. If you'd need live internet data you "
                "don't have here, say so plainly and suggest what to search for."
            ),
            user=text + self._lang_directive(text),
            model=AIModel.STRATEGY,
            max_tokens=800,
            temperature=0.4,
            agent_name="aria_fallback",
            prefer_quality=True,
        )
        return resp.content.strip() if (resp and resp.success) else "Got it — one moment."

    # ── COGNITIVE STATE MANAGEMENT ───────────────────────────────────────────

    async def _load_state(self, chat_id: str) -> dict:
        cache = self._cache_client()
        if cache:
            s = await cache.get(self.K_STATE.format(cid=chat_id))
            if isinstance(s, dict):
                return s
        return {"focus": "", "confidence": 0.7, "interaction_count": 0}

    async def _evolve_state(
        self, chat_id: str, current: dict, text: str, goals: list[dict]
    ) -> None:
        """Updates the cognitive state after each interaction."""
        cache = self._cache_client()
        if not cache:
            return

        # Update the counter
        current["interaction_count"] = current.get("interaction_count", 0) + 1

        # Update focus (first 60 chars of the current text)
        current["focus"] = text[:60]

        # Confidence climbs slowly toward 1.0 with each success
        current["confidence"] = min(1.0, current.get("confidence", 0.7) + 0.01)

        await cache.set(self.K_STATE.format(cid=chat_id), current, ttl_seconds=86400 * 30)

    async def _load_goals(self) -> list[dict]:
        cache = self._cache_client()
        if cache:
            g = await cache.get(self.K_GOALS)
            if isinstance(g, list):
                return [x for x in g if isinstance(x, dict)]
        return []

    async def _save_goals(self, goals: list[dict]) -> None:
        cache = self._cache_client()
        if cache:
            await cache.set(self.K_GOALS, goals, ttl_seconds=86400 * 365)

    async def _apply_goal_action(self, action: dict, goals: list[dict]) -> list[dict]:
        if action.get("action") == "add":
            goals.append(
                Goal(
                    text=action.get("text", ""),
                    priority=int(action.get("priority", 5)),
                ).__dict__
            )
            await self._save_goals(goals)
        elif action.get("action") == "update":
            idx = action.get("index", 0)
            if 0 <= idx < len(goals):
                if "progress" in action:
                    goals[idx]["progress"] = action["progress"]
                if "status" in action:
                    goals[idx]["status"] = action["status"]
                await self._save_goals(goals)
        return goals

    async def _load_learned(self) -> list[str]:
        cache = self._cache_client()
        if cache:
            l = await cache.get(self.K_LEARNED)
            if isinstance(l, list):
                return l
        return []

    async def _clear_conversation(self, chat_id: str) -> None:
        """Actually reset this chat's history/state (goals and learned rules
        are global, persistent memory — /clear must not touch those)."""
        cache = self._cache_client()
        if not cache:
            return
        with suppress(Exception):
            await cache.delete(self.K_HISTORY.format(cid=chat_id))
        with suppress(Exception):
            await cache.delete(self.K_STATE.format(cid=chat_id))
        with suppress(Exception):
            await cache.delete(self.K_ICOUNT.format(cid=chat_id))

    async def _load_history(self, chat_id: str) -> list[dict]:
        cache = self._cache_client()
        if cache:
            h = await cache.get(self.K_HISTORY.format(cid=chat_id))
            if isinstance(h, list):
                return h
        return []

    async def _store_interaction(
        self, chat_id: str, user_text: str, aria_text: str | None, tool: str | None
    ) -> None:
        cache = self._cache_client()
        if not cache:
            return
        key = self.K_HISTORY.format(cid=chat_id)
        history = await cache.get(key) or []
        if not isinstance(history, list):
            history = []
        history.append({"role": "user", "content": user_text[:300]})
        if aria_text:
            history.append(
                {
                    "role": "assistant",
                    "content": aria_text[:300],
                    **({"tool": tool} if tool else {}),
                }
            )
        history = history[-(self.MAX_HISTORY * 2) :]
        await cache.set(key, history, ttl_seconds=86400 * 7)

    async def _record_exec(self, tool: str, args: dict, obs: str, success: bool) -> None:
        """Stores an execution record for future self-reflection."""
        cache = self._cache_client()
        if not cache:
            return
        execs = await cache.get(self.K_EXECS) or []
        if not isinstance(execs, list):
            execs = []
        execs.append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "tool": tool,
                "success": success,
                "in": str(args)[:100],
                "out": obs[:150],
            }
        )
        execs = execs[-self.MAX_EXECS :]
        await cache.set(self.K_EXECS, execs, ttl_seconds=86400 * 30)

    async def _trace_turn(
        self,
        task_type: str,
        prompt: str,
        response: str,
        started_at: float,
        success: bool,
    ) -> None:
        """Records this turn with CognitionTracer for the ai_performance_report
        tool. Best-effort only — a tracing failure must never affect the
        actual reply the user already received, so every error is swallowed."""
        with suppress(Exception):
            from apps.evaluation.phoenix.tracer import get_cognition_tracer

            await get_cognition_tracer().record(
                agent_name="aria_mind",
                task_type=task_type,
                prompt=prompt,
                response=response,
                latency_ms=(time.monotonic() - started_at) * 1000,
                success=success,
            )

    # ── SELF-REFLECTION ───────────────────────────────────────────────────────

    async def _maybe_reflect(self, chat_id: str) -> None:
        """
        Analyzes recent executions, generates concrete improvement rules,
        and saves them to Redis. They affect behavior immediately.
        """
        state = await self._load_state(chat_id)
        count = state.get("interaction_count", 0)
        if count == 0 or count % self.REFLECT_EVERY != 0:
            return

        logger.info("[AriaMind] Self-reflection at interaction #%d", count)
        cache = self._cache_client()
        if not cache:
            return

        # Lock so this doesn't run in parallel
        locked = await cache.acquire_lock("aria:mind:reflect", ttl_seconds=60)
        if not locked:
            return

        try:
            execs = await cache.get(self.K_EXECS) or []
            if len(execs) < 5:
                return

            # Build a sample of executions for the LLM
            sample = "\n".join(
                f"[{'✓' if e.get('success') else '✗'}] {e.get('tool','?')}: "
                f"in={e.get('in','')[:60]} → out={e.get('out','')[:80]}"
                for e in execs[-20:]
            )

            ai = self._ai_client()
            if not ai:
                return

            from apps.core.tools.ai_client import AIModel

            # This prompt's output is injected verbatim into SYSTEM_TEMPLATE's
            # {learned} placeholder in every future conversation, so it must
            # produce English rules to match the rest of that system prompt —
            # not because English is inherently better, but because a
            # mid-prompt language switch reads as confused, not intelligent.
            resp = await ai.complete(
                system=(
                    "You are ARIA's self-improvement module. "
                    "Analyze the executions and generate concrete operating rules. "
                    "Each rule must be a direct instruction that improves future decisions. "
                    "Format: action verbs. No explanations. Just the rules."
                ),
                user=(
                    f"My last {len(execs[-20:])} executions:\n{sample}\n\n"
                    "Generate exactly 3 improvement rules. One per line. "
                    "Example: 'Use SDXL directly when FLUX fails on the first attempt.'"
                ),
                model=AIModel.STRATEGY,
                max_tokens=200,
                temperature=0.2,
                agent_name="aria_reflection",
            )

            if resp and resp.success and resp.content:
                new_rules = [
                    l.strip().lstrip("•-123. ")
                    for l in resp.content.strip().split("\n")
                    if l.strip() and len(l.strip()) > 10
                ][:3]

                existing = await self._load_learned()
                updated = (existing + new_rules)[-20:]  # cap at 20 rules
                await cache.set(self.K_LEARNED, updated, ttl_seconds=86400 * 365)
                logger.info("[AriaMind] New rules learned: %s", new_rules)
        except Exception as exc:
            logger.warning("[AriaMind] Reflection failed: %s", exc)
        finally:
            await cache.release_lock("aria:mind:reflect")

    # ── LAZY SINGLETONS ────────────────────────────────────────────────────

    def _ai_client(self):
        if self._ai is None:
            try:
                from apps.core.tools.ai_client import get_ai_client

                self._ai = get_ai_client()
            except Exception as e:
                logger.error("[AriaMind] Could not load ai_client: %s", e)
        return self._ai

    def _cache_client(self):
        if self._cache is None:
            try:
                from apps.core.memory.redis_client import get_cache

                self._cache = get_cache()
            except Exception as e:
                logger.warning("[AriaMind] Could not load cache: %s", e)
        return self._cache

    # ── PROACTIVE NOTIFICATIONS ──────────────────────────────────────────────

    async def proactive_notify(self, message: str) -> None:
        """ARIA proactively decides to notify — critical things only."""
        try:
            from apps.core.config import settings
            from apps.core.tools.telegram_bot import get_bot

            chat_id = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
            if chat_id:
                await get_bot().notify_owner(message)
        except Exception as exc:
            logger.debug("[AriaMind] proactive_notify: %s", exc)

    async def _build_status(self) -> MindResponse:
        """Fast-path /status command — returns rich system status without an LLM call."""
        lines: list[str] = ["## ARIA System Status\n"]

        # AI providers
        try:
            from apps.core.tools.ai_client import get_ai_client

            health = get_ai_client().get_health_summary()
            providers = {k: v for k, v in health.items() if k != "_totals"}
            totals = health.get("_totals", {})
            lines.append("**AI providers:**")
            for name, info in providers.items():
                status = "up" if info.get("available") else "down"
                rate = info.get("success_rate_pct", 100)
                calls = info.get("total_calls", 0)
                lines.append(f"  - **{name}** ({status}) — {rate:.0f}% success · {calls} calls")
            if totals:
                lines.append(
                    f"\n  Total tokens: `{totals.get('tokens_used', 0):,}` · Fallbacks: `{totals.get('fallbacks_triggered', 0)}`"
                )
        except Exception:
            lines.append("  No provider data")

        # Goals
        try:
            goals = await self._load_goals()
            active = [
                g for g in goals if isinstance(g, dict) and g.get("status", "active") == "active"
            ]
            lines.append(f"\n**Active goals:** {len(active)}")
            for g in active[:5]:
                p = g.get("priority", "")
                lines.append(f"  - {'[P'+str(p)+'] ' if p else ''}{g.get('text','')[:70]}")
            if len(active) > 5:
                lines.append(f"  … and {len(active)-5} more")
        except Exception:
            pass

        # Background tasks
        try:
            from apps.core.tools.task_manager import get_task_manager

            stats = get_task_manager().stats()
            running = stats.get("running", 0)
            queued = stats.get("queued", 0)
            completed = stats.get("completed", 0)
            lines.append(
                f"\n**Background tasks:** {running} running · {queued} queued · {completed} completed"
            )
        except Exception:
            pass

        # Knowledge base
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base

            kb = get_knowledge_base()
            kstats = kb.stats()
            lines.append(
                f"\n**Knowledge base:** {kstats.get('total_chunks', 0)} chunks across {len(kstats.get('by_category', {}))} categories"
            )
        except Exception:
            pass

        lines.append(f"\n**Timestamp:** `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`")
        lines.append("\nUse `/help` to see all available capabilities.")
        return MindResponse(text="\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

_mind: AriaMind | None = None


def get_aria_mind() -> AriaMind:
    global _mind
    if _mind is None:
        _mind = AriaMind()
    return _mind
