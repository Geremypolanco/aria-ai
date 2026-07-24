"""
orchestrator.py — Central director of ARIA AI. Absolute priority: MONETIZATION.

v4 improvements:
- Reinforced 24/7 proactivity
- Priority on Shopify, Zapier, and High-Ticket
- Automatic search expansion in WebTools
- Fix: unified revenue dashboard with the 'revenue' table
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.orchestrator")

TELEGRAM_API = "https://api.telegram.org/bot"


class Orchestrator(BaseAgent):
    """
    Central director of the ARIA AI system.
    Mission: generate real revenue autonomously.
    AI engine: HuggingFace (primary) → Groq → OpenAI
    """

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            description="Central director — autonomous monetization and agent coordination",
            capabilities=["market_analysis", "planning", "coordination", "reporting"],
        )
        self._agents: dict[str, BaseAgent] = {}
        self._cycle_count = 0

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self.run_cycle()

    async def execute_mission(self, mission_text: str) -> dict[str, Any]:
        """Executes a specific mission on demand (e.g. from Telegram)."""
        logger.info("[Orchestrator] Running mission: %s", mission_text)

        # Enhanced multimedia/software creation mission
        # (bilingual match against user input mission text — left untranslated)
        m_lower = mission_text.lower()
        if any(x in m_lower for x in ["create", "genera", "crea", "haz", "dibuja"]):
            # Identify format
            fmt = "image"
            if any(x in m_lower for x in ["video", "clip", "película"]):
                fmt = "video"
            elif any(x in m_lower for x in ["música", "canción", "audio", "music"]):
                fmt = "music"
            elif any(x in m_lower for x in ["software", "código", "app"]):
                fmt = "software"

            agent = await self._get_agent("content")
            if agent:
                logger.info(f"[Orchestrator] Delegating {fmt} creation to ContentAgent")
                return await agent.execute(
                    {"task": "creative_creation", "format": fmt, "topic": mission_text}
                )

        return {"success": False, "error": "Mission not recognized or agent not available"}

    # ── MAIN CYCLE ───────────────────────────────────────────

    async def run_cycle(self) -> dict[str, Any]:
        """
        Full autonomous cycle:
        1. Real market intelligence (internet)
        2. AI action plan (HF primary)
        3. Parallel execution by priority
        4. Logging to Supabase
        5. Telegram report
        """
        self._cycle_count += 1
        cycle_start = time.time()
        logger.info("[Orchestrator] ─── CYCLE #%d STARTED ───", self._cycle_count)

        # Make sure agents are loaded
        if not self._agents:
            self._auto_discover_agents()

        # Log start to Supabase
        cycle_id = await self._log_cycle_start()

        # 1. REAL market intelligence
        intelligence = await self._gather_market_intelligence()

        # 2. Monetization plan with AI (HuggingFace primary)
        plan = await self._generate_monetization_plan(intelligence)
        if not plan.get("missions"):
            plan = self._fallback_monetization_plan()

        # 3. Monetization always comes first
        plan = self._enforce_monetization_priority(plan)

        logger.info(
            "[Orchestrator] Plan: %d missions — focus: %s",
            len(plan["missions"]),
            plan.get("focus", "monetization"),
        )

        # 4. Run missions in parallel by priority
        results = await self._execute_by_priority(plan["missions"])

        cycle_time = time.time() - cycle_start
        revenue_summary = self._extract_revenue_summary(results)

        # 5. Log the result to Supabase
        await self._log_cycle_end(cycle_id, results, revenue_summary)

        # 6. Report via Telegram
        await self._send_cycle_report(results, intelligence, revenue_summary, cycle_time)

        return {
            "cycle": self._cycle_count,
            "missions_run": len(results),
            "plan_focus": plan.get("focus", ""),
            "market_opportunity": intelligence.get("top_opportunity", ""),
            "revenue_summary": revenue_summary,
            "cycle_time_s": round(cycle_time, 1),
        }

    # ── SUPABASE LOGGING ──────────────────────────────────────────

    async def _log_cycle_start(self) -> str | None:
        """Logs the cycle start to Supabase."""
        try:
            from apps.core.tools.db_setup import log_to_supabase

            data = {
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "summary": {"cycle_number": self._cycle_count},
            }
            await log_to_supabase("autonomous_cycles", data)
        except Exception as exc:
            logger.debug("[Orchestrator] DB log start error: %s", exc)
        return None

    async def _log_cycle_end(
        self, cycle_id: str | None, results: list[dict], revenue: dict
    ) -> None:
        """Logs the cycle end to Supabase."""
        try:
            from apps.core.tools.db_setup import log_to_supabase

            errors = [r.get("error", "") for r in results if not r.get("success")]
            data = {
                "status": "completed",
                "completed_at": datetime.now(UTC).isoformat(),
                "revenue_generated": revenue.get("total_revenue_usd", 0),
                "articles_published": revenue.get("items_published", 0),
                "products_created": revenue.get("products_listed", 0),
                "errors": errors[:5],
                "summary": {
                    "cycle_number": self._cycle_count,
                    "missions_ok": revenue.get("missions_successful", 0),
                    "missions_fail": revenue.get("missions_failed", 0),
                },
            }
            await log_to_supabase("autonomous_cycles", data)
        except Exception as exc:
            logger.debug("[Orchestrator] DB log end error: %s", exc)

    # ── REAL MARKET INTELLIGENCE ─────────────────────────────

    async def _gather_market_intelligence(self) -> dict[str, Any]:
        """Gathers REAL market intelligence from the internet."""
        try:
            from apps.core.tools.web_tools import WebTools

            wt = WebTools()
            logger.info("[Orchestrator] Accessing the internet for market intelligence...")
            intel = await wt.gather_market_intelligence(
                focus="digital products passive income AI tools saas affiliate marketing"
            )
            all_titles = intel.get("trending_titles", [])
            intel["top_opportunity"] = (
                all_titles[0] if all_titles else "expanding digital market"
            )
            intel["sources_used"] = intel.get("sources_available", [])
            logger.info(
                "[Orchestrator] Intelligence: %d sources, %d trends",
                intel.get("sources_count", 0),
                intel.get("total_data_points", 0),
            )
            return intel
        except Exception as exc:
            logger.error("[Orchestrator] Intelligence error: %s", exc)
            return {
                "error": str(exc),
                "sources_used": [],
                "trending_titles": [],
                "top_opportunity": "AI-powered digital products",
            }

    # ── AI MONETIZATION PLAN ───────────────────────────────

    async def _generate_monetization_plan(self, intelligence: dict[str, Any]) -> dict[str, Any]:
        """
        Generates a detailed action plan using AI.
        """
        ai = get_ai_client()
        if not ai:
            logger.error("[Orchestrator] AI client not available")
            return {}

        trending = intelligence.get("trending_titles", [])[:8]
        hn_top = intelligence.get("hacker_news", [{}])
        hn_title = hn_top[0].get("title", "") if hn_top else ""
        reddit_top = intelligence.get("reddit", [{}])
        reddit_title = reddit_top[0].get("title", "") if reddit_top else ""

        system_prompt = (
            "You are the strategic director of ARIA AI, a proactive 24/7 autonomous monetization system. "
            "Your mission is to identify massive revenue opportunities and execute them without omitting any detail. "
            "You prioritize Shopify, Zapier, and High-Ticket services over traditional SEO content. "
            "Respond ONLY with valid JSON, no markdown."
        )

        user_prompt = f"""MARKET CONTEXT ({datetime.now(UTC).strftime('%Y-%m-%d')}):
