"""
IncomeLoop v1.0 — ARIA's 24/7 Autonomous Income Machine.

Runs every 30 minutes alongside the orchestrator (60 min).
Focuses on PURE EXECUTION — no planning overhead.

Every cycle picks a strategy based on weighted probability:
  30% — Content Pipeline   (SEO articles + affiliate → Medium/dev.to/Hashnode)
  22% — Niche Rotator      (launches next niche in catalog → Gumroad + Zapier)
  18% — Product Factory    (creates new digital products for trending topics)
  10% — Opportunity Scan   (web research for new income streams)
   8% — Shopify Listing    (creates Shopify digital product from trending topic)
   7% — Email Campaign     (Mailchimp campaign to owned audience)
   3% — Social Blitz       (Zapier distribution for all existing products)
   2% — Premium Offer      (high-ticket B2B consulting offers)

Scale at 30-min intervals:
  48 cycles/day × 3 articles = 144 articles/day
  48 cycles/day → full niche catalog covered every ~1 day
  Revenue compounds: more products + more content = more discovery

The loop NEVER stops. Every exception is caught, logged, and the
loop resumes after a short backoff. Redis tracks all results.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("aria.income_loop")

INTERVAL_SECONDS  = 1800   # 30 minutes between cycles
FIRST_RUN_DELAY   = 45     # seconds after startup before first run
ERROR_BACKOFF     = 300    # 5 min backoff after errors
MAX_STRATEGY_TIME = 240    # 4 min max per strategy (avoids blocking)

# Strategy probability weights (sum = 100)
STRATEGIES = [
    ("content_pipeline",  30),
    ("niche_rotator",     22),
    ("product_factory",   18),
    ("opportunity_scan",  10),
    ("shopify_listing",    8),
    ("email_campaign",     7),
    ("social_blitz",       3),
    ("premium_offer",      2),
]


@dataclass
class CycleResult:
    cycle_id: int
    strategy: str
    success: bool
    summary: str
    revenue_potential: float = 0.0
    urls_created: list[str] = field(default_factory=list)
    elapsed_seconds: int = 0
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IncomeLoop:
    """
    Autonomous income machine. Never sleeps for more than 30 minutes.
    Each cycle executes one income strategy, tracks results in Redis,
    and notifies via Telegram only on significant events.
    """

    def __init__(self) -> None:
        self._running    = False
        self._task       = None
        self._cycle      = 0
        self._niche_idx  = 0    # Round-robin through niche catalog

    # ── Control ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the income loop as a background coroutine."""
        if self._running:
            logger.info("[IncomeLoop] Already running")
            return
        self._running = True
        self._task    = asyncio.create_task(self._run_forever())
        logger.info("[IncomeLoop] 24/7 income loop started (interval=%ds)", INTERVAL_SECONDS)

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[IncomeLoop] Stopped")

    @property
    def is_running(self) -> bool:
        return self._running and (self._task is not None) and (not self._task.done())

    # ── Main loop ─────────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Infinite loop. Never crashes. Always resumes."""
        logger.info("[IncomeLoop] First run in %ds", FIRST_RUN_DELAY)
        await asyncio.sleep(FIRST_RUN_DELAY)

        while self._running:
            try:
                await self._run_one_cycle()
            except asyncio.CancelledError:
                logger.info("[IncomeLoop] Cancelled gracefully")
                break
            except Exception as exc:
                logger.error("[IncomeLoop] Unhandled error: %s", exc, exc_info=True)
                self._save_error(str(exc))
                await asyncio.sleep(ERROR_BACKOFF)
                continue

            await asyncio.sleep(INTERVAL_SECONDS)

    async def _run_one_cycle(self, force_strategy: str | None = None) -> "CycleResult":
        self._cycle += 1
        strategy = force_strategy if force_strategy else self._pick_strategy()
        start    = time.time()
        logger.info("[IncomeLoop] Cycle #%d — strategy: %s", self._cycle, strategy)

        result = CycleResult(
            cycle_id=self._cycle,
            strategy=strategy,
            success=False,
            summary="",
        )

        try:
            obs = await asyncio.wait_for(
                self._execute(strategy), timeout=MAX_STRATEGY_TIME
            )
            result.success          = obs.get("success", False)
            result.summary          = obs.get("summary", "")
            result.revenue_potential = obs.get("revenue_potential", 0.0)
            result.urls_created     = obs.get("urls", [])
        except asyncio.TimeoutError:
            result.summary = f"Strategy '{strategy}' timed out after {MAX_STRATEGY_TIME}s"
            logger.warning("[IncomeLoop] %s", result.summary)
        except Exception as exc:
            result.summary = f"Strategy '{strategy}' error: {str(exc)[:150]}"
            logger.error("[IncomeLoop] %s", result.summary)
        finally:
            result.elapsed_seconds = int(time.time() - start)

        self._save_result(result)

        # Notify on wins
        if result.success and result.urls_created:
            await self._notify_win(result)

        logger.info(
            "[IncomeLoop] Cycle #%d done in %ds | success=%s | %s",
            self._cycle, result.elapsed_seconds, result.success, result.summary[:80]
        )
        return result

    def _pick_strategy(self) -> str:
        """Weighted random strategy selection."""
        names   = [s[0] for s in STRATEGIES]
        weights = [s[1] for s in STRATEGIES]
        return random.choices(names, weights=weights, k=1)[0]

    # ── Strategy Executors ─────────────────────────────────────────────────

    async def _execute(self, strategy: str) -> dict:
        if strategy == "content_pipeline":
            return await self._exec_content_pipeline()
        elif strategy == "niche_rotator":
            return await self._exec_niche_rotator()
        elif strategy == "product_factory":
            return await self._exec_product_factory()
        elif strategy == "opportunity_scan":
            return await self._exec_opportunity_scan()
        elif strategy == "shopify_listing":
            return await self._exec_shopify_listing()
        elif strategy == "email_campaign":
            return await self._exec_email_campaign()
        elif strategy == "social_blitz":
            return await self._exec_social_blitz()
        elif strategy == "premium_offer":
            return await self._exec_premium_offer()
        return {"success": False, "summary": "Unknown strategy"}

    async def _exec_content_pipeline(self) -> dict:
        """Run the full content pipeline: trending → articles → publish → affiliate."""
        try:
            from apps.core.tools.content_pipeline import ContentPipeline
            cp    = ContentPipeline()
            result = await cp.run_pipeline(num_articles=3, language="es")
            arts   = result.get("articles", [])
            urls   = [u["url"] for a in arts for u in a.get("urls", []) if u.get("url")]
            return {
                "success": result.get("success", False),
                "summary": f"Published {len(arts)} articles to {result.get('articles_published',0)} platforms",
                "revenue_potential": len(arts) * 2.5,  # ~$2.5 per article in affiliate
                "urls": urls[:6],
            }
        except Exception as exc:
            logger.error("[IncomeLoop] content_pipeline: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_niche_rotator(self) -> dict:
        """Rotate through niche catalog — launch next unstarted niche."""
        try:
            from apps.core.tools.niche_revenue_engine import (
                get_niche_revenue_engine, NICHE_CATALOG
            )
            engine  = get_niche_revenue_engine()
            launched = {ls.niche_key for ls in engine._load_listings()}
            all_keys = list(NICHE_CATALOG.keys())

            # Find next unlaunched niche (round-robin)
            candidates = [k for k in all_keys if k not in launched]
            if not candidates:
                # All launched — pick the oldest for a refresh
                candidates = all_keys
            target = candidates[self._niche_idx % len(candidates)]
            self._niche_idx += 1

            result = await engine.launch_niche(target)
            urls   = [u["url"] for u in result.published_urls + result.seo_article_urls if u.get("url")]
            return {
                "success":          result.success,
                "summary":          f"Niche '{target}': checklist={result.checklist.score if result.checklist else 0}/100 | {len(result.published_urls)} listings | {len(result.seo_article_urls)} articles",
                "revenue_potential": result.revenue_potential_usd,
                "urls":             urls,
            }
        except Exception as exc:
            logger.error("[IncomeLoop] niche_rotator: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_product_factory(self) -> dict:
        """Create a new digital product for the most trending topic."""
        try:
            from apps.core.tools.content_pipeline import ContentPipeline
            from apps.core.tools.gumroad_tools import GumroadTools
            from apps.core.tools.ai_client import get_ai_client, AIModel

            cp     = ContentPipeline()
            topics = await cp.get_trending_topics(limit=5)
            if not topics:
                return {"success": False, "summary": "No trending topics found"}

            topic = topics[0]
            title = topic.get("title", "Digital Guide")[:60]
            cat   = topic.get("category", "tech")

            ai    = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI client unavailable"}

            # Generate ebook content
            resp = await ai.complete(
                system=(
                    "You are a bestselling digital product creator. "
                    "Write complete, actionable content. No fluff. Output JSON only."
                ),
                user=f"""Create a complete digital product for the trending topic: "{title}"
Category: {cat}

Output JSON:
{{
  "product_name": "Compelling title with keyword",
  "tagline": "One-line value proposition",
  "description": "300+ word sales description with pain points, solution, benefits, social proof, CTA",
  "table_of_contents": ["Chapter 1: ...", "Chapter 2: ...", "Chapter 3: ...", "Chapter 4: ...", "Chapter 5: ..."],
  "price_cents": 1997,
  "tags": ["tag1", "tag2", "tag3"]
}}""",
                model=AIModel.CREATIVE,
                max_tokens=2000,
                temperature=0.8,
            )

            if not resp or not resp.success or not resp.content:
                return {"success": False, "summary": "AI generation failed"}

            try:
                product_data = json.loads(resp.content.strip())
            except Exception:
                return {"success": False, "summary": "AI returned invalid JSON"}

            # Create on Gumroad
            gt     = GumroadTools()
            gr_res = await gt.create_product(
                name=product_data.get("product_name", title),
                description=product_data.get("description", ""),
                price_cents=product_data.get("price_cents", 997),
                tags=product_data.get("tags", [cat, "digital", "guide"]),
            )

            if gr_res.get("success"):
                url = gr_res.get("url", "")
                # Fire Zapier event to distribute
                try:
                    from apps.core.tools.zapier_connector import ZapierConnector
                    await ZapierConnector().dispatch_event(
                        "NEW_PRODUCT",
                        {
                            "product_name": product_data.get("product_name"),
                            "tagline": product_data.get("tagline"),
                            "price": gr_res.get("price_usd"),
                            "url": url,
                            "category": cat,
                        },
                    )
                except Exception:
                    pass

                return {
                    "success": True,
                    "summary": f"New product '{product_data.get('product_name',title)[:50]}' at ${product_data.get('price_cents',997)/100:.0f}",
                    "revenue_potential": product_data.get("price_cents", 997) / 100,
                    "urls": [url] if url else [],
                }
            return {
                "success": False,
                "summary": f"Gumroad: {gr_res.get('error', 'failed')}",
            }
        except Exception as exc:
            logger.error("[IncomeLoop] product_factory: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_opportunity_scan(self) -> dict:
        """
        Web research to discover NEW income opportunities ARIA hasn't tried yet.
        Saves discoveries to Redis queue for the niche_rotator to pick up.
        """
        try:
            from apps.core.tools.web_tools import WebTools
            from apps.core.tools.ai_client import get_ai_client, AIModel

            wt  = WebTools()
            queries = [
                "best ways to make money online with AI 2025",
                "passive income ideas digital products trending",
                "freelance niches high demand low competition 2025",
            ]
            all_results = []
            for q in queries:
                r = await wt.search_web(q, num_results=5)
                if r.get("success"):
                    all_results.extend(r.get("results", [])[:3])

            if not all_results:
                return {"success": False, "summary": "No search results for opportunity scan"}

            # AI analysis of opportunities
            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable for opportunity analysis"}

            results_text = "\n".join(
                f"- {r.get('title','')}: {r.get('snippet','')[:150]}"
                for r in all_results[:12]
            )

            resp = await ai.complete(
                system="You are an income opportunity analyst. Be specific and actionable. Output JSON only.",
                user=f"""Analyze these search results and extract 3 SPECIFIC income opportunities:

{results_text}

Output JSON:
{{
  "opportunities": [
    {{
      "name": "specific opportunity name",
      "niche_key": "snake_case_key",
      "description": "what exactly to do",
      "platform": "where to sell",
      "time_to_first_dollar": "X days",
      "estimated_monthly_revenue": 500,
      "difficulty": "easy|medium|hard"
    }}
  ]
}}""",
                model=AIModel.STRATEGY,
                max_tokens=1000,
                temperature=0.5,
            )

            if not resp or not resp.success:
                return {"success": False, "summary": "AI analysis failed"}

            try:
                data = json.loads(resp.content.strip())
                opportunities = data.get("opportunities", [])
            except Exception:
                opportunities = []

            # Save to Redis queue
            r = self._redis()
            if r and opportunities:
                for opp in opportunities:
                    r.rpush("aria:income:opportunity_queue", json.dumps(opp))

            summaries = [f"{o.get('name','')} ({o.get('time_to_first_dollar','')})" for o in opportunities[:3]]
            return {
                "success": True,
                "summary": f"Found {len(opportunities)} opportunities: {', '.join(summaries)}",
                "revenue_potential": sum(o.get("estimated_monthly_revenue", 0) for o in opportunities),
                "urls": [],
            }
        except Exception as exc:
            logger.error("[IncomeLoop] opportunity_scan: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_social_blitz(self) -> dict:
        """Fire Zapier events for ALL existing live products simultaneously."""
        try:
            from apps.core.tools.niche_revenue_engine import get_niche_revenue_engine
            from apps.core.tools.zapier_connector import ZapierConnector

            engine   = get_niche_revenue_engine()
            listings = engine._load_listings()
            live     = [ls for ls in listings if ls.listing_urls]

            if not live:
                return {"success": False, "summary": "No live listings to promote"}

            zc   = ZapierConnector()
            sent = 0
            for ls in live[:5]:  # Limit to 5 to avoid spam
                try:
                    await zc.dispatch_event(
                        "CONTENT_READY",
                        {
                            "product_name": ls.title,
                            "tagline": ls.tagline,
                            "price": ls.pricing_tiers.get("basic", {}).get("price", 0),
                            "urls": ls.listing_urls,
                            "keywords": ", ".join(ls.keywords[:3]),
                            "category": ls.category,
                        },
                    )
                    sent += 1
                    await asyncio.sleep(2)  # Rate limit
                except Exception:
                    pass

            return {
                "success": sent > 0,
                "summary": f"Promoted {sent}/{len(live)} listings via Zapier",
                "revenue_potential": 0,
                "urls": [],
            }
        except Exception as exc:
            logger.error("[IncomeLoop] social_blitz: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_premium_offer(self) -> dict:
        """
        Create a high-ticket B2B service offer.
        These generate $500-$5,000+ per client.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.gumroad_tools import GumroadTools
            from apps.core.tools.web_tools import WebTools

            # Find a trending B2B pain point
            wt = WebTools()
            r  = await wt.search_web("business automation AI consulting demand 2025", num_results=5)
            context = ""
            if r.get("success") and r.get("results"):
                context = r["results"][0].get("snippet", "")[:300]

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            resp = await ai.complete(
                system="You are a B2B sales expert. Create premium service packages that command $500-$5000. Output JSON only.",
                user=f"""Create a premium B2B consulting offer based on this market insight:
{context}

Focus on AI automation / business efficiency / revenue growth.

JSON:
{{
  "offer_name": "Premium offer title",
  "tagline": "ROI-focused one-liner",
  "description": "Compelling 250+ word description. Lead with ROI. Include what's included, who it's for, transformation promised.",
  "what_included": ["Deliverable 1", "Deliverable 2", "Deliverable 3", "Deliverable 4"],
  "price_cents": 149700,
  "target_client": "Description of ideal B2B client",
  "tags": ["consulting", "automation", "ai", "b2b"]
}}""",
                model=AIModel.STRATEGY,
                max_tokens=1500,
                temperature=0.6,
            )

            if not resp or not resp.success:
                return {"success": False, "summary": "AI failed"}

            try:
                offer = json.loads(resp.content.strip())
            except Exception:
                return {"success": False, "summary": "AI returned invalid JSON"}

            # Publish to Gumroad as consulting package
            gt = GumroadTools()
            gr = await gt.create_product(
                name=offer.get("offer_name", "Premium AI Consulting"),
                description=offer.get("description", ""),
                price_cents=offer.get("price_cents", 149700),
                tags=offer.get("tags", ["consulting", "ai", "b2b"]),
            )

            if gr.get("success"):
                return {
                    "success": True,
                    "summary": f"Premium offer '{offer.get('offer_name','')[:50]}' at ${offer.get('price_cents',149700)/100:.0f}",
                    "revenue_potential": offer.get("price_cents", 149700) / 100,
                    "urls": [gr.get("url", "")] if gr.get("url") else [],
                }
            return {"success": False, "summary": f"Gumroad: {gr.get('error', 'failed')}"}

        except Exception as exc:
            logger.error("[IncomeLoop] premium_offer: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_shopify_listing(self) -> dict:
        """
        Create a Shopify product listing for a trending digital item.
        Targets print-on-demand, digital downloads, or info products.
        """
        try:
            from apps.core.tools.ai_client import get_ai_client, AIModel
            from apps.core.tools.commerce_tools import get_commerce_tools
            from apps.core.tools.content_pipeline import ContentPipeline

            cp     = ContentPipeline()
            topics = await cp.get_trending_topics(limit=3)
            topic  = topics[0] if topics else "AI productivity tools 2025"

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            resp = await ai.complete(
                system="You are a Shopify product expert. Create compelling digital product listings. Output JSON only.",
                user=f"""Create a Shopify digital product listing for the trending topic: "{topic}"

JSON:
{{
  "title": "Product title (60 chars max)",
  "description": "Compelling HTML product description (200+ words). Include benefits, what's included, who it's for.",
  "price": "29.99",
  "product_type": "Digital Download",
  "tags": ["digital", "download", "productivity"],
  "status": "active"
}}""",
                model=AIModel.FAST,
                max_tokens=800,
                temperature=0.6,
            )

            if not resp or not resp.success:
                return {"success": False, "summary": "AI failed to generate product"}

            try:
                product = json.loads(resp.content.strip())
            except Exception:
                return {"success": False, "summary": "Invalid product JSON from AI"}

            ct    = get_commerce_tools()
            price = float(product.get("price", "29.99"))
            res   = await ct.shopify_create_product(
                title=product.get("title", f"Digital Product: {topic[:40]}"),
                description=product.get("description", ""),
                price=price,
                product_type=product.get("product_type", "Digital Download"),
            )

            if res.get("success"):
                url = res.get("shop_url", "")
                return {
                    "success": True,
                    "summary": f"Shopify product '{product.get('title','')[:50]}' at ${price:.2f}",
                    "revenue_potential": price,
                    "urls": [url] if url else [],
                }
            return {"success": False, "summary": f"Shopify: {res.get('error', 'failed')}"}

        except Exception as exc:
            logger.error("[IncomeLoop] shopify_listing: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    async def _exec_email_campaign(self) -> dict:
        """
        Create and send a Mailchimp email campaign promoting ARIA's latest products.
        Email list = owned audience = free traffic = recurring revenue.
        """
        try:
            from apps.core.tools.mailchimp_tools import MailchimpTools
            from apps.core.tools.ai_client import get_ai_client, AIModel

            mc = MailchimpTools()
            if not mc._configured():
                return {"success": False, "summary": "Mailchimp not configured (MAILCHIMP_API_KEY missing)"}

            lists = await mc.get_lists()
            if not lists.get("lists"):
                return {"success": False, "summary": "No Mailchimp lists found"}
            list_id = lists["lists"][0]["id"]

            ai = get_ai_client()
            if not ai:
                return {"success": False, "summary": "AI unavailable"}

            resp = await ai.complete(
                system="You are an email marketing expert. Write high-converting email campaigns. Output JSON only.",
                user="""Create an email campaign promoting AI productivity tools and digital products.

JSON:
{
  "subject": "Email subject line (compelling, under 60 chars)",
  "preview_text": "Preview text (50 chars max)",
  "html_body": "Full HTML email body (300+ words). Include CTA button. Professional and persuasive."
}""",
                model=AIModel.FAST,
                max_tokens=1200,
                temperature=0.7,
            )

            if not resp or not resp.success:
                return {"success": False, "summary": "AI failed to generate email"}

            try:
                email_data = json.loads(resp.content.strip())
            except Exception:
                return {"success": False, "summary": "Invalid email JSON"}

            result = await mc.create_campaign(
                list_id=list_id,
                subject=email_data.get("subject", "Discover AI Tools That Make You Money"),
                preview_text=email_data.get("preview_text", "Exclusive offer inside"),
                html_body=email_data.get("html_body", "<p>Check out our latest products!</p>"),
            )

            if result.get("success"):
                campaign_id = result.get("campaign_id", "")
                return {
                    "success": True,
                    "summary": f"Email campaign '{email_data.get('subject','')[:50]}' → list {list_id}",
                    "revenue_potential": 150.0,
                    "urls": [f"https://mailchimp.com/campaigns/{campaign_id}"] if campaign_id else [],
                }
            return {"success": False, "summary": f"Mailchimp: {result.get('error', 'failed')}"}

        except Exception as exc:
            logger.error("[IncomeLoop] email_campaign: %s", exc)
            return {"success": False, "summary": str(exc)[:100]}

    # ── Persistence ───────────────────────────────────────────────────────

    def _redis(self):
        try:
            from apps.core.tools.knowledge_base import get_knowledge_base
            return get_knowledge_base()._redis
        except Exception:
            return None

    def _save_result(self, result: CycleResult) -> None:
        r = self._redis()
        if not r:
            return
        try:
            r.rpush("aria:income:loop_history", json.dumps(asdict(result)))
            r.ltrim("aria:income:loop_history", -200, -1)  # Keep last 200
            r.set("aria:income:last_cycle", json.dumps(asdict(result)))
            r.incr("aria:income:total_cycles")
            if result.success:
                r.incr("aria:income:successful_cycles")
        except Exception as exc:
            logger.warning("[IncomeLoop] Redis save: %s", exc)

    def _save_error(self, error: str) -> None:
        r = self._redis()
        if r:
            try:
                r.rpush("aria:income:errors", json.dumps({
                    "error": error, "ts": datetime.now(timezone.utc).isoformat()
                }))
                r.ltrim("aria:income:errors", -50, -1)
            except Exception:
                pass

    # ── Notifications ─────────────────────────────────────────────────────

    async def _notify_win(self, result: CycleResult) -> None:
        """Notify via Telegram only when something valuable was created."""
        if result.revenue_potential < 10:
            return
        try:
            from apps.core.tools.telegram_bot import get_bot
            urls_text = "\n".join(result.urls_created[:3])
            msg = (
                f"💰 <b>Nuevo ingreso creado</b>\n"
                f"Estrategia: {result.strategy}\n"
                f"Potencial: ${result.revenue_potential:.0f}\n"
                f"{result.summary[:200]}"
                + (f"\n\n{urls_text}" if urls_text else "")
            )
            bot = get_bot()
            await bot.notify_owner(msg)
        except Exception:
            pass

    # ── Status ────────────────────────────────────────────────────────────

    def get_status_dict(self) -> dict:
        """Return structured status dict for API/dashboard consumption."""
        r = self._redis()
        total_cycles    = 0
        success_count   = 0
        error_count     = 0
        last_cycle_data = {}
        recent_cycles   = []
        opportunities   = []
        total_revenue   = 0.0

        if r:
            try:
                total_cycles  = int(r.get("aria:income:total_cycles") or 0)
                success_count = int(r.get("aria:income:successful_cycles") or 0)
                error_count   = int(r.get("aria:income:errors") or 0)

                last_raw = r.get("aria:income:last_cycle")
                if last_raw:
                    last_cycle_data = json.loads(last_raw if isinstance(last_raw, str) else last_raw.decode())

                history_raw = r.lrange("aria:income:loop_history", -20, -1)
                for raw in reversed(history_raw or []):
                    try:
                        c = json.loads(raw if isinstance(raw, str) else raw.decode())
                        recent_cycles.append(c)
                        total_revenue += c.get("revenue_potential", 0)
                    except Exception:
                        pass

                opp_raw = r.lrange("aria:income:opportunity_queue", 0, 9)
                for raw in (opp_raw or []):
                    try:
                        opportunities.append(json.loads(raw if isinstance(raw, str) else raw.decode()))
                    except Exception:
                        pass
            except Exception:
                pass

        return {
            "running": self.is_running,
            "total_cycles": total_cycles,
            "successful_cycles": success_count,
            "errors": error_count,
            "success_rate": round(success_count / total_cycles * 100, 1) if total_cycles else 0,
            "total_revenue_potential": round(total_revenue, 2),
            "last_cycle": last_cycle_data or None,
            "recent_cycles": recent_cycles,
            "opportunities": opportunities,
            "opportunity_count": len(opportunities),
            "interval_minutes": INTERVAL_SECONDS // 60,
        }

    def get_status(self) -> str:
        r = self._redis()
        total_cycles = 0
        success_rate = 0.0
        last_cycle   = {}
        recent_urls  = []

        if r:
            try:
                total_cycles  = int(r.get("aria:income:total_cycles") or 0)
                success_count = int(r.get("aria:income:successful_cycles") or 0)
                success_rate  = (success_count / total_cycles * 100) if total_cycles else 0

                last_raw = r.get("aria:income:last_cycle")
                if last_raw:
                    last_cycle = json.loads(last_raw if isinstance(last_raw, str) else last_raw.decode())

                history_raw = r.lrange("aria:income:loop_history", -10, -1)
                for raw in (history_raw or []):
                    try:
                        cycle = json.loads(raw if isinstance(raw, str) else raw.decode())
                        recent_urls.extend(cycle.get("urls_created", []))
                    except Exception:
                        pass
            except Exception:
                pass

        next_run = INTERVAL_SECONDS - ((self._cycle * INTERVAL_SECONDS) % INTERVAL_SECONDS) if self._cycle else FIRST_RUN_DELAY
        status_label = "🟢 RUNNING" if self.is_running else "🔴 STOPPED"

        lines = [
            f"**ARIA Income Loop — {status_label}**",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"Cycles completed: {total_cycles}",
            f"Success rate: {success_rate:.1f}%",
            f"Interval: every {INTERVAL_SECONDS//60} minutes",
            f"",
            f"**Last cycle:**",
        ]
        if last_cycle:
            lines += [
                f"  Strategy: {last_cycle.get('strategy','?')}",
                f"  Success: {'✅' if last_cycle.get('success') else '❌'}",
                f"  Summary: {last_cycle.get('summary','')[:100]}",
                f"  Revenue potential: ${last_cycle.get('revenue_potential',0):.0f}",
                f"  Time: {last_cycle.get('elapsed_seconds',0)}s",
            ]
        else:
            lines.append("  (no cycles yet)")

        if recent_urls:
            unique_urls = list(dict.fromkeys(u for u in recent_urls if u))[:5]
            if unique_urls:
                lines.append("")
                lines.append("**Recent URLs created:**")
                for u in unique_urls:
                    lines.append(f"  • {u}")

        lines += [
            "",
            f"**Strategies in rotation:**",
        ]
        for name, weight in STRATEGIES:
            lines.append(f"  {weight}% — {name}")

        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────────────────────

_loop: Optional[IncomeLoop] = None

def get_income_loop() -> IncomeLoop:
    global _loop
    if _loop is None:
        _loop = IncomeLoop()
    return _loop