- HackerNews trend: {hn_title or 'Not available'}
- Reddit trend: {reddit_title or 'Not available'}
- Trending topics: {', '.join(trending[:5]) or 'AI, digital business, automation'}

GOLDEN RULES:
1. Don't omit details: each mission must have a specific, ambitious 'target_topic'.
2. Direct monetization: prioritize the 'ecommerce' and 'cfo' agents for Shopify and High-Ticket.
3. Quality: products must be high quality, with optimized listings and SEO.

AVAILABLE AGENTS:
- ecommerce: manages Shopify, creates products, optimized listings, inventory, images, and videos.
- cfo: manages payments, Gumroad, and High-Ticket sales strategy ($997+).
- content: generates SEO articles with affiliate links.
- pm: researches profitable niches and Zapier automation strategies.
- social: distributes content on social media via Buffer.
- investor: seeks real capital, contacts VCs/Angels, and creates pitch decks.

Generate the detailed monetization plan. Expected JSON:
{{
  "focus": "strategic description of today's focus",
  "market_opportunity": "opportunity detected in trends",
  "estimated_revenue_usd": 0,
  "missions": [
    {{
      "agent": "ecommerce",
      "task": "full_ecommerce_pipeline",
      "priority": 1,
      "target_topic": "specific high-value product/service",
      "revenue_target_usd": 500,
      "rationale": "detailed explanation of why this product today"
    }}
  ]
}}"""

        try:
            plan = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1200,
                agent_name="orchestrator",
            )
            if plan and plan.get("missions"):
                logger.info("[Orchestrator] AI plan (HF): %s", plan.get("focus", ""))
                return plan
        except Exception as exc:
            logger.error("[Orchestrator] Error generating plan: %s", exc)

        return {}

    def _enforce_monetization_priority(self, plan: dict) -> dict:
        """Guarantees content and cfo are ALWAYS in the plan."""
        missions = plan.get("missions", [])
        existing_agents = {m.get("agent") for m in missions}

        if "ecommerce" not in existing_agents:
            missions.insert(
                0,
                {
                    "agent": "ecommerce",
                    "task": "full_ecommerce_pipeline",
                    "priority": 1,
                    "target_topic": "premium products for the tech/AI niche",
                    "revenue_target_usd": 500,
                    "rationale": "Shopify + Zapier = scalable revenue",
                },
            )

        if "cfo" not in existing_agents:
            missions.insert(
                1,
                {
                    "agent": "cfo",
                    "task": "high_ticket_sales_strategy",
                    "priority": 2,
                    "target_topic": "high-ticket AI consulting services",
                    "revenue_target_usd": 1000,
                    "rationale": "High-ticket sales maximize ROI",
                },
            )

        missions.sort(key=lambda x: x.get("priority", 99))
        plan["missions"] = missions
        return plan

    def _fallback_monetization_plan(self) -> dict:
        """Emergency plan for when the AI doesn't respond."""
        return {
            "focus": "multi-channel monetization — Shopify e-commerce + content + high-ticket",
            "market_opportunity": "expanding e-commerce and premium AI services",
            "missions": [
                {
                    "agent": "ecommerce",
                    "task": "full_ecommerce_pipeline",
                    "priority": 1,
                    "target_topic": "high-value AI products",
                    "revenue_target_usd": 500,
                    "rationale": "Shopify + Zapier + High-Ticket = maximum revenue",
                },
                {
                    "agent": "content",
                    "task": "full_pipeline",
                    "priority": 2,
                    "target_topic": "AI tools for e-commerce 2025",
                    "revenue_target_usd": 50,
                },
                {
                    "agent": "cfo",
                    "task": "create_and_sell_ebook",
                    "priority": 3,
                    "target_topic": "AI and Shopify automation guide",
                    "revenue_target_usd": 100,
                },
            ],
        }

    # ── MISSION EXECUTION ────────────────────────────────────

    async def _execute_by_priority(self, missions: list[dict]) -> list[dict]:
        """Runs missions in parallel by priority groups."""
        if not missions:
            return []

        groups: dict[int, list] = {}
        for m in missions:
            p = m.get("priority", 99)
            groups.setdefault(p, []).append(m)

        all_results = []
        for priority in sorted(groups.keys()):
            group = groups[priority]
            logger.info(
                "[Orchestrator] Priority %d: %s",
                priority,
                [m.get("agent") for m in group],
            )
            tasks = [self._run_mission(m) for m in group]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    all_results.append(
                        {
                            "agent": group[i].get("agent"),
                            "success": False,
                            "error": str(r),
                        }
                    )
                else:
                    all_results.append(r)

        return all_results

    async def _run_mission(self, mission: dict) -> dict:
        """Runs a single mission."""
        agent_name = mission.get("agent", "")
        task = mission.get("task", "")
        topic = mission.get("target_topic", "")

        try:
            agent = await self._get_agent(agent_name)
            if not agent:
                return {
                    "agent": agent_name,
                    "success": False,
                    "error": f"Agent '{agent_name}' not found",
                }

            logger.info("[Orchestrator] Running: %s -> %s (%s)", agent_name, task, topic)
            result = await agent.run(mission)

            # Zapier notification temporarily disabled at the user's request
            # if result.get("success") and agent_name in ["cfo", "ecommerce"] and result.get("shop_url"):
            #     await self._notify_zapier_new_product(result)

            return result
        except Exception as exc:
            logger.error("[Orchestrator] Error in mission %s: %s", agent_name, exc)
            return {"agent": agent_name, "success": False, "error": str(exc)}

    async def _get_agent(self, name: str) -> BaseAgent | None:
        """Gets or loads an agent by name."""
        if name in self._agents:
            return self._agents[name]

        # Auto-discovery if not loaded
        self._auto_discover_agents()
        return self._agents.get(name)

    def _auto_discover_agents(self) -> None:
        """Dynamically loads all available agents."""
        try:
            from apps.core.agents.business.investor_agent import InvestorAgent
            from apps.core.agents.cfo_agent import CFOAgent
            from apps.core.agents.content_agent import ContentAgent
            from apps.core.agents.ecommerce_agent import EcommerceAgent
            from apps.core.agents.pm_agent import PMAgent

            self._agents["content"] = ContentAgent()
            self._agents["cfo"] = CFOAgent()
            self._agents["pm"] = PMAgent()
            self._agents["ecommerce"] = EcommerceAgent()
            self._agents["investor"] = InvestorAgent()

            # Optional or in-development agents
            try:
                from apps.core.agents.affiliate_agent import AffiliateAgent

                self._agents["affiliate"] = AffiliateAgent()
            except ImportError:
                logger.debug("[Orchestrator] AffiliateAgent not available")

            try:
                from apps.core.agents.social_agent import SocialAgent

                self._agents["social"] = SocialAgent()
            except ImportError:
                logger.debug("[Orchestrator] SocialAgent not available")

            logger.info("[Orchestrator] %d agents loaded successfully", len(self._agents))
        except Exception as exc:
            logger.error("[Orchestrator] Error in auto-discovery: %s", exc)

    def _extract_revenue_summary(self, results: list[dict]) -> dict:
        """Calculates a summary of the cycle's revenue and successes."""
        summary = {
            "total_revenue_usd": 0.0,
            "items_published": 0,
            "products_listed": 0,
            "missions_successful": 0,
            "missions_failed": 0,
        }
        for r in results:
            if r.get("success"):
                summary["missions_successful"] += 1
                summary["total_revenue_usd"] += float(r.get("revenue_usd", 0))
                if r.get("agent") == "content":
                    summary["items_published"] += 1
                if r.get("agent") in ["cfo", "ecommerce"]:
                    summary["products_listed"] += 1
            else:
                summary["missions_failed"] += 1
        return summary

    async def get_status(self) -> dict[str, Any]:
        """Returns the Orchestrator's current status for the Telegram bot."""
        if not self._agents:
            self._auto_discover_agents()

        caps = self.check_capabilities()
        return {
            "cycle_count": self._cycle_count,
            "agents_loaded": list(self._agents.keys()),
            "capabilities": dict.fromkeys(caps.get("available", []), True),
            "missing_capabilities": caps.get("unavailable", []),
        }

    async def _send_cycle_report(
        self, results: list, intelligence: dict, revenue: dict, duration: float
    ) -> None:
        """Sends the cycle report to Telegram with screenshots if any exist."""
        import html as _html

        from apps.core.tools.telegram_bot import get_bot

        bot = get_bot()
        chat_id = str(settings.TELEGRAM_CHAT_ID) if settings.TELEGRAM_CHAT_ID else None

        ok = revenue["missions_failed"] == 0
        icon = "✅" if ok else "⚠️"
        total_rev = revenue["total_revenue_usd"]
        foco = _html.escape(intelligence.get("top_opportunity", "Monetization"))
        misiones = f"{revenue['missions_successful']}/{len(results)}"

        kw = 11
        data_rows = [
            f"{'Duration':<{kw}} {duration:.1f}s",
            f"{'Revenue':<{kw}} ${total_rev:.2f}",
            f"{'Focus':<{kw}} {foco}",
            f"{'Missions':<{kw}} {misiones}",
        ]
        if revenue.get("products_listed", 0) > 0:
            data_rows.append(f"{'Products':<{kw}} {revenue['products_listed']}")

        sections = [
            f"{icon} <b>CYCLE #{self._cycle_count}  ·  COMPLETE</b>",
            "<pre>" + "\n".join(data_rows) + "</pre>",
        ]

        shop_url = getattr(settings, "SHOPIFY_URL", None) or getattr(
            settings, "SHOPIFY_SHOP_NAME", None
        )
        if shop_url:
            safe_url = _html.escape(str(shop_url))
            sections.append(f'  🛒 <a href="https://{safe_url}">Shopify →</a>')

        await bot.notify_owner("\n".join(sections), already_html=True)

        # Send screenshots if any are present in the results
        if chat_id:
            for r in results:
                if r.get("product_screenshot"):
                    await bot._send_photo(
                        chat_id,
                        r["product_screenshot"],
                        caption=f"📸 Product · {r.get('agent', 'ecommerce')}",
                    )
                market_research = r.get("market_research", {})
                if isinstance(market_research, dict) and market_research.get("screenshots"):
                    for ss_path in market_research["screenshots"]:
                        await bot._send_photo(
                            chat_id,
                            ss_path,
                            caption=f"🔍 Analysis · {r.get('agent', 'ecommerce')}",
                        )

    async def start(self) -> None:
        """Orchestrator initialization."""
        self._auto_discover_agents()
        logger.info("[Orchestrator] System ready.")

    async def stop(self) -> None:
        """Orchestrator cleanup."""
        logger.info("[Orchestrator] Shutting down...")
