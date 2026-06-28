"""
Aria AI — Sistema Operativo Núcleo v2.

Cambios vs v1:
  - ContinuousTrainer real (ya no importa módulo inexistente)
  - AriaMind arranca en lifespan
  - Scheduler NO spamea Telegram — solo logs
  - Startup message mínimo: ARIA ya está activa, sin detalles técnicos
  - v2.1: OpenTelemetry tracing + structured logging + Sentry + /metrics endpoint
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from apps.api.ratelimit import rate_limit
from apps.core.config_pkg import settings

# ── Observability bootstrap (FIRST — before any other imports) ────────────
from apps.core.observability.logging import configure_logging, get_logger
from apps.core.observability.metrics import get_metrics
from apps.core.observability.sentry import setup_sentry
from apps.core.observability.tracing import setup_tracing

configure_logging(level="INFO")
setup_tracing(service_name="aria-ai", service_version="2.0.0")
setup_sentry()

logger = get_logger("aria.core")

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client

TELEGRAM_API = "https://api.telegram.org/bot"
scheduler = AsyncIOScheduler(timezone="UTC")

_orchestrator: Any | None = None


async def get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is None:
        from apps.core.agents.orchestrator import Orchestrator

        _orchestrator = Orchestrator()
        await _orchestrator.start()
    return _orchestrator


# ── TELEGRAM UTILS ────────────────────────────────────────────────────────


async def send_telegram(message: str) -> bool:
    """Envía mensaje solo cuando es realmente necesario. No spamear."""
    if not settings.telegram_token or not settings.TELEGRAM_CHAT_ID:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                f"{TELEGRAM_API}{settings.telegram_token}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            return r.status_code == 200
    except Exception as exc:
        logger.error("Telegram error: %s", exc)
        return False


# ── REVENUE CHANNEL VALIDATOR ─────────────────────────────────────────────


async def _validate_revenue_channels() -> None:
    """Check all money-generating API credentials at startup, send Telegram summary."""
    await asyncio.sleep(10)  # let app finish booting
    import httpx as _hx

    lines: list[str] = ["<b>💰 ARIA Revenue Channel Status</b>"]

    # Gumroad
    try:
        if settings.GUMROAD_TOKEN:
            r = await _hx.AsyncClient(timeout=10.0).get(
                "https://api.gumroad.com/v2/products",
                params={"access_token": settings.GUMROAD_TOKEN},
            )
            data = r.json()
            if data.get("success"):
                n = len(data.get("products", []))
                lines.append(f"✅ Gumroad: OK ({n} products)")
            else:
                lines.append(f"❌ Gumroad: invalid token — {str(data)[:60]}")
        else:
            lines.append("⚠️ Gumroad: GUMROAD_TOKEN not set")
    except Exception as exc:
        lines.append(f"❌ Gumroad: {str(exc)[:60]}")

    # Dev.to
    try:
        if settings.DEVTO_API_KEY:
            r = await _hx.AsyncClient(timeout=10.0).get(
                "https://dev.to/api/users/me", headers={"api-key": settings.DEVTO_API_KEY}
            )
            if r.status_code == 200:
                username = r.json().get("username", "?")
                lines.append(f"✅ Dev.to: OK (@{username})")
            else:
                lines.append(f"❌ Dev.to: status {r.status_code}")
        else:
            lines.append("⚠️ Dev.to: DEVTO_API_KEY not set (using browser fallback)")
    except Exception as exc:
        lines.append(f"❌ Dev.to: {str(exc)[:60]}")

    # Stripe
    try:
        sk = getattr(settings, "STRIPE_SECRET_KEY", None)
        if sk:
            r = await _hx.AsyncClient(timeout=10.0).get(
                "https://api.stripe.com/v1/products?limit=3", auth=(sk, "")
            )
            if r.status_code == 200:
                n = len(r.json().get("data", []))
                lines.append(f"✅ Stripe: OK ({n} products found)")
            else:
                lines.append(f"❌ Stripe: status {r.status_code} — check STRIPE_SECRET_KEY")
        else:
            lines.append("⚠️ Stripe: STRIPE_SECRET_KEY not set")
    except Exception as exc:
        lines.append(f"❌ Stripe: {str(exc)[:60]}")

    # Twitter
    try:
        tw_key = getattr(settings, "TWITTER_API_KEY", None)
        tw_sec = getattr(settings, "TWITTER_API_SECRET", None)
        tw_tok = getattr(settings, "TWITTER_ACCESS_TOKEN", None)
        tw_tsec = getattr(settings, "TWITTER_ACCESS_SECRET", None)
        if all([tw_key, tw_sec, tw_tok, tw_tsec]):
            lines.append("✅ Twitter: credentials configured (OAuth1)")
        else:
            missing = [
                k
                for k, v in {
                    "API_KEY": tw_key,
                    "API_SECRET": tw_sec,
                    "ACCESS_TOKEN": tw_tok,
                    "ACCESS_SECRET": tw_tsec,
                }.items()
                if not v
            ]
            lines.append(f"⚠️ Twitter: missing {', '.join(missing)}")
    except Exception as exc:
        lines.append(f"❌ Twitter: {str(exc)[:60]}")

    # LinkedIn
    try:
        lk_tok = getattr(settings, "LINKEDIN_ACCESS_TOKEN", None)
        lk_urn = getattr(settings, "LINKEDIN_PERSON_URN", None)
        if lk_tok and lk_urn:
            lines.append("✅ LinkedIn: credentials configured")
        elif lk_tok:
            lines.append("⚠️ LinkedIn: token OK but LINKEDIN_PERSON_URN missing")
        else:
            lines.append("⚠️ LinkedIn: LINKEDIN_ACCESS_TOKEN not set")
    except Exception as exc:
        lines.append(f"❌ LinkedIn: {str(exc)[:60]}")

    # SendGrid (email campaigns)
    try:
        sg_key = getattr(settings, "SENDGRID_API_KEY", None)
        if sg_key:
            lines.append("✅ SendGrid: API key configured")
        else:
            lines.append("⚠️ SendGrid: SENDGRID_API_KEY not set (email campaigns disabled)")
    except Exception:
        pass

    # ARIA browser credentials
    try:
        if settings.ARIA_EMAIL and settings.ARIA_PASSWORD:
            lines.append(f"✅ Browser: ARIA_EMAIL set ({settings.ARIA_EMAIL[:20]}...)")
        else:
            lines.append("⚠️ Browser: ARIA_EMAIL/ARIA_PASSWORD not set (stealth browser disabled)")
    except Exception:
        pass

    msg = "\n".join(lines)
    logger.info("[RevenueCheck] %s", msg.replace("<b>", "").replace("</b>", ""))
    await send_telegram(msg)


# ── LIFESPAN ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    # 1. Registrar webhook de Telegram
    try:
        from apps.core.tools.telegram_bot import get_bot

        bot = get_bot()
        webhook_url = "https://aria-ai.fly.dev/telegram/webhook"
        ok = await bot.set_webhook(webhook_url)
        if ok:
            logger.info("Telegram webhook registrado: %s", webhook_url)
            # Mensaje mínimo de startup — sin dump técnico
            await send_telegram("✅ ARIA en línea.")
        else:
            logger.warning("Webhook de Telegram no se pudo registrar")
    except Exception as exc:
        logger.error("Error startup webhook: %s", exc)

    # 2. ContinuousTrainer (background, silencioso)
    try:
        from apps.core.training.continuous_trainer import get_trainer

        asyncio.create_task(get_trainer().run_forever())
        logger.info("ContinuousTrainer 24/7 activo")
    except Exception as exc:
        logger.error("Error iniciando ContinuousTrainer: %s", exc)

    # 2b. IncomeLoop 24/7 — autonomous income generation every 20 min
    try:
        from apps.core.tools.income_loop import INTERVAL_SECONDS as _IL_INTERVAL
        from apps.core.tools.income_loop import get_income_loop

        await get_income_loop().start()
        logger.info("IncomeLoop 24/7 activo (cada %ds = %.0fmin)", _IL_INTERVAL, _IL_INTERVAL / 60)
    except Exception as exc:
        logger.error("Error iniciando IncomeLoop: %s", exc)

    # 2c. Revenue channel health check — validates all money APIs on startup
    asyncio.create_task(_validate_revenue_channels())

    # 3. AriaMind precarga (para que el primer mensaje no tenga cold start)
    try:
        from apps.core.cognition.aria_mind import get_aria_mind

        get_aria_mind()
        logger.info("AriaMind inicializada")
    except Exception as exc:
        logger.error("Error precargando AriaMind: %s", exc)

    # 3b. TaskManager — persistent background task queue
    try:
        from apps.core.tools.task_manager import get_task_manager

        get_task_manager().start(workers=3)
        logger.info("TaskManager iniciado (3 workers)")
    except Exception as exc:
        logger.error("Error iniciando TaskManager: %s", exc)

    # 3c. Enterprise runtime: task queue worker + world model init
    try:
        from apps.core.runtime.task_queue import get_task_queue

        await get_task_queue().start_worker()
        logger.info("TaskQueue worker started (4-priority Redis streams)")
    except Exception as exc:
        logger.error("Error iniciando TaskQueue worker: %s", exc)

    try:
        from apps.core.world_model.entity_registry import get_entity_registry

        await get_entity_registry().load()
        logger.info("World model entity registry initialized")
    except Exception as exc:
        logger.error("Error inicializando WorldModel: %s", exc)

    # 3d. Phase 3 enterprise systems: memory orchestrator, tool registry, agent hierarchy, quality
    try:
        from apps.core.memory.orchestrator import get_memory_orchestrator

        get_memory_orchestrator()
        logger.info("Memory Orchestrator initialized (unified 3-layer retrieval)")
    except Exception as exc:
        logger.error("Error iniciando MemoryOrchestrator: %s", exc)

    try:
        from apps.core.agents.hierarchy.agent_hierarchy import get_agent_hierarchy

        get_agent_hierarchy()
        logger.info("Agent Hierarchy bootstrapped (executive → director → specialist)")
    except Exception as exc:
        logger.error("Error iniciando AgentHierarchy: %s", exc)

    try:
        from apps.core.cognition.pipeline.cognitive_pipeline import get_cognitive_pipeline

        get_cognitive_pipeline()
        logger.info("Cognitive Pipeline initialized (5-stage async)")
    except Exception as exc:
        logger.error("Error iniciando CognitivePipeline: %s", exc)

    try:
        from apps.core.observability.cognition.reasoning_tracer import get_reasoning_tracer

        get_reasoning_tracer()
        logger.info("Reasoning Tracer initialized (hallucination detection active)")
    except Exception as exc:
        logger.error("Error iniciando ReasoningTracer: %s", exc)

    # 3e. Phase 4 platform systems: event bus, rule engine, executive agent, tiered memory, BI telemetry
    try:
        from apps.core.events.bus import get_event_bus

        get_event_bus()
        logger.info("Event Bus initialized (Redis-backed, Kafka-compatible interface)")
    except Exception as exc:
        logger.error("Error iniciando EventBus: %s", exc)

    try:
        from apps.core.deterministic.rule_engine import get_rule_engine

        get_rule_engine()
        logger.info("Rule Engine initialized (6 deterministic governance rules)")
    except Exception as exc:
        logger.error("Error iniciando RuleEngine: %s", exc)

    try:
        from apps.core.agents.executive.executive_agent import get_executive_agent

        get_executive_agent()
        logger.info("Executive Agent initialized (task arbitration + budget enforcement)")
    except Exception as exc:
        logger.error("Error iniciando ExecutiveAgent: %s", exc)

    try:
        from apps.core.memory.tiering.tiered_memory import get_tiered_memory

        get_tiered_memory()
        logger.info("Tiered Memory initialized (HOT/WARM/COLD hierarchy)")
    except Exception as exc:
        logger.error("Error iniciando TieredMemory: %s", exc)

    try:
        from apps.core.business.intelligence.bi_telemetry import get_bi_telemetry

        get_bi_telemetry()
        logger.info("BI Telemetry initialized (workflow profitability tracking)")
    except Exception as exc:
        logger.error("Error iniciando BITelemetry: %s", exc)

    # 4. Scheduler (ciclos autónomos, SIN notificaciones Telegram automáticas)
    try:
        scheduler.add_job(
            autonomous_cycle_job,
            IntervalTrigger(minutes=settings.CYCLE_INTERVAL_MINUTES),
            id="autonomous_cycle",
            replace_existing=True,
        )
        scheduler.add_job(
            heartbeat_job, IntervalTrigger(minutes=5), id="heartbeat", replace_existing=True
        )
        scheduler.start()
        logger.info("Scheduler iniciado (ciclo cada %d min)", settings.CYCLE_INTERVAL_MINUTES)
    except Exception as exc:
        logger.error("Error scheduler: %s", exc)

    # 5. Phase 5 autonomous business systems
    try:
        from apps.business.growth.growth_engine import get_growth_engine

        get_growth_engine()
        logger.info(
            "Growth Engine initialized (8 loops: shopify_seo, content, social, email, affiliate, youtube, linkedin, paid)"
        )
    except Exception as exc:
        logger.error("Error iniciando GrowthEngine: %s", exc)

    try:
        from apps.business.ecommerce.shopify_operator import get_shopify_operator

        get_shopify_operator()
        logger.info("Shopify Operator initialized (autonomous catalog optimization)")
    except Exception as exc:
        logger.error("Error iniciando ShopifyOperator: %s", exc)

    try:
        from apps.content.content_os import get_content_os

        get_content_os()
        logger.info("Content OS initialized (multi-platform content pipeline)")
    except Exception as exc:
        logger.error("Error iniciando ContentOS: %s", exc)

    try:
        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler

        _auto_sched = get_autonomous_scheduler()
        asyncio.create_task(_auto_sched.continuous_loop(interval_seconds=300))
        logger.info(
            "Autonomous Scheduler RUNNING (36 strategic objectives, 24/7 execution — check every 5min)"
        )
    except Exception as exc:
        logger.error("Error iniciando AutonomousScheduler: %s", exc)

    try:
        from apps.business.economics.economic_engine import get_economic_engine

        get_economic_engine()
        logger.info("Economic Intelligence Engine initialized (CAC/LTV/ROI optimization)")
    except Exception as exc:
        logger.error("Error iniciando EconomicEngine: %s", exc)

    try:
        from apps.business.crm.crm_engine import get_crm_engine

        get_crm_engine()
        logger.info("CRM Engine initialized (lead tracking + churn prediction)")
    except Exception as exc:
        logger.error("Error iniciando CRMEngine: %s", exc)

    # 6. Phase 6 autonomous media + creative infrastructure
    try:
        from apps.multimodal.images.image_generator import get_image_generator

        get_image_generator()
        logger.info("Image Generator initialized (FLUX/SDXL/Ideogram/DALL-E/Mock)")
    except Exception as exc:
        logger.error("Error iniciando ImageGenerator: %s", exc)

    try:
        from apps.branding.identity.brand_engine import get_brand_engine

        get_brand_engine()
        logger.info("Brand Engine initialized (persistent brand profiles)")
    except Exception as exc:
        logger.error("Error iniciando BrandEngine: %s", exc)

    try:
        from apps.factory.content.content_factory import get_content_factory

        get_content_factory()
        logger.info("Content Factory initialized (industrial-scale batch production)")
    except Exception as exc:
        logger.error("Error iniciando ContentFactory: %s", exc)

    try:
        from apps.factory.ads.ad_factory import get_ad_factory

        get_ad_factory()
        logger.info("Ad Factory initialized (multi-platform ad creative generation)")
    except Exception as exc:
        logger.error("Error iniciando AdFactory: %s", exc)

    try:
        from apps.distribution.social.social_publisher import get_social_publisher

        get_social_publisher()
        logger.info("Social Publisher initialized (scheduled publishing across platforms)")
    except Exception as exc:
        logger.error("Error iniciando SocialPublisher: %s", exc)

    try:
        from apps.revenue.attribution.revenue_tracker import get_revenue_tracker

        get_revenue_tracker()
        logger.info("Revenue Tracker initialized (multi-touch attribution)")
    except Exception as exc:
        logger.error("Error iniciando RevenueTracker: %s", exc)

    try:
        from apps.revenue.optimization.revenue_optimizer import get_revenue_optimizer

        get_revenue_optimizer()
        logger.info("Revenue Optimizer initialized (quick wins + scenario planning)")
    except Exception as exc:
        logger.error("Error iniciando RevenueOptimizer: %s", exc)

    try:
        from apps.infra.gpu.gpu_orchestrator import get_gpu_orchestrator

        get_gpu_orchestrator()
        logger.info("GPU Orchestrator initialized (Modal/RunPod/Mock backends)")
    except Exception as exc:
        logger.error("Error iniciando GPUOrchestrator: %s", exc)

    # 7. Phase 7 strategic economic intelligence
    try:
        from apps.market.trends.trend_analyzer import get_trend_analyzer

        get_trend_analyzer()
        logger.info("Trend Analyzer initialized (market signal detection)")
    except Exception as exc:
        logger.error("Error iniciando TrendAnalyzer: %s", exc)

    try:
        from apps.market.competition.competitor_monitor import get_competitor_monitor

        get_competitor_monitor()
        logger.info("Competitor Monitor initialized (competitive intelligence)")
    except Exception as exc:
        logger.error("Error iniciando CompetitorMonitor: %s", exc)

    try:
        from apps.market.demand.demand_scorer import get_demand_scorer

        get_demand_scorer()
        logger.info("Demand Scorer initialized (opportunity scoring)")
    except Exception as exc:
        logger.error("Error iniciando DemandScorer: %s", exc)

    try:
        from apps.market.opportunities.opportunity_finder import get_opportunity_finder

        get_opportunity_finder()
        logger.info("Opportunity Finder initialized (ROI-ranked opportunities)")
    except Exception as exc:
        logger.error("Error iniciando OpportunityFinder: %s", exc)

    try:
        from apps.content.intelligence.content_quality_engine import get_content_quality_engine

        get_content_quality_engine()
        logger.info("Content Quality Engine initialized (8-dimension quality scoring)")
    except Exception as exc:
        logger.error("Error iniciando ContentQualityEngine: %s", exc)

    try:
        from apps.content.scoring.engagement_predictor import get_engagement_predictor

        get_engagement_predictor()
        logger.info("Engagement Predictor initialized (platform-aware predictions)")
    except Exception as exc:
        logger.error("Error iniciando EngagementPredictor: %s", exc)

    try:
        from apps.content.virality.virality_engine import get_virality_engine

        get_virality_engine()
        logger.info("Virality Engine initialized (10 viral patterns)")
    except Exception as exc:
        logger.error("Error iniciando ViralityEngine: %s", exc)

    try:
        from apps.learning.economics.economic_learner import get_economic_learner

        get_economic_learner()
        logger.info("Economic Learner initialized (channel ROI learning)")
    except Exception as exc:
        logger.error("Error iniciando EconomicLearner: %s", exc)

    try:
        from apps.learning.conversion.conversion_learner import get_conversion_learner

        get_conversion_learner()
        logger.info("Conversion Learner initialized (funnel intelligence)")
    except Exception as exc:
        logger.error("Error iniciando ConversionLearner: %s", exc)

    try:
        from apps.psychology.personas.persona_engine import get_persona_engine

        get_persona_engine()
        logger.info("Persona Engine initialized (8 audience archetypes)")
    except Exception as exc:
        logger.error("Error iniciando PersonaEngine: %s", exc)

    try:
        from apps.psychology.behavior.behavior_analyzer import get_behavior_analyzer

        get_behavior_analyzer()
        logger.info("Behavior Analyzer initialized (user segmentation + churn prediction)")
    except Exception as exc:
        logger.error("Error iniciando BehaviorAnalyzer: %s", exc)

    try:
        from apps.psychology.conversion.persuasion_engine import get_persuasion_engine

        get_persuasion_engine()
        logger.info("Persuasion Engine initialized (8 Cialdini principles)")
    except Exception as exc:
        logger.error("Error iniciando PersuasionEngine: %s", exc)

    try:
        from apps.strategy.prioritization.priority_engine import get_priority_engine

        get_priority_engine()
        logger.info("Priority Engine initialized (effort-impact ranking)")
    except Exception as exc:
        logger.error("Error iniciando PriorityEngine: %s", exc)

    try:
        from apps.strategy.leverage.leverage_analyzer import get_leverage_analyzer

        get_leverage_analyzer()
        logger.info("Leverage Analyzer initialized (constraint removal planning)")
    except Exception as exc:
        logger.error("Error iniciando LeverageAnalyzer: %s", exc)

    try:
        from apps.strategy.forecasting.strategic_forecaster import get_strategic_forecaster

        get_strategic_forecaster()
        logger.info("Strategic Forecaster initialized (LINEAR/EXPONENTIAL/S_CURVE/PLATEAU)")
    except Exception as exc:
        logger.error("Error iniciando StrategicForecaster: %s", exc)

    try:
        from apps.creative.style.style_engine import get_style_engine

        get_style_engine()
        logger.info("Style Engine initialized (brand style profiles)")
    except Exception as exc:
        logger.error("Error iniciando StyleEngine: %s", exc)

    try:
        from apps.creative.differentiation.differentiation_engine import get_differentiation_engine

        get_differentiation_engine()
        logger.info("Differentiation Engine initialized (17 generic phrase detection)")
    except Exception as exc:
        logger.error("Error iniciando DifferentiationEngine: %s", exc)

    try:
        from apps.creative.identity.creative_identity import get_creative_identity_manager

        get_creative_identity_manager()
        logger.info("Creative Identity Manager initialized (voice + novelty tracking)")
    except Exception as exc:
        logger.error("Error iniciando CreativeIdentityManager: %s", exc)

    try:
        from apps.autonomy.goals.goal_manager import get_goal_manager

        get_goal_manager()
        logger.info("Goal Manager initialized (autonomous goal tracking)")
    except Exception as exc:
        logger.error("Error iniciando GoalManager: %s", exc)

    try:
        from apps.autonomy.revenue_loops.revenue_loop_engine import get_revenue_loop_engine

        get_revenue_loop_engine()
        logger.info("Revenue Loop Engine initialized (autonomous economic loops)")
    except Exception as exc:
        logger.error("Error iniciando RevenueLoopEngine: %s", exc)

    try:
        from apps.autonomy.self_direction.self_director import get_self_director

        get_self_director()
        logger.info("Self Director initialized (SCALE/OPTIMIZE/PIVOT directives)")
    except Exception as exc:
        logger.error("Error iniciando SelfDirector: %s", exc)

    try:
        from apps.business.operations.operations_manager import get_operations_manager

        get_operations_manager()
        logger.info("Operations Manager initialized (KPI dashboard)")
    except Exception as exc:
        logger.error("Error iniciando OperationsManager: %s", exc)

    try:
        from apps.business.executive.executive_dashboard import get_executive_dashboard

        get_executive_dashboard()
        logger.info("Executive Dashboard initialized (strategic snapshots)")
    except Exception as exc:
        logger.error("Error iniciando ExecutiveDashboard: %s", exc)

    try:
        from apps.business.finance.cashflow_engine import get_cashflow_engine

        get_cashflow_engine()
        logger.info("Cashflow Engine initialized (runway + forecast)")
    except Exception as exc:
        logger.error("Error iniciando CashflowEngine: %s", exc)

    try:
        from apps.business.analytics.business_analytics import get_business_analytics

        get_business_analytics()
        logger.info("Business Analytics initialized (funnel + cohort + attribution)")
    except Exception as exc:
        logger.error("Error iniciando BusinessAnalytics: %s", exc)

    # 8. Phase 8 cognitive infrastructure upgrade
    try:
        from apps.cognition.langgraph.cognitive_agent import get_cognitive_agent

        get_cognitive_agent()
        logger.info("Cognitive Agent initialized (LangGraph StateGraph + fallback)")
    except Exception as exc:
        logger.error("Error iniciando CognitiveAgent: %s", exc)

    try:
        from apps.cognition.dspy.optimizer import get_prompt_optimizer

        get_prompt_optimizer()
        logger.info("Prompt Optimizer initialized (DSPy + fallback)")
    except Exception as exc:
        logger.error("Error iniciando PromptOptimizer: %s", exc)

    try:
        from apps.memory.vector.memory_retriever import get_memory_retriever

        get_memory_retriever()
        logger.info("Memory Retriever initialized (Qdrant vector store + in-memory fallback)")
    except Exception as exc:
        logger.error("Error iniciando MemoryRetriever: %s", exc)

    try:
        from apps.memory.graph.knowledge_graph import get_knowledge_graph

        get_knowledge_graph()
        logger.info("Knowledge Graph initialized (NetworkX + Neo4j optional)")
    except Exception as exc:
        logger.error("Error iniciando KnowledgeGraph: %s", exc)

    try:
        from apps.evaluation.phoenix.tracer import get_cognition_tracer

        get_cognition_tracer()
        logger.info("Cognition Tracer initialized (Arize Phoenix + in-memory)")
    except Exception as exc:
        logger.error("Error iniciando CognitionTracer: %s", exc)

    try:
        from apps.evaluation.phoenix.evaluator import get_ai_evaluator

        get_ai_evaluator()
        logger.info("AI Evaluator initialized (6-dimension quality + hallucination scoring)")
    except Exception as exc:
        logger.error("Error iniciando AIEvaluator: %s", exc)

    try:
        from apps.runtime.celery.task_runner import get_task_runner

        get_task_runner()
        logger.info("Task Runner initialized (Celery distributed + inline fallback)")
    except Exception as exc:
        logger.error("Error iniciando TaskRunner: %s", exc)

    # 9. Phase 9 economic autonomy systems
    try:
        from apps.content.seo.seo_engine import get_seo_engine

        get_seo_engine()
        logger.info("SEO Engine initialized")
    except Exception as exc:
        logger.error("Error iniciando SEOEngine: %s", exc)

    try:
        from apps.content.blog.content_calendar import get_content_calendar

        get_content_calendar()
        logger.info("Content Calendar initialized")
    except Exception as exc:
        logger.error("Error iniciando ContentCalendar: %s", exc)

    try:
        from apps.shopify.offers.flash_sale_engine import get_flash_sale_engine

        get_flash_sale_engine()
        logger.info("Flash Sale Engine initialized")
    except Exception as exc:
        logger.error("Error iniciando FlashSaleEngine: %s", exc)

    try:
        from apps.shopify.revenue.cart_recovery import get_cart_recovery_engine

        get_cart_recovery_engine()
        logger.info("Cart Recovery Engine initialized")
    except Exception as exc:
        logger.error("Error iniciando CartRecoveryEngine: %s", exc)

    try:
        from apps.conversion.quiz.quiz_engine import get_quiz_engine

        get_quiz_engine()
        logger.info("Quiz Engine initialized")
    except Exception as exc:
        logger.error("Error iniciando QuizEngine: %s", exc)

    try:
        from apps.conversion.quiz.lead_scorer import get_lead_scorer

        get_lead_scorer()
        logger.info("Lead Scorer initialized")
    except Exception as exc:
        logger.error("Error iniciando LeadScorer: %s", exc)

    try:
        from apps.ads.retargeting.retargeting_engine import get_retargeting_engine

        get_retargeting_engine()
        logger.info("Retargeting Engine initialized")
    except Exception as exc:
        logger.error("Error iniciando RetargetingEngine: %s", exc)

    try:
        from apps.ads.audiences.audience_segmenter import get_audience_segmenter

        get_audience_segmenter()
        logger.info("Audience Segmenter initialized")
    except Exception as exc:
        logger.error("Error iniciando AudienceSegmenter: %s", exc)

    try:
        from apps.learning.optimization.reinforcement_optimizer import get_reinforcement_optimizer

        get_reinforcement_optimizer()
        logger.info("Reinforcement Optimizer initialized (UCB1 bandit)")
    except Exception as exc:
        logger.error("Error iniciando ReinforcementOptimizer: %s", exc)

    try:
        from apps.market.intelligence.market_intelligence import get_market_intelligence

        get_market_intelligence()
        logger.info("Market Intelligence initialized")
    except Exception as exc:
        logger.error("Error iniciando MarketIntelligence: %s", exc)

    try:
        from apps.orchestration.growth_orchestrator import get_growth_orchestrator

        get_growth_orchestrator()
        logger.info("Growth Orchestrator initialized (central economic brain)")
    except Exception as exc:
        logger.error("Error iniciando GrowthOrchestrator: %s", exc)

    try:
        from apps.orchestration.resource_allocator import get_resource_allocator

        get_resource_allocator()
        logger.info("Resource Allocator initialized")
    except Exception as exc:
        logger.error("Error iniciando ResourceAllocator: %s", exc)

    # 10. Phase 10: Autonomous AI-Native Economic Organization
    try:
        from apps.executive.ceo_agent import get_ceo_agent

        get_ceo_agent()
        logger.info("CEO Agent initialized")
    except Exception as exc:
        logger.error("Error iniciando CEOAgent: %s", exc)

    try:
        from apps.executive.coo_agent import get_coo_agent

        get_coo_agent()
        logger.info("COO Agent initialized")
    except Exception as exc:
        logger.error("Error iniciando COOAgent: %s", exc)

    try:
        from apps.executive.cto_agent import get_cto_agent

        get_cto_agent()
        logger.info("CTO Agent initialized")
    except Exception as exc:
        logger.error("Error iniciando CTOAgent: %s", exc)

    try:
        from apps.executive.cfo_agent import get_cfo_agent

        get_cfo_agent()
        logger.info("CFO Agent initialized")
    except Exception as exc:
        logger.error("Error iniciando CFOAgent: %s", exc)

    try:
        from apps.executive.cmo_agent import get_cmo_agent

        get_cmo_agent()
        logger.info("CMO Agent initialized")
    except Exception as exc:
        logger.error("Error iniciando CMOAgent: %s", exc)

    try:
        from apps.executive.executive_council import get_executive_council

        get_executive_council()
        logger.info("Executive Council initialized (CEO+COO+CTO+CFO+CMO)")
    except Exception as exc:
        logger.error("Error iniciando ExecutiveCouncil: %s", exc)

    try:
        from apps.workforce.engineering.engineering_division import get_engineering_division

        get_engineering_division()
        logger.info("Engineering Division initialized (6 agents)")
    except Exception as exc:
        logger.error("Error iniciando EngineeringDivision: %s", exc)

    try:
        from apps.workforce.design.design_division import get_design_division

        get_design_division()
        logger.info("Design Division initialized (6 agents)")
    except Exception as exc:
        logger.error("Error iniciando DesignDivision: %s", exc)

    try:
        from apps.workforce.marketing.marketing_division import get_marketing_division

        get_marketing_division()
        logger.info("Marketing Division initialized")
    except Exception as exc:
        logger.error("Error iniciando MarketingDivision: %s", exc)

    try:
        from apps.workforce.content.content_division import get_content_division

        get_content_division()
        logger.info("Content Division initialized")
    except Exception as exc:
        logger.error("Error iniciando ContentDivision: %s", exc)

    try:
        from apps.workforce.operations.operations_division import get_operations_division

        get_operations_division()
        logger.info("Operations Division initialized")
    except Exception as exc:
        logger.error("Error iniciando OperationsDivision: %s", exc)

    try:
        from apps.workforce.analytics.analytics_division import get_analytics_division

        get_analytics_division()
        logger.info("Analytics Division initialized")
    except Exception as exc:
        logger.error("Error iniciando AnalyticsDivision: %s", exc)

    try:
        from apps.economics.economic_intelligence import get_economic_intelligence

        get_economic_intelligence()
        logger.info("Economic Intelligence initialized")
    except Exception as exc:
        logger.error("Error iniciando EconomicIntelligence: %s", exc)

    try:
        from apps.economics.roi_tracker import get_roi_tracker

        get_roi_tracker()
        logger.info("ROI Tracker initialized")
    except Exception as exc:
        logger.error("Error iniciando ROITracker: %s", exc)

    try:
        from apps.marketplace.client_acquisition import get_client_acquisition

        get_client_acquisition()
        logger.info("Client Acquisition initialized")
    except Exception as exc:
        logger.error("Error iniciando ClientAcquisition: %s", exc)

    try:
        from apps.marketplace.proposal_engine import get_proposal_engine

        get_proposal_engine()
        logger.info("Proposal Engine initialized")
    except Exception as exc:
        logger.error("Error iniciando ProposalEngine: %s", exc)

    # 11. Phase 11: Extended Economic Autonomy
    try:
        from apps.video.youtube.youtube_engine import get_youtube_engine

        get_youtube_engine()
        logger.info("YouTube Engine initialized (SEO + scripts + calendar)")
    except Exception as exc:
        logger.error("Error iniciando YouTubeEngine: %s", exc)

    try:
        from apps.video.shorts.shorts_engine import get_shorts_engine

        get_shorts_engine()
        logger.info("Shorts Engine initialized (TikTok/Reels/YouTube Shorts)")
    except Exception as exc:
        logger.error("Error iniciando ShortsEngine: %s", exc)

    try:
        from apps.video.automation.publishing_pipeline import get_publishing_pipeline

        get_publishing_pipeline()
        logger.info("Publishing Pipeline initialized (scheduled video publishing)")
    except Exception as exc:
        logger.error("Error iniciando PublishingPipeline: %s", exc)

    try:
        from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

        get_linkedin_outreach()
        logger.info("LinkedIn Outreach initialized (AI prospecting + sequences)")
    except Exception as exc:
        logger.error("Error iniciando LinkedInOutreach: %s", exc)

    try:
        from apps.acquisition.upwork.upwork_bidder import get_upwork_bidder

        get_upwork_bidder()
        logger.info("Upwork Bidder initialized (job evaluation + proposals)")
    except Exception as exc:
        logger.error("Error iniciando UpworkBidder: %s", exc)

    try:
        from apps.acquisition.fiverr.fiverr_optimizer import get_fiverr_optimizer

        get_fiverr_optimizer()
        logger.info("Fiverr Optimizer initialized (gig creation + SEO)")
    except Exception as exc:
        logger.error("Error iniciando FiverrOptimizer: %s", exc)

    try:
        from apps.acquisition.outreach.outreach_sequencer import get_outreach_sequencer

        get_outreach_sequencer()
        logger.info("Outreach Sequencer initialized (multi-channel sequences)")
    except Exception as exc:
        logger.error("Error iniciando OutreachSequencer: %s", exc)

    try:
        from apps.learning.roi.roi_learner import get_roi_learner

        get_roi_learner()
        logger.info("ROI Learner initialized (cross-channel pattern detection)")
    except Exception as exc:
        logger.error("Error iniciando ROILearner: %s", exc)

    try:
        from apps.learning.prioritization.priority_engine import (
            get_priority_engine as get_p11_priority_engine,
        )

        get_p11_priority_engine()
        logger.info("Priority Engine (P11) initialized (urgency + ROI boost scoring)")
    except Exception as exc:
        logger.error("Error iniciando PriorityEngine P11: %s", exc)

    try:
        from apps.conversion.sms.sms_capture import get_sms_capture_engine

        get_sms_capture_engine()
        logger.info("SMS Capture Engine initialized (Klaviyo SMS sync)")
    except Exception as exc:
        logger.error("Error iniciando SMSCaptureEngine: %s", exc)

    try:
        from apps.conversion.funnels.funnel_engine import get_funnel_engine

        get_funnel_engine()
        logger.info("Funnel Engine initialized (ecommerce/lead_gen/saas/quiz)")
    except Exception as exc:
        logger.error("Error iniciando FunnelEngine: %s", exc)

    try:
        from apps.market.pricing.pricing_intelligence import get_pricing_intelligence

        get_pricing_intelligence()
        logger.info("Pricing Intelligence initialized (competitor benchmarking)")
    except Exception as exc:
        logger.error("Error iniciando PricingIntelligence: %s", exc)

    try:
        from apps.content.internal_linking.linking_optimizer import get_linking_optimizer

        get_linking_optimizer()
        logger.info("Linking Optimizer initialized (pillar-cluster SEO)")
    except Exception as exc:
        logger.error("Error iniciando LinkingOptimizer: %s", exc)

    try:
        from apps.content.distribution.distribution_engine import get_distribution_engine

        get_distribution_engine()
        logger.info("Distribution Engine initialized (multi-channel adaptation)")
    except Exception as exc:
        logger.error("Error iniciando DistributionEngine: %s", exc)

    try:
        from apps.memory.economic.economic_memory import get_economic_memory

        get_economic_memory()
        logger.info("Economic Memory initialized (profitable patterns + failed strategies)")
    except Exception as exc:
        logger.error("Error iniciando EconomicMemory: %s", exc)

    try:
        from apps.memory.client.client_memory import get_client_memory

        get_client_memory()
        logger.info("Client Memory initialized (VIP/at-risk segmentation)")
    except Exception as exc:
        logger.error("Error iniciando ClientMemory: %s", exc)

    try:
        from apps.memory.workflow.workflow_memory import get_workflow_memory

        get_workflow_memory()
        logger.info("Workflow Memory initialized (success/failure pattern learning)")
    except Exception as exc:
        logger.error("Error iniciando WorkflowMemory: %s", exc)

    # ── Phase 12 — Revenue Activation ─────────────────────────────────────────
    try:
        from apps.shopify.seo.product_seo import get_product_seo_optimizer

        get_product_seo_optimizer()
        logger.info("Product SEO Optimizer initialized (Shopify organic traffic)")
    except Exception as exc:
        logger.error("Error iniciando ProductSEOOptimizer: %s", exc)

    try:
        from apps.shopify.funnels.shopify_funnels import get_shopify_funnel_engine

        get_shopify_funnel_engine()
        logger.info("Shopify Funnel Engine initialized (upsells, abandoned cart, landing pages)")
    except Exception as exc:
        logger.error("Error iniciando ShopifyFunnelEngine: %s", exc)

    try:
        from apps.execution.daily_runtime import get_daily_runtime

        get_daily_runtime()
        logger.info("Daily Runtime initialized (autonomous daily execution orchestrator)")
    except Exception as exc:
        logger.error("Error iniciando DailyRuntime: %s", exc)

    # ── Phase 13 — Distribution + Acquisition Scale ────────────────────────────
    try:
        from apps.distribution.linkedin.linkedin_publisher import get_linkedin_publisher

        get_linkedin_publisher()
        logger.info("LinkedIn Publisher initialized (authority content + B2B lead generation)")
    except Exception as exc:
        logger.error("Error iniciando LinkedInPublisher: %s", exc)

    try:
        from apps.distribution.twitter.twitter_engine import get_twitter_engine

        get_twitter_engine()
        logger.info("Twitter Engine initialized (viral threads + X distribution)")
    except Exception as exc:
        logger.error("Error iniciando TwitterEngine: %s", exc)

    try:
        from apps.distribution.tiktok.tiktok_engine import get_tiktok_engine

        get_tiktok_engine()
        logger.info("TikTok Engine initialized (short-form video factory)")
    except Exception as exc:
        logger.error("Error iniciando TikTokEngine: %s", exc)

    try:
        from apps.distribution.blog.blog_publisher import get_blog_publisher

        get_blog_publisher()
        logger.info("Blog Publisher initialized (SEO content + organic traffic)")
    except Exception as exc:
        logger.error("Error iniciando BlogPublisher: %s", exc)

    try:
        from apps.acquisition.leads.lead_engine import get_lead_engine

        get_lead_engine()
        logger.info("Lead Engine initialized (autonomous lead discovery + scoring)")
    except Exception as exc:
        logger.error("Error iniciando LeadEngine: %s", exc)

    try:
        from apps.acquisition.crm.crm_engine import get_crm_engine

        get_crm_engine()
        logger.info("CRM Engine initialized (pipeline tracking + revenue attribution)")
    except Exception as exc:
        logger.error("Error iniciando CRMEngine: %s", exc)

    try:
        from apps.conversion.landing_pages.landing_page_engine import get_landing_page_engine

        get_landing_page_engine()
        logger.info("Landing Page Engine initialized (A/B conversion optimization)")
    except Exception as exc:
        logger.error("Error iniciando LandingPageEngine: %s", exc)

    try:
        from apps.conversion.email_sequences.email_nurture import get_email_nurture_engine

        get_email_nurture_engine()
        logger.info("Email Nurture Engine initialized (automated lead → customer sequences)")
    except Exception as exc:
        logger.error("Error iniciando EmailNurtureEngine: %s", exc)

    try:
        from apps.runtime.daily_business_loop import get_daily_business_loop

        get_daily_business_loop()
        logger.info("Daily Business Loop initialized (full autonomous daily execution)")
    except Exception as exc:
        logger.error("Error iniciando DailyBusinessLoop: %s", exc)

    # ── Phase 14: Real-World Execution Layer ───────────────────────────────
    try:
        from apps.distribution.publishers.api_publisher import get_api_publisher

        get_api_publisher()
        logger.info("RealAPIPublisher initialized (Twitter/LinkedIn/TikTok live publishing)")
    except Exception as exc:
        logger.error("Error iniciando RealAPIPublisher: %s", exc)

    try:
        from apps.shopify.api_client import get_shopify_api_client

        get_shopify_api_client()
        logger.info("ShopifyAPIClient initialized (Shopify Admin API integration)")
    except Exception as exc:
        logger.error("Error iniciando ShopifyAPIClient: %s", exc)

    try:
        from apps.economics.dashboard import get_economic_dashboard

        get_economic_dashboard()
        logger.info("EconomicDashboard initialized (CTR/CAC/LTV/ROAS tracking)")
    except Exception as exc:
        logger.error("Error iniciando EconomicDashboard: %s", exc)

    try:
        from apps.acquisition.scraper.lead_scraper import get_lead_scraper

        get_lead_scraper()
        logger.info("LeadScraper initialized (web-based B2B lead discovery)")
    except Exception as exc:
        logger.error("Error iniciando LeadScraper: %s", exc)

    try:
        from apps.video.media.media_pipeline import get_media_pipeline

        get_media_pipeline()
        logger.info("MediaPipeline initialized (FFmpeg + ElevenLabs video generation)")
    except Exception as exc:
        logger.error("Error iniciando MediaPipeline: %s", exc)

    try:
        from apps.runtime.scheduler import get_aria_scheduler

        aria_sched = get_aria_scheduler()
        await aria_sched.start()
        logger.info(
            "ARIAScheduler started (APScheduler cron: morning/midday/daily/leads/analytics)"
        )
    except Exception as exc:
        logger.error("Error iniciando ARIAScheduler: %s", exc)

    logger.info("Aria OS activo.")
    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    try:
        from apps.core.tools.telegram_bot import get_bot

        await get_bot().close()
    except Exception:
        pass
    logger.info("Aria OS apagado.")


# ── SCHEDULER JOBS ────────────────────────────────────────────────────────


async def autonomous_cycle_job() -> None:
    """Ciclo autónomo. NO envía notificación a Telegram — solo ejecuta y loguea."""
    logger.info("[Scheduler] Ciclo autónomo iniciando...")
    cache = get_cache()
    locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
    if not locked:
        return
    try:
        await cache.set_agent_heartbeat("orchestrator")
        orch = await get_orchestrator()
        result = await orch.run_cycle()
        revenue = result.get("revenue_summary", {}).get("total_revenue_usd", 0)
        logger.info("[Scheduler] Ciclo completado. Revenue: $%.2f", revenue)

        # Solo notificar si hay ingresos reales (no spam de ciclos vacíos)
        if revenue > 0:
            await send_telegram(f"💰 Ciclo autónomo: <b>${revenue:.2f}</b> generados.")
    except Exception as exc:
        logger.error("[Scheduler] Error en ciclo: %s", exc)
    finally:
        await cache.release_lock("autonomous_cycle")


async def heartbeat_job() -> None:
    try:
        cache = get_cache()
        await cache.set_agent_heartbeat("system")
    except Exception:
        pass


# ── FASTAPI APP ───────────────────────────────────────────────────────────

app = FastAPI(title="Aria AI", version="2.0.0", lifespan=lifespan)

# Observability middleware — must be added BEFORE CORS so request IDs propagate
from apps.core.observability.middleware import AriaObservabilityMiddleware

app.add_middleware(AriaObservabilityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 routes
try:
    from apps.core.routes.api import router as api_router

    app.include_router(api_router)
    logger.info("API v1 montada en /api/v1")
except Exception as _e:
    logger.error("Error montando API v1: %s", _e)

# Mount inbound webhooks (lead capture, Stripe events) — used by the public
# landing page form at docs/index.html which POSTs to /api/webhooks/lead.
try:
    from apps.api.webhooks import router as webhooks_router

    app.include_router(webhooks_router)
    logger.info("Webhooks montados en /api/webhooks")
except Exception as _e:
    logger.error("Error montando webhooks: %s", _e)

# Serve static front-end assets (design system, images) — NOT docs/products (those
# are paid deliverables gated behind /access/{key}).
try:
    import pathlib as _pl

    from fastapi.staticfiles import StaticFiles

    for _assets in (
        _pl.Path("/app/docs/assets"),
        _pl.Path(__file__).resolve().parents[2] / "docs" / "assets",
    ):
        if _assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")
            logger.info("Static assets montados en /assets")
            break
except Exception as _e:
    logger.error("Error montando assets: %s", _e)


# Pricing tiers — (Stripe amount in cents, product label, USD dollars)
_ARIA_TIERS = {
    "starter": (2900, "ARIA Starter — $29/mo", 29),
    "pro": (9700, "ARIA Pro — $97/mo", 97),
    "agency": (49700, "ARIA Agency — $497/mo", 497),
}

# LIVE Stripe payment links (account "Aria_AI", livemode) — real money, real cards.
# Created via the live Stripe connector; these take priority over any test-mode key.
_ARIA_STRIPE_LINKS = {
    "starter": "https://buy.stripe.com/3cIaEXeRn3bTa2N1KLdQQ01",
    "pro": "https://buy.stripe.com/fZu00j9x38wdej3fBBdQQ00",
    "agency": "https://buy.stripe.com/bJe4gzgZv6o5grb4WXdQQ02",
}

# Public PayPal.Me handle for real payments (no API/secret needed — the handle is
# a public payment link). Set via the PAYPAL_ME_HANDLE env/secret, e.g. "geremypolanco"
# so /subscribe/{tier} sends buyers straight to paypal.me/<handle>/<amount>USD.
_ARIA_PAYPAL_ME = (
    (os.getenv("PAYPAL_ME_HANDLE") or "")
    .strip()
    .lstrip("@")
    .replace("https://paypal.me/", "")
    .replace("paypal.me/", "")
    .strip("/")
)


def _paypal_me_link(tier: str) -> str | None:
    """Return a real PayPal.Me payment URL for a tier, or None if no handle is set."""
    if not _ARIA_PAYPAL_ME or tier not in _ARIA_TIERS:
        return None
    dollars = _ARIA_TIERS[tier][2]
    return f"https://www.paypal.com/paypalme/{_ARIA_PAYPAL_ME}/{dollars}USD"


# PayPal REST API (Orders v2) — uses PAYPAL_CLIENT_ID + PAYPAL_SECRET secrets.
# Default to live; set PAYPAL_ENV=sandbox to test against sandbox credentials.
_PAYPAL_BASE = (
    "https://api-m.sandbox.paypal.com"
    if (os.getenv("PAYPAL_ENV") or "live").lower() == "sandbox"
    else "https://api-m.paypal.com"
)


async def _paypal_token_for(base: str) -> tuple[int, str | None]:
    """Try to get a PayPal token from a specific base URL. Returns (status, token|None)."""
    cid = getattr(settings, "PAYPAL_CLIENT_ID", None)
    secret = getattr(settings, "PAYPAL_SECRET", None)
    if not cid or not secret:
        return (0, None)
    try:
        import httpx as _hx

        async with _hx.AsyncClient(timeout=20) as hc:
            r = await hc.post(
                f"{base}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(cid, secret),
                headers={"Accept": "application/json"},
            )
            return (r.status_code, r.json().get("access_token") if r.status_code == 200 else None)
    except Exception:
        return (-1, None)


@app.get("/paypal/diag", dependencies=[Depends(rate_limit(10, 60, "diag"))])
async def paypal_diag():
    """Diagnose which PayPal environment the configured credentials belong to.

    Exposes NO secret values — only presence booleans and token HTTP statuses, so it
    is safe to hit publicly while wiring up payments.
    """
    cid = getattr(settings, "PAYPAL_CLIENT_ID", None)
    secret = getattr(settings, "PAYPAL_SECRET", None)
    live_status, live_tok = await _paypal_token_for("https://api-m.paypal.com")
    sand_status, sand_tok = await _paypal_token_for("https://api-m.sandbox.paypal.com")
    works = "live" if live_tok else ("sandbox" if sand_tok else "none")
    return {
        "client_id_present": bool(cid),
        "secret_present": bool(secret),
        "live_token_status": live_status,
        "sandbox_token_status": sand_status,
        "credentials_work_in": works,
        "active_base": _PAYPAL_BASE,
    }


# Digital product delivery — buyers are redirected here by Stripe after payment.
# Keys are non-obvious so the files aren't casually shareable; pages are noindex.
_PRODUCT_FILES = {
    "ai-prompts-x7k2q9": "200-ai-prompts.html",
    "playbook-m4p8w1c5": "ai-automation-playbook.html",
}


@app.get("/access/{key}", response_class=HTMLResponse)
async def product_access(key: str):
    """Serve a purchased digital product. Linked only from the post-payment redirect."""
    import pathlib

    fname = _PRODUCT_FILES.get(key)
    if not fname:
        return HTMLResponse("<h2>Invalid or expired download link.</h2>", status_code=404)
    for base in (
        pathlib.Path("/app/docs/products"),
        pathlib.Path(__file__).resolve().parents[2] / "docs" / "products",
    ):
        f = base / fname
        try:
            if f.is_file():
                return HTMLResponse(
                    f.read_text(encoding="utf-8"), headers={"X-Robots-Tag": "noindex"}
                )
        except Exception:
            continue
    return HTMLResponse(
        "<h2>Your product is being prepared — email saraph.core@gmail.com if it doesn't load.</h2>",
        status_code=503,
    )


@app.get("/api/v1/capabilities")
async def list_capabilities(check: bool = False):
    """ARIA's capability matrix: what it can do, quality, verified, and known gaps.

    Exposes no secret values — only capability names, statuses and required-secret
    *names*. ``?check=true`` additionally runs each capability's health check.
    """
    try:
        from apps.core.capabilities.registry import get_capability_registry

        reg = get_capability_registry()
        payload = {
            "summary": reg.summary(),
            "matrix": reg.matrix(),
            "gaps": reg.missing(),
        }
        if check:
            payload["health"] = await reg.check_all()
        return payload
    except Exception as exc:
        logger.error("[capabilities] endpoint error: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)[:200]})


# Public, PII-free labels for ARIA's strategy executions (keyword → icon + label).
# Order matters: first matching keyword wins. Keeps the public feed honest but safe.
_ACTIVITY_LABELS: list[tuple[tuple[str, ...], str, str]] = [
    (("proactive_client", "lead_", "prospect"), "🎯", "Researched new prospects"),
    (("linkedin_dm", "outreach", "cold_", "sms"), "💬", "Sent warm outreach"),
    (("proposal", "lead_closer", "deal"), "📨", "Prepared a client proposal"),
    (("agency_sales", "linkedin_post"), "📣", "Ran the sales engine"),
    (("viral", "content", "article", "blog", "ebook", "video"), "✍️", "Published content"),
    (("competitor", "research", "market", "trend"), "🔎", "Analyzed the market"),
    (("subscription", "stripe", "pricing", "payment"), "💳", "Tuned a payment offer"),
    (("shopify", "product", "gumroad", "saas", "course", "kit"), "🛠️", "Created a product"),
    (("email_capture", "funnel", "landing", "waitlist"), "🧲", "Built a lead funnel"),
    (("revenue_report", "analytics", "daily"), "📊", "Reviewed performance"),
]


def _activity_label(strategy: str) -> tuple[str, str]:
    s = (strategy or "").lower()
    for keys, icon, label in _ACTIVITY_LABELS:
        if any(k in s for k in keys):
            return icon, label
    return "⚡", "Ran a growth strategy"


@app.get("/welcome", response_class=HTMLResponse)
async def welcome(plan: str = ""):
    """Post-purchase onboarding — every paying customer lands here and receives real
    value immediately: instant digital products + a clear path to activate their ARIA.

    This is the anti-fraud guarantee: no one pays and receives nothing.
    """
    plan = (plan or "your").lower()
    plan_label = {
        "starter": "Starter",
        "pro": "Pro",
        "agency": "Agency",
        "dfy": "Done-For-You",
    }.get(plan, "ARIA")
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Welcome to ARIA — let's get you set up</title>
<link rel="stylesheet" href="/assets/aria-design-system.css">
<style>.wrap{{max-width:760px;margin:0 auto;padding:var(--s-8) var(--s-5)}}
.step{{display:flex;gap:var(--s-4);padding:var(--s-4) 0;border-bottom:1px solid var(--border)}}
.num{{flex:0 0 30px;height:30px;border-radius:9px;background:var(--surface-2);border:1px solid var(--border);color:var(--aria-accent);display:grid;place-items:center;font-weight:700;font-size:var(--fs-sm)}}</style>
</head><body>
<header class="nav"><div class="container nav-inner">
  <a class="brand" href="/"><img src="/assets/aria-logo.svg" width="28" height="28" alt=""> ARIA <span class="dim" style="font-weight:500;font-size:var(--fs-sm)">by Saraph</span></a>
</div></header>
<div class="wrap stack">
  <span class="badge badge-live"><span class="dot"></span> Payment received</span>
  <h1 class="h1">Welcome to ARIA {plan_label}.</h1>
  <p class="lead">You're in. Here's everything you get — starting right now.</p>

  <div class="card stack" style="margin-top:var(--s-4)">
    <div class="row"><span class="num">1</span><h2 class="h3">Your resources — instant access</h2></div>
    <p class="muted">Yours to keep, included with every plan:</p>
    <div class="row">
      <a class="btn btn-secondary" href="/access/ai-prompts-x7k2q9" target="_blank" rel="noopener">200 AI Prompts</a>
      <a class="btn btn-secondary" href="/access/playbook-m4p8w1c5" target="_blank" rel="noopener">The AI Automation Playbook</a>
    </div>
  </div>

  <div class="card stack">
    <div class="row"><span class="num">2</span><h2 class="h3">Activate ARIA for your business</h2></div>
    <p class="muted">Tell us about your business and we'll configure and launch your ARIA — finding clients, publishing, and running outreach for you. We set it up <strong>with</strong> you so it's tuned to your offers.</p>
    <a class="btn btn-primary" href="/#audit">Start my setup (2 min)</a>
  </div>

  <div class="step"><span class="num">3</span><div><strong>What happens next</strong><br><span class="muted">Within 24 hours you'll receive your personalized growth plan and your ARIA goes to work. Questions any time: <a href="mailto:saraph.core@gmail.com" style="color:var(--aria-accent-3)">saraph.core@gmail.com</a></span></div></div>

  <p class="dim center" style="margin-top:var(--s-5)"><a href="/" style="color:var(--text-muted)">← Back to ARIA</a></p>
</div></body></html>"""
    )


@app.get("/api/v1/activity/public", dependencies=[Depends(rate_limit(60, 60, "activity"))])
async def public_activity(limit: int = 12):
    """ARIA's recent real actions, sanitized for public display (the live landing feed).

    Reads the income-loop history and returns only a category label + relative time —
    never raw summaries (which can contain prospect names/emails). Returns an empty
    list (200) when there's no data so the client can fall back gracefully.
    """
    items: list[dict] = []
    with contextlib.suppress(Exception):
        import json as _json
        import time as _time

        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        if cache:
            limit = max(1, min(int(limit), 30))
            raw = await cache.lrange("aria:income:loop_history", -60, -1)
            now = _time.time()
            for entry in reversed(raw or []):
                try:
                    c = _json.loads(entry) if isinstance(entry, str) else entry
                except Exception:
                    continue
                if not isinstance(c, dict) or not c.get("success"):
                    continue
                icon, label = _activity_label(c.get("strategy", ""))
                ts = float(c.get("ts") or 0)
                items.append(
                    {
                        "icon": icon,
                        "label": label,
                        "ago_seconds": int(max(0, now - ts)) if ts else None,
                    }
                )
                if len(items) >= limit:
                    break
    return {"items": items}


async def _paypal_token() -> str | None:
    """Fetch a PayPal OAuth access token from client credentials. None if unset/failed."""
    cid = getattr(settings, "PAYPAL_CLIENT_ID", None)
    secret = getattr(settings, "PAYPAL_SECRET", None)
    if not cid or not secret:
        return None
    try:
        import httpx as _hx

        async with _hx.AsyncClient(timeout=20) as hc:
            r = await hc.post(
                f"{_PAYPAL_BASE}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(cid, secret),
                headers={"Accept": "application/json"},
            )
            if r.status_code == 200:
                return r.json().get("access_token")
            logger.warning("[paypal] token failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("[paypal] token error: %s", exc)
    return None


async def _create_paypal_order(tier: str) -> str | None:
    """Create a PayPal order for a tier and return the buyer approval URL (or None)."""
    if tier not in _ARIA_TIERS:
        return None
    token = await _paypal_token()
    if not token:
        return None
    dollars = _ARIA_TIERS[tier][2]
    label = _ARIA_TIERS[tier][1]
    try:
        import httpx as _hx

        async with _hx.AsyncClient(timeout=20) as hc:
            r = await hc.post(
                f"{_PAYPAL_BASE}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "amount": {"currency_code": "USD", "value": f"{dollars}.00"},
                            "description": label[:127],
                        }
                    ],
                    "application_context": {
                        "brand_name": "ARIA AI",
                        "user_action": "PAY_NOW",
                        "return_url": f"https://aria-ai.fly.dev/paypal/capture?tier={tier}",
                        "cancel_url": "https://aria-ai.fly.dev/?paypal=cancelled",
                    },
                },
            )
            if r.status_code in (200, 201):
                for link in r.json().get("links", []):
                    if link.get("rel") in ("approve", "payer-action"):
                        return link.get("href")
            else:
                logger.warning("[paypal] create order failed: %s %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.warning("[paypal] create order error: %s", exc)
    return None


async def _get_or_create_stripe_link(tier: str) -> str | None:
    """
    Return a live Stripe payment-link URL for a tier, creating it on first use.

    Checks the Redis cache first (populated here or by the aria_subscription_launch
    income-loop strategy). On a miss, and if STRIPE_SECRET_KEY is configured, creates
    the Stripe product → recurring price → payment link on the fly, caches it for 90
    days, and returns it. Returns None if Stripe isn't configured or the API fails, so
    the caller can fall back to the lead-capture landing. Never raises.
    """
    cache = None
    with contextlib.suppress(Exception):
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        if cache:
            cached = await cache.get(f"aria:stripe:link:{tier}")
            if cached:
                return cached.decode() if isinstance(cached, bytes) else str(cached)

    stripe_key = getattr(settings, "STRIPE_SECRET_KEY", None)
    if not stripe_key or tier not in _ARIA_TIERS:
        return None

    cents, label = _ARIA_TIERS[tier][0], _ARIA_TIERS[tier][1]
    try:
        import httpx as _hx

        async with _hx.AsyncClient(timeout=25) as hc:
            prod_r = await hc.post(
                "https://api.stripe.com/v1/products",
                data={"name": label, "description": f"ARIA AI {tier.title()} Plan"},
                auth=(stripe_key, ""),
            )
            if prod_r.status_code != 200:
                return None
            price_r = await hc.post(
                "https://api.stripe.com/v1/prices",
                data={
                    "product": prod_r.json()["id"],
                    "unit_amount": cents,
                    "currency": "usd",
                    "recurring[interval]": "month",
                },
                auth=(stripe_key, ""),
            )
            if price_r.status_code != 200:
                return None
            pl_r = await hc.post(
                "https://api.stripe.com/v1/payment_links",
                data={
                    "line_items[0][price]": price_r.json()["id"],
                    "line_items[0][quantity]": "1",
                },
                auth=(stripe_key, ""),
            )
            if pl_r.status_code != 200:
                return None
            link = pl_r.json().get("url", "")
            if link and cache:
                with contextlib.suppress(Exception):
                    await cache.set(f"aria:stripe:link:{tier}", link, ttl_seconds=86400 * 90)
            return link or None
    except Exception as exc:
        logger.warning("[subscribe] Stripe link creation failed for %s: %s", tier, exc)
        return None


@app.get("/stripe/diag", dependencies=[Depends(rate_limit(10, 60, "diag"))])
async def stripe_diag():
    """Report whether the configured Stripe key is live or test mode (no secret exposed)."""
    key = getattr(settings, "STRIPE_SECRET_KEY", None) or ""
    if key.startswith(("sk_live_", "rk_live_")):
        mode = "live"
    elif key.startswith(("sk_test_", "rk_test_")):
        mode = "test"
    else:
        mode = "unknown_or_missing"

    api_status = 0
    if key:
        with contextlib.suppress(Exception):
            import httpx as _hx

            async with _hx.AsyncClient(timeout=15) as hc:
                r = await hc.get("https://api.stripe.com/v1/balance", auth=(key, ""))
                api_status = r.status_code

    return {
        "stripe_key_present": bool(key),
        "stripe_key_mode": mode,
        "stripe_api_status": api_status,
        "accepts_real_money": mode == "live",
    }


@app.get("/subscribe/{tier}")
async def subscribe_redirect(tier: str):
    """
    Redirect a pricing-CTA click straight to a real payment page.

    Priority: (1) PayPal.Me — real money, no API key needed, live the moment a
    PAYPAL_ME_HANDLE is set; (2) a live Stripe checkout created on first use;
    (3) the lead-capture landing so the prospect is never dropped.
    """
    from fastapi.responses import RedirectResponse

    tier = (tier or "").lower().strip()
    if tier not in _ARIA_TIERS:
        return RedirectResponse(url="https://aria-ai.fly.dev", status_code=302)

    # 0. LIVE Stripe payment link (real money — highest priority)
    if _ARIA_STRIPE_LINKS.get(tier):
        return RedirectResponse(url=_ARIA_STRIPE_LINKS[tier], status_code=302)

    # 1. Real PayPal checkout via the REST API (PAYPAL_CLIENT_ID/SECRET configured)
    paypal_order = await _create_paypal_order(tier)
    if paypal_order:
        return RedirectResponse(url=paypal_order, status_code=302)

    # 2. PayPal.Me link (if a public handle is configured)
    paypal_me = _paypal_me_link(tier)
    if paypal_me:
        return RedirectResponse(url=paypal_me, status_code=302)

    # 3. Live Stripe checkout (created + cached on first use)
    link = await _get_or_create_stripe_link(tier)
    if link:
        return RedirectResponse(url=link, status_code=302)

    # 4. No live payment rail → lead-capture landing (served by this app)
    return RedirectResponse(url=f"/?plan={tier}", status_code=302)


@app.get("/paypal/capture", response_class=HTMLResponse)
async def paypal_capture(token: str = "", tier: str = ""):
    """
    PayPal return URL — captures the approved order so the money actually moves,
    records the sale, and shows the buyer a confirmation. ``token`` is the PayPal
    order id appended by PayPal on redirect.
    """
    captured = False
    amount = 0
    if token:
        access = await _paypal_token()
        if access:
            with contextlib.suppress(Exception):
                import httpx as _hx

                async with _hx.AsyncClient(timeout=20) as hc:
                    r = await hc.post(
                        f"{_PAYPAL_BASE}/v2/checkout/orders/{token}/capture",
                        headers={
                            "Authorization": f"Bearer {access}",
                            "Content-Type": "application/json",
                        },
                    )
                    if r.status_code in (200, 201):
                        data = r.json()
                        captured = data.get("status") == "COMPLETED"
                        with contextlib.suppress(Exception):
                            cap = data["purchase_units"][0]["payments"]["captures"][0]
                            amount = float(cap["amount"]["value"])

    # Record the real sale + alert the owner
    if captured:
        with contextlib.suppress(Exception):
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                import json as _json
                import time as _time

                await cache.rpush(
                    "aria:crm:subscribers",
                    _json.dumps(
                        {
                            "plan": tier,
                            "amount": amount,
                            "rail": "paypal",
                            "order": token,
                            "ts": _time.time(),
                        }
                    ),
                )
                await cache.increment("aria:revenue:paypal_total")
        with contextlib.suppress(Exception):
            from apps.core.tools.telegram_bot import get_bot

            await get_bot().notify_owner(
                f"💰 <b>REAL PAYMENT RECEIVED!</b>\n\n"
                f"Plan: <b>{tier.title()}</b>\nAmount: <b>${amount:.2f}</b>\n"
                f"Rail: PayPal\nOrder: {token}",
                already_html=True,
            )

    if captured:
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Thank you — ARIA AI</title>
<style>body{{font-family:-apple-system,Inter,sans-serif;max-width:560px;margin:8vh auto;padding:0 1.25rem;text-align:center;color:#1a1a2e}}
.card{{background:#f0fdf4;border:1px solid #86efac;border-radius:16px;padding:2.5rem}}h1{{color:#16a34a}}a{{color:#4f46e5}}</style></head>
<body><div class="card"><h1>✅ Payment received — thank you!</h1>
<p>Your <b>ARIA {tier.title()}</b> plan is active. We'll be in touch at the email on your PayPal account with next steps.</p>
<p><a href="https://aria-ai.fly.dev">← Back to ARIA</a></p></div></body></html>"""
        )
    return HTMLResponse(
        """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Payment status — ARIA AI</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:8vh auto;text-align:center">
<h2>We couldn't confirm your payment yet</h2>
<p>If you completed checkout, it may still be processing. Questions? Reply to your PayPal receipt.</p>
<p><a href="https://aria-ai.fly.dev">← Back to ARIA</a></p></body></html>""",
        status_code=200,
    )


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        from apps.core.tools.telegram_bot import get_bot

        await get_bot().handle_update(update)
    except Exception as exc:
        logger.error("Webhook error: %s", exc)
    return {"ok": True}


@app.get("/health")
async def health():
    """Liveness + lightweight component readiness probe."""
    components: dict[str, str] = {}

    # Redis (Upstash) reachability — non-fatal
    try:
        cache = get_cache()
        await cache.get("health:ping")
        components["redis"] = "ok"
    except Exception:
        components["redis"] = "unavailable"

    # AI client availability — non-fatal
    try:
        components["ai"] = "ok" if get_ai_client() is not None else "unavailable"
    except Exception:
        components["ai"] = "unavailable"

    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return {
        "status": status,
        "version": app.version,
        "components": components,
        "ts": datetime.now(UTC).isoformat(),
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible metrics endpoint. Scrape with Grafana or any Prom-compatible tool."""
    return get_metrics().to_prometheus()


@app.get("/api/v1/metrics")
async def api_metrics():
    """Structured metrics as JSON for dashboard consumption."""
    return get_metrics().to_dict()


@app.get("/api/v1/governance/audit")
async def governance_audit():
    """Security audit log — all policy decisions ARIA has made."""
    try:
        from apps.core.security.capabilities import get_policy_engine

        engine = get_policy_engine()
        return {
            "summary": engine.summary(),
            "recent": engine.get_audit_log(limit=50),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/world-model")
async def world_model_summary():
    """Summary of ARIA's persistent world model."""
    try:
        from apps.core.world_model.entity_registry import get_entity_registry

        registry = get_entity_registry()
        return registry.summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/temporal")
async def temporal_memory_summary():
    """Recent events from ARIA's temporal memory."""
    try:
        from apps.core.memory.temporal.temporal_memory import get_temporal_memory

        mem = get_temporal_memory()
        recent = await mem.recent(n=20)
        return {
            "summary": mem.summary(),
            "recent_events": [e.to_dict() for e in recent],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/procedural")
async def procedural_memory_summary():
    """ARIA's learned procedures."""
    try:
        from apps.core.memory.procedural.procedural_memory import get_procedural_memory

        mem = get_procedural_memory()
        procs = await mem.list_all()
        return {
            "summary": mem.summary(),
            "procedures": [
                {
                    "id": p.id,
                    "name": p.name,
                    "success_rate": round(p.success_rate, 3),
                    "execution_count": p.execution_count,
                    "trusted": p.is_trusted,
                    "utility_score": round(p.utility_score(), 3),
                }
                for p in procs[:20]
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/orchestrator")
async def memory_orchestrator_summary():
    """Unified memory layer summary from the Memory Orchestrator."""
    try:
        from apps.core.memory.orchestrator import get_memory_orchestrator

        return get_memory_orchestrator().summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/tools/intelligence")
async def tool_intelligence_summary():
    """Tool reliability intelligence summary."""
    try:
        from apps.core.tools.intelligence.tool_registry import get_tool_registry

        registry = get_tool_registry()
        return {
            "summary": registry.summary(),
            "failing_tools": [t.name for t in registry.failing_tools()],
            "best_tools": [
                {"name": t.name, "success_rate": round(t.success_rate, 3)}
                for t in registry.best_tools(top_k=5)
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/agents/hierarchy")
async def agent_hierarchy_summary():
    """ARIA agent organizational hierarchy and delegation stats."""
    try:
        from apps.core.agents.hierarchy.agent_hierarchy import get_agent_hierarchy

        h = get_agent_hierarchy()
        return {
            "summary": h.summary(),
            "reporting_structure": h.reporting_structure(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/business/roi")
async def roi_summary():
    """Economic intelligence and opportunity portfolio."""
    try:
        from apps.core.business.roi_engine import get_roi_engine

        engine = get_roi_engine()
        return {
            "portfolio": await engine.get_portfolio_summary(),
            "recommendation": await engine.recommend_next_action(),
            "top_opportunities": [o.to_dict() for o in await engine.rank_opportunities(top_k=5)],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/quality/health")
async def system_quality_health():
    """Autonomous quality controller health report."""
    try:
        from apps.core.quality.quality_controller import get_quality_controller

        ctrl = get_quality_controller()
        return {
            "health": ctrl.system_health(),
            "open_findings": [f.to_dict() for f in ctrl.open_findings()[:10]],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/quality/audit")
async def run_quality_audit():
    """Trigger an on-demand architecture audit."""
    try:
        from apps.core.quality.quality_controller import get_quality_controller

        report = await get_quality_controller().run_architecture_audit()
        return report.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/cognition/traces")
async def cognition_traces():
    """Recent reasoning traces with hallucination risk scores."""
    try:
        from apps.core.observability.cognition.reasoning_tracer import get_reasoning_tracer

        tracer = get_reasoning_tracer()
        return {
            "summary": tracer.summary(),
            "recent": tracer.recent(n=10),
            "high_risk": [t.to_dict() for t in tracer.high_risk_traces()],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/events/stats")
async def event_bus_stats():
    """Event bus statistics: topics, volume, DLQ depth."""
    try:
        from apps.core.events.bus import get_event_bus

        return get_event_bus().stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/events/dlq")
async def event_dlq():
    """Dead-letter queue — events that failed after all retries."""
    try:
        from apps.core.events.bus import get_event_bus

        bus = get_event_bus()
        items = await bus.consume_dlq(limit=50)
        return {"dead_letter_count": bus.dead_letter_count, "items": items}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/business/intelligence")
async def bi_report():
    """Business intelligence report: workflow profitability and ROI telemetry."""
    try:
        from apps.core.business.intelligence.bi_telemetry import get_bi_telemetry

        bi = get_bi_telemetry()
        return {
            "summary": bi.summary(),
            "report_24h": await bi.report(window_hours=24),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/quality/benchmark")
async def run_benchmark():
    """Run hallucination and rule-engine benchmark suites."""
    try:
        from tests.testing.cognition.benchmark_harness import (
            BenchmarkRunner,
            build_hallucination_suite,
            build_rule_engine_suite,
        )

        runner = BenchmarkRunner()
        hallucination_report = await runner.run(build_hallucination_suite())
        rule_report = await runner.run(build_rule_engine_suite())
        return {
            "hallucination_suite": {
                "pass_rate": hallucination_report.pass_rate,
                "avg_latency_ms": hallucination_report.avg_latency_ms,
                "regression_detected": runner.regression_detected(hallucination_report),
            },
            "rule_engine_suite": {
                "pass_rate": rule_report.pass_rate,
                "avg_latency_ms": rule_report.avg_latency_ms,
                "regression_detected": runner.regression_detected(rule_report),
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/status")
async def status():
    try:
        from apps.core.training.continuous_trainer import get_trainer

        trainer_status = get_trainer().get_status()
    except Exception:
        trainer_status = {}
    return JSONResponse(
        {
            "aria": "running",
            "trainer": trainer_status,
            "ts": datetime.now(UTC).isoformat(),
        }
    )


@app.get("/api/v1/growth/loops")
async def growth_loops():
    """Growth loop orchestrator status and per-loop metrics."""
    try:
        from apps.business.growth.growth_engine import get_growth_engine

        engine = get_growth_engine()
        return {
            "summary": engine.summary(),
            "loops": [
                {
                    "loop_id": l.loop_id,
                    "name": l.name,
                    "channel": l.channel,
                    "enabled": l.enabled,
                    "success_rate": round(l.success_rate, 3),
                    "avg_revenue_per_run": round(l.avg_revenue_per_run, 2),
                    "is_due": l.is_due(),
                }
                for l in engine._loops.values()
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/growth/optimize")
async def optimize_growth():
    """Re-prioritize growth loops based on ROI performance."""
    try:
        from apps.business.growth.growth_engine import get_growth_engine

        engine = get_growth_engine()
        await engine.optimize_allocation()
        return {"status": "optimized", "summary": engine.summary()}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/ecommerce/shopify")
async def shopify_status():
    """Autonomous Shopify operator status and catalog health."""
    try:
        from apps.business.ecommerce.shopify_operator import get_shopify_operator

        op = get_shopify_operator()
        return op.summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/ecommerce/shopify/cycle")
async def shopify_cycle():
    """Run one autonomous Shopify optimization cycle."""
    try:
        from apps.business.ecommerce.shopify_operator import get_shopify_operator

        op = get_shopify_operator()
        return await op.run_autonomous_cycle()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/content")
async def content_pipeline():
    """Content OS performance report and pipeline status."""
    try:
        from apps.content.content_os import get_content_os

        cos = get_content_os()
        return {
            "summary": cos.summary(),
            "report": await cos.performance_report(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/autonomy/schedule")
async def autonomy_schedule():
    """Autonomous scheduler status and strategic objectives."""
    try:
        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler

        sched = get_autonomous_scheduler()
        objs = await sched.get_objectives()
        return {
            "summary": sched.summary(),
            "objectives": [
                {
                    "name": o.name,
                    "priority": o.priority.value,
                    "frequency_hours": o.frequency_hours,
                    "success_rate": round(o.success_rate, 3),
                    "total_value_usd": round(o.total_value_usd, 2),
                    "is_due": o.is_due(),
                }
                for o in objs
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/economics")
async def economics_report():
    """Economic intelligence report with unit economics and forecasting."""
    try:
        from apps.business.economics.economic_engine import get_economic_engine

        engine = get_economic_engine()
        return await engine.economic_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/crm/summary")
async def crm_summary():
    """CRM summary: leads, customers, churn risk, segments."""
    try:
        from apps.business.crm.crm_engine import get_crm_engine

        crm = get_crm_engine()
        return {
            "summary": crm.summary(),
            "high_risk": [
                {"customer_id": c.customer_id, "email": c.email, "churn_risk": c.churn_risk.value}
                for c in await crm.high_risk_customers()
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/growth/learner")
async def growth_learner_report():
    """Growth learning system: strategy knowledge and campaign intelligence."""
    try:
        from apps.learning.growth.growth_learner import get_growth_learner

        learner = get_growth_learner()
        return await learner.learning_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/media/image")
async def image_generator_status():
    """Image generation pipeline status and recent jobs."""
    try:
        from apps.multimodal.images.image_generator import get_image_generator

        gen = get_image_generator()
        return gen.queue_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/media/image/generate")
async def generate_image(request: Request):
    """Generate an image from a prompt."""
    try:
        from apps.multimodal.images.image_generator import get_image_generator

        body = await request.json()
        gen = get_image_generator()
        job = await gen.generate(
            prompt=body.get("prompt", ""),
            negative_prompt=body.get("negative_prompt", ""),
        )
        return job.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/brand")
async def brand_status():
    """Brand engine: list all brand profiles."""
    try:
        from apps.branding.identity.brand_engine import get_brand_engine

        engine = get_brand_engine()
        brands = await engine.list_brands()
        return {
            "brand_count": len(brands),
            "brands": [{"brand_id": b.brand_id, "name": b.name, "niche": b.niche} for b in brands],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/factory/stats")
async def factory_stats():
    """Content and ad factory production statistics."""
    try:
        from apps.factory.ads.ad_factory import get_ad_factory
        from apps.factory.content.content_factory import get_content_factory

        return {
            "content_factory": get_content_factory().summary(),
            "ad_factory": get_ad_factory().summary(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/distribution/stats")
async def distribution_stats():
    """Social distribution pipeline statistics."""
    try:
        from apps.distribution.social.social_publisher import get_social_publisher

        return await get_social_publisher().publishing_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/revenue/attribution")
async def revenue_attribution():
    """Revenue attribution report across all channels."""
    try:
        from apps.revenue.attribution.revenue_tracker import AttributionModel, get_revenue_tracker

        tracker = get_revenue_tracker()
        channels = await tracker.roi_by_channel(AttributionModel.LAST_TOUCH)
        forecast = await tracker.revenue_forecast(months=3)
        return {
            "summary": tracker.summary(),
            "by_channel": [c.to_dict() for c in channels],
            "3_month_forecast": forecast,
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/revenue/optimize")
async def revenue_optimize():
    """Revenue optimization recommendations and growth scenarios."""
    try:
        from apps.revenue.optimization.revenue_optimizer import get_revenue_optimizer

        optimizer = get_revenue_optimizer()
        return await optimizer.autonomous_recommendation()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/infra/gpu")
async def gpu_status():
    """GPU orchestration status and queue depth."""
    try:
        from apps.infra.gpu.gpu_orchestrator import get_gpu_orchestrator

        return await get_gpu_orchestrator().status()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/market/trends")
async def market_trends(niche: str = "general"):
    """Trend analysis for a given niche."""
    try:
        from apps.market.trends.trend_analyzer import get_trend_analyzer

        return (await get_trend_analyzer().analyze_niche(niche)).to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/market/opportunities")
async def market_opportunities(niche: str = "general", budget_usd: float = 1000.0):
    """ROI-ranked business opportunities."""
    try:
        from apps.market.opportunities.opportunity_finder import get_opportunity_finder

        opps = await get_opportunity_finder().find_opportunities(niche, budget_usd)
        return {"opportunities": [o.to_dict() for o in opps]}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/content/quality")
async def content_quality_stats():
    """Content quality engine statistics."""
    try:
        from apps.content.intelligence.content_quality_engine import get_content_quality_engine

        return get_content_quality_engine().quality_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/strategy/priorities")
async def strategy_priorities():
    """Top strategic priorities ranked by effort-impact."""
    try:
        from apps.strategy.prioritization.priority_engine import get_priority_engine

        return {"priorities": [a.to_dict() for a in get_priority_engine().top_priorities()]}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/autonomy/goals")
async def autonomy_goals():
    """Autonomous goal dashboard."""
    try:
        from apps.autonomy.goals.goal_manager import get_goal_manager

        return get_goal_manager().goal_dashboard()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/autonomy/loops")
async def autonomy_loops():
    """Revenue loop analytics."""
    try:
        from apps.autonomy.revenue_loops.revenue_loop_engine import get_revenue_loop_engine

        return get_revenue_loop_engine().loop_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/business/executive")
async def business_executive():
    """Executive dashboard snapshot."""
    try:
        from apps.business.executive.executive_dashboard import get_executive_dashboard

        return await get_executive_dashboard().weekly_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/business/cashflow")
async def business_cashflow():
    """Cashflow status and runway."""
    try:
        from apps.business.finance.cashflow_engine import get_cashflow_engine

        engine = get_cashflow_engine()
        return {
            "current_balance": engine.current_balance(),
            "runway_months": engine.runway_months(),
            "monthly_summary": engine.monthly_summary(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/cognition/agent")
async def cognition_agent_status():
    """LangGraph cognitive agent summary."""
    try:
        from apps.cognition.langgraph.cognitive_agent import get_cognitive_agent

        return get_cognitive_agent().summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/cognition/run")
async def cognition_run(task: str, context: dict = None):
    """Run a task through the LangGraph cognitive workflow."""
    if context is None:
        context = {}
    try:
        from apps.cognition.langgraph.cognitive_agent import get_cognitive_agent

        return await get_cognitive_agent().run(task, context)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/status")
async def memory_status():
    """Vector memory and knowledge graph status."""
    try:
        from apps.memory.graph.knowledge_graph import get_knowledge_graph
        from apps.memory.vector.memory_retriever import get_memory_retriever

        return {
            "vector_memory": get_memory_retriever().status(),
            "knowledge_graph": get_knowledge_graph().summary(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/evaluation/analytics")
async def evaluation_analytics():
    """AI trace analytics and quality metrics."""
    try:
        from apps.evaluation.phoenix.tracer import get_cognition_tracer

        return await get_cognition_tracer().analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/evaluation/evaluate")
async def evaluate_content(content: str, prompt: str = ""):
    """Evaluate AI response quality across 6 dimensions."""
    try:
        from apps.evaluation.phoenix.evaluator import get_ai_evaluator

        result = get_ai_evaluator().evaluate(content, prompt)
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/runtime/tasks")
async def runtime_task_stats():
    """Distributed task runner statistics."""
    try:
        from apps.runtime.celery.task_runner import get_task_runner

        return await get_task_runner().task_stats()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 9 Economic Autonomy Endpoints ──────────────────────────────────────


@app.get("/api/v1/content/seo")
async def seo_stats():
    """SEO engine keyword opportunities and stats."""
    try:
        from apps.content.seo.seo_engine import get_seo_engine

        return get_seo_engine().stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/content/calendar")
async def content_calendar():
    """Upcoming content calendar slots."""
    try:
        from apps.content.blog.content_calendar import get_content_calendar

        cal = get_content_calendar()
        return {"this_week": cal.this_week(), "stats": cal.calendar_stats()}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/flash-sales")
async def flash_sales():
    """Active flash sales and analytics."""
    try:
        from apps.shopify.offers.flash_sale_engine import get_flash_sale_engine

        return get_flash_sale_engine().sales_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/bundles")
async def bundles():
    """Active product bundles."""
    try:
        from apps.shopify.bundles.bundle_generator import get_bundle_generator

        bg = get_bundle_generator()
        return {"bundles": bg._bundles, "total": len(bg._bundles)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/conversion/quiz")
async def quiz_analytics():
    """Quiz engine analytics and active quizzes."""
    try:
        from apps.conversion.quiz.quiz_engine import get_quiz_engine

        qe = get_quiz_engine()
        return {"quizzes": qe.list_quizzes(), "total": len(qe._quizzes)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/conversion/leads")
async def lead_funnel():
    """Lead funnel report from Lead Scorer."""
    try:
        from apps.conversion.quiz.lead_scorer import get_lead_scorer

        return get_lead_scorer().lead_funnel_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/ads/retargeting")
async def retargeting_analytics():
    """Retargeting campaign analytics."""
    try:
        from apps.ads.retargeting.retargeting_engine import get_retargeting_engine

        return get_retargeting_engine().campaign_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/orchestration/growth")
async def growth_analytics():
    """Growth orchestrator analytics."""
    try:
        from apps.orchestration.growth_orchestrator import get_growth_orchestrator

        return get_growth_orchestrator().growth_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/orchestration/cycle")
async def autonomous_growth_cycle(niche: str = "general"):
    """Trigger autonomous growth cycle for a given niche."""
    try:
        from apps.orchestration.growth_orchestrator import get_growth_orchestrator

        return await get_growth_orchestrator().autonomous_growth_cycle(niche)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/orchestration/report")
async def strategic_report():
    """Full strategic growth report."""
    try:
        from apps.orchestration.growth_orchestrator import get_growth_orchestrator

        return await get_growth_orchestrator().strategic_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/learning/reinforcement")
async def reinforcement_report():
    """UCB1 reinforcement optimizer arm rankings and report."""
    try:
        from apps.learning.optimization.reinforcement_optimizer import get_reinforcement_optimizer

        return get_reinforcement_optimizer().optimization_report()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 10 Executive Layer Endpoints ───────────────────────────────────────


@app.get("/api/v1/executive/summary")
async def executive_summary():
    """Strategic summary across all C-suite agents."""
    try:
        from apps.executive.ceo_agent import get_ceo_agent
        from apps.executive.cfo_agent import get_cfo_agent
        from apps.executive.coo_agent import get_coo_agent

        return {
            "ceo": get_ceo_agent().strategic_summary(),
            "coo": get_coo_agent().operations_report(),
            "cfo": get_cfo_agent().profitability_report(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/executive/council")
async def convene_council(niche: str = "general"):
    """Convene the Executive Council for a unified growth report."""
    try:
        from apps.executive.executive_council import get_executive_council

        report = await get_executive_council().convene(niche, {})
        return report.to_dict() if hasattr(report, "to_dict") else report
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/executive/cto/tech-radar")
async def tech_radar():
    """CTO tech radar — adopt/trial/hold/avoid."""
    try:
        from apps.executive.cto_agent import get_cto_agent

        return get_cto_agent().tech_radar()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 10 Workforce Endpoints ─────────────────────────────────────────────


@app.get("/api/v1/workforce/engineering/stats")
async def engineering_stats():
    """Engineering division task stats."""
    try:
        from apps.workforce.engineering.engineering_division import get_engineering_division

        return get_engineering_division().engineering_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/workforce/engineering/task")
async def engineering_task(task_type: str, title: str, spec: str = "{}"):
    """Run an engineering task (frontend/backend/mlops/api/qa/automation)."""
    try:
        import json

        from apps.workforce.engineering.engineering_division import get_engineering_division

        div = get_engineering_division()
        spec_dict = json.loads(spec)
        method = getattr(div, f"{task_type}_task", None)
        if not method:
            return {"error": f"Unknown task_type: {task_type}"}
        task = await method(title, spec_dict)
        return task.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/workforce/design/stats")
async def design_stats():
    """Design division asset stats."""
    try:
        from apps.workforce.design.design_division import get_design_division

        return get_design_division().design_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/workforce/marketing/stats")
async def marketing_stats():
    """Marketing division campaign stats."""
    try:
        from apps.workforce.marketing.marketing_division import get_marketing_division

        return get_marketing_division().marketing_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/workforce/content/stats")
async def content_stats():
    """Content division production stats."""
    try:
        from apps.workforce.content.content_division import get_content_division

        return get_content_division().content_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/workforce/analytics/stats")
async def analytics_division_stats():
    """Analytics division report stats."""
    try:
        from apps.workforce.analytics.analytics_division import get_analytics_division

        return get_analytics_division().analytics_stats()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 10 Economics Endpoints ─────────────────────────────────────────────


@app.get("/api/v1/economics/dashboard")
async def economics_dashboard():
    """Full economic intelligence dashboard."""
    try:
        from apps.economics.economic_intelligence import get_economic_intelligence

        return get_economic_intelligence().economic_dashboard()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/economics/roi")
async def roi_summary_v2():
    """ROI tracker summary across all tracked investments."""
    try:
        from apps.economics.roi_tracker import get_roi_tracker

        return get_roi_tracker().roi_summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/economics/snapshot")
async def economics_snapshot(period: str = "7d"):
    """Generate economic snapshot for a period."""
    try:
        from apps.economics.economic_intelligence import get_economic_intelligence

        snap = await get_economic_intelligence().snapshot(period)
        return snap.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 10 Marketplace Endpoints ───────────────────────────────────────────


@app.get("/api/v1/marketplace/pipeline")
async def pipeline_report():
    """Client acquisition pipeline report."""
    try:
        from apps.marketplace.client_acquisition import get_client_acquisition

        return get_client_acquisition().pipeline_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/marketplace/proposals")
async def proposals():
    """Recent proposals and analytics."""
    try:
        from apps.marketplace.proposal_engine import get_proposal_engine

        pe = get_proposal_engine()
        return {"analytics": pe.proposal_analytics(), "recent": pe.recent_proposals(limit=10)}
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 11 Extended Economic Autonomy Endpoints ────────────────────────────


@app.get("/api/v1/video/youtube/stats")
async def youtube_stats():
    try:
        from apps.video.youtube.youtube_engine import get_youtube_engine

        return get_youtube_engine().channel_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/video/youtube/metadata")
async def youtube_metadata(topic: str, keyword: str = ""):
    try:
        from apps.video.youtube.youtube_engine import get_youtube_engine

        meta = await get_youtube_engine().create_video_metadata(topic, keyword or topic)
        return meta.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/video/shorts/stats")
async def shorts_stats():
    try:
        from apps.video.shorts.shorts_engine import get_shorts_engine

        return get_shorts_engine().shorts_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/video/pipeline/stats")
async def video_pipeline_stats():
    try:
        from apps.video.automation.publishing_pipeline import get_publishing_pipeline

        return get_publishing_pipeline().pipeline_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/acquisition/linkedin/analytics")
async def linkedin_analytics():
    try:
        from apps.acquisition.linkedin.linkedin_outreach import get_linkedin_outreach

        return get_linkedin_outreach().outreach_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/acquisition/upwork/analytics")
async def upwork_analytics():
    try:
        from apps.acquisition.upwork.upwork_bidder import get_upwork_bidder

        return get_upwork_bidder().bidding_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/acquisition/fiverr/analytics")
async def fiverr_analytics():
    try:
        from apps.acquisition.fiverr.fiverr_optimizer import get_fiverr_optimizer

        return get_fiverr_optimizer().gig_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/acquisition/outreach/analytics")
async def outreach_analytics():
    try:
        from apps.acquisition.outreach.outreach_sequencer import get_outreach_sequencer

        return get_outreach_sequencer().sequence_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/learning/roi")
async def roi_learning_report():
    try:
        from apps.learning.roi.roi_learner import get_roi_learner

        return get_roi_learner().learning_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/conversion/sms/stats")
async def sms_stats():
    try:
        from apps.conversion.sms.sms_capture import get_sms_capture_engine

        return get_sms_capture_engine().capture_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/conversion/funnels/analytics")
async def funnels_analytics():
    try:
        from apps.conversion.funnels.funnel_engine import get_funnel_engine

        return get_funnel_engine().funnel_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/market/pricing/dashboard")
async def pricing_dashboard():
    try:
        from apps.market.pricing.pricing_intelligence import get_pricing_intelligence

        return get_pricing_intelligence().pricing_dashboard()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/content/linking/stats")
async def linking_stats():
    try:
        from apps.content.internal_linking.linking_optimizer import get_linking_optimizer

        return get_linking_optimizer().linking_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/content/distribution/stats")
async def content_distribution_stats():
    try:
        from apps.content.distribution.distribution_engine import get_distribution_engine

        return get_distribution_engine().distribution_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/economic/summary")
async def economic_memory_summary():
    try:
        from apps.memory.economic.economic_memory import get_economic_memory

        return get_economic_memory().memory_summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/clients/summary")
async def client_memory_summary():
    try:
        from apps.memory.client.client_memory import get_client_memory

        return get_client_memory().client_memory_summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/workflows/analytics")
async def workflow_memory_analytics():
    try:
        from apps.memory.workflow.workflow_memory import get_workflow_memory

        return get_workflow_memory().workflow_analytics()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 12 Revenue Activation Endpoints ────────────────────────────────────


@app.get("/api/v1/shopify/seo/stats")
async def shopify_seo_stats():
    try:
        from apps.shopify.seo.product_seo import get_product_seo_optimizer

        return get_product_seo_optimizer().seo_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/shopify/seo/optimize")
async def shopify_seo_optimize(
    product_id: str, name: str, title: str = "", description: str = "", category: str = "general"
):
    try:
        from apps.shopify.seo.product_seo import get_product_seo_optimizer

        seo = await get_product_seo_optimizer().optimize_product(
            product_id, name, title, description, category
        )
        return seo.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/seo/keywords")
async def shopify_seo_keywords(niche: str):
    try:
        from apps.shopify.seo.product_seo import get_product_seo_optimizer

        return await get_product_seo_optimizer().audit_keywords(niche)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/funnels/stats")
async def shopify_funnel_stats():
    try:
        from apps.shopify.funnels.shopify_funnels import get_shopify_funnel_engine

        return get_shopify_funnel_engine().funnel_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/shopify/funnels/upsell")
async def shopify_upsell(original: str, original_price: float, upsell: str, upsell_price: float):
    try:
        from apps.shopify.funnels.shopify_funnels import get_shopify_funnel_engine

        offer = await get_shopify_funnel_engine().create_upsell_flow(
            original, original_price, upsell, upsell_price
        )
        return offer.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/shopify/funnels/abandoned-cart")
async def shopify_abandoned_cart(product: str, price: float, discount_pct: float = 10.0):
    try:
        from apps.shopify.funnels.shopify_funnels import get_shopify_funnel_engine

        funnel = await get_shopify_funnel_engine().create_abandoned_cart_sequence(
            product, price, discount_pct
        )
        return funnel.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/shopify/funnels/landing-page")
async def shopify_landing_page(product: str, offer: str, audience: str, price: float = 0.0):
    try:
        from apps.shopify.funnels.shopify_funnels import get_shopify_funnel_engine

        funnel = await get_shopify_funnel_engine().create_landing_page(
            product, offer, audience, price
        )
        return funnel.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/execution/plan")
async def execution_plan():
    try:
        from apps.execution.daily_runtime import get_daily_runtime

        tasks = get_daily_runtime().plan_day()
        return {"tasks": [t.to_dict() for t in tasks], "total": len(tasks)}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/execution/run-daily")
async def run_daily_execution(max_tasks: int = 18):
    try:
        from apps.execution.daily_runtime import get_daily_runtime

        report = await get_daily_runtime().run_daily(max_tasks=max_tasks)
        return report.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/execution/report")
async def execution_report():
    try:
        from apps.execution.daily_runtime import get_daily_runtime

        report = await get_daily_runtime().generate_report()
        return report.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/execution/stats")
async def execution_stats():
    try:
        from apps.execution.daily_runtime import get_daily_runtime

        return get_daily_runtime().runtime_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/execution/recent-reports")
async def execution_recent_reports(limit: int = 7):
    try:
        from apps.execution.daily_runtime import get_daily_runtime

        return get_daily_runtime().recent_reports(limit=limit)
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 13 Distribution + Acquisition Endpoints ────────────────────────────


@app.post("/api/v1/distribution/linkedin/post")
async def linkedin_create_post(topic: str, objective: str = "thought_leadership"):
    try:
        from apps.distribution.linkedin.linkedin_publisher import get_linkedin_publisher

        post = await get_linkedin_publisher().create_post(topic, objective)
        return post.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/distribution/linkedin/analytics")
async def linkedin_publisher_analytics():
    try:
        from apps.distribution.linkedin.linkedin_publisher import get_linkedin_publisher

        return get_linkedin_publisher().post_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/distribution/twitter/thread")
async def twitter_create_thread(topic: str, angle: str = "educational", num_tweets: int = 7):
    try:
        from apps.distribution.twitter.twitter_engine import get_twitter_engine

        thread = await get_twitter_engine().create_thread(topic, angle, num_tweets)
        return thread.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/distribution/twitter/analytics")
async def twitter_analytics():
    try:
        from apps.distribution.twitter.twitter_engine import get_twitter_engine

        return get_twitter_engine().twitter_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/distribution/tiktok/script")
async def tiktok_generate_script(topic: str, niche: str, platform: str = "tiktok"):
    try:
        from apps.distribution.tiktok.tiktok_engine import get_tiktok_engine

        script = await get_tiktok_engine().generate_script(topic, niche, platform)
        return script.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/distribution/tiktok/analytics")
async def tiktok_analytics():
    try:
        from apps.distribution.tiktok.tiktok_engine import get_tiktok_engine

        return get_tiktok_engine().tiktok_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/distribution/blog/write")
async def blog_write_post(
    topic: str, keyword: str, audience: str = "general", word_target: int = 1200
):
    try:
        from apps.distribution.blog.blog_publisher import get_blog_publisher

        post = await get_blog_publisher().write_post(topic, keyword, audience, word_target)
        return post.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/distribution/blog/stats")
async def blog_stats():
    try:
        from apps.distribution.blog.blog_publisher import get_blog_publisher

        return get_blog_publisher().blog_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/acquisition/leads/discover")
async def discover_leads(niche: str, count: int = 10):
    try:
        from apps.acquisition.leads.lead_engine import get_lead_engine

        leads = await get_lead_engine().discover_leads(niche, count)
        return {"leads": [l.to_dict() for l in leads], "total": len(leads)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/acquisition/leads/analytics")
async def lead_analytics():
    try:
        from apps.acquisition.leads.lead_engine import get_lead_engine

        return get_lead_engine().lead_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/acquisition/crm/contact")
async def crm_add_contact(
    name: str, company: str, email: str = "", niche: str = "", deal_value: float = 500.0
):
    try:
        from apps.acquisition.crm.crm_engine import get_crm_engine

        contact = await get_crm_engine().add_contact(
            name, company, email, niche, deal_value_usd=deal_value
        )
        return contact.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/acquisition/crm/dashboard")
async def crm_dashboard():
    try:
        from apps.acquisition.crm.crm_engine import get_crm_engine

        return get_crm_engine().crm_dashboard()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/conversion/landing-page")
async def create_landing_page(product: str, offer: str, audience: str, price: float = 0.0):
    try:
        from apps.conversion.landing_pages.landing_page_engine import get_landing_page_engine

        page = await get_landing_page_engine().create_page(product, offer, audience, price)
        return page.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/conversion/landing-pages/stats")
async def landing_page_stats():
    try:
        from apps.conversion.landing_pages.landing_page_engine import get_landing_page_engine

        return get_landing_page_engine().page_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/conversion/email-sequence")
async def create_email_sequence(niche: str, goal: str, audience: str, num_emails: int = 7):
    try:
        from apps.conversion.email_sequences.email_nurture import get_email_nurture_engine

        seq = await get_email_nurture_engine().create_sequence(niche, goal, audience, num_emails)
        return seq.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/conversion/email-sequences/analytics")
async def email_sequence_analytics():
    try:
        from apps.conversion.email_sequences.email_nurture import get_email_nurture_engine

        return get_email_nurture_engine().sequence_analytics()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/runtime/run-daily")
async def run_daily_business_loop(max_ops: int = 18):
    try:
        from apps.runtime.daily_business_loop import get_daily_business_loop

        report = await get_daily_business_loop().run(max_ops=max_ops)
        return report.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/runtime/morning")
async def run_morning_session():
    try:
        from apps.runtime.daily_business_loop import get_daily_business_loop

        ops = await get_daily_business_loop().run_morning_session()
        return {"ops": [o.to_dict() for o in ops], "total": len(ops)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/runtime/status")
async def runtime_status():
    try:
        from apps.runtime.daily_business_loop import get_daily_business_loop

        return await get_daily_business_loop().generate_status_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/runtime/stats")
async def runtime_loop_stats():
    try:
        from apps.runtime.daily_business_loop import get_daily_business_loop

        return get_daily_business_loop().loop_stats()
    except Exception as exc:
        return {"error": str(exc)}


# ── Phase 14: Real-World Execution API ───────────────────────────────────────


@app.post("/api/v1/publish/twitter")
async def publish_twitter(request: Request):
    try:
        body = await request.json()
        from apps.distribution.publishers.api_publisher import get_api_publisher

        pub = get_api_publisher()
        result = await pub.publish_to_twitter(body.get("content", ""), body.get("reply_to_id", ""))
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/publish/linkedin")
async def publish_linkedin(request: Request):
    try:
        body = await request.json()
        from apps.distribution.publishers.api_publisher import get_api_publisher

        pub = get_api_publisher()
        result = await pub.publish_to_linkedin(
            body.get("content", ""), body.get("visibility", "PUBLIC")
        )
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/publish/tiktok")
async def publish_tiktok(request: Request):
    try:
        body = await request.json()
        from apps.distribution.publishers.api_publisher import get_api_publisher

        pub = get_api_publisher()
        result = await pub.publish_to_tiktok(body.get("video_url", ""), body.get("caption", ""))
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/publish/thread")
async def publish_thread(request: Request):
    try:
        body = await request.json()
        from apps.distribution.publishers.api_publisher import get_api_publisher

        pub = get_api_publisher()
        results = await pub.publish_thread_to_twitter(body.get("tweets", []))
        return {"results": [r.to_dict() for r in results], "total": len(results)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/publish/stats")
async def publish_stats():
    try:
        from apps.distribution.publishers.api_publisher import get_api_publisher

        return get_api_publisher().publishing_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/products")
async def shopify_products():
    try:
        from apps.shopify.api_client import get_shopify_api_client

        products = await get_shopify_api_client().get_products()
        return {"products": [p.to_dict() for p in products], "total": len(products)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/orders")
async def shopify_orders():
    try:
        from apps.shopify.api_client import get_shopify_api_client

        orders = await get_shopify_api_client().get_orders()
        return {"orders": [o.to_dict() for o in orders], "total": len(orders)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/analytics")
async def shopify_analytics():
    try:
        from apps.shopify.api_client import get_shopify_api_client

        analytics = await get_shopify_api_client().get_revenue_analytics()
        return analytics.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/shopify/status")
async def shopify_status_v2():
    try:
        from apps.shopify.api_client import get_shopify_api_client

        return get_shopify_api_client().client_status()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/economics/track")
async def economics_track(request: Request):
    try:
        body = await request.json()
        from apps.economics.dashboard import get_economic_dashboard

        event = await get_economic_dashboard().track_event(
            body.get("event_type", "impression"),
            body.get("channel", "unknown"),
            float(body.get("amount", 0.0)),
            body.get("metadata", {}),
        )
        return event.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/economics/snapshot")
async def economics_snapshot_v2():
    try:
        from apps.economics.dashboard import get_economic_dashboard

        snap = await get_economic_dashboard().snapshot_today()
        return snap.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/economics/summary")
async def economics_summary():
    try:
        from apps.economics.dashboard import get_economic_dashboard

        return get_economic_dashboard().dashboard_summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/economics/weekly-report")
async def economics_weekly_report():
    try:
        from apps.economics.dashboard import get_economic_dashboard

        return await get_economic_dashboard().weekly_report()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/leads/scrape")
async def leads_scrape(request: Request):
    try:
        body = await request.json()
        from apps.acquisition.scraper.lead_scraper import get_lead_scraper

        batch = await get_lead_scraper().scrape_leads(
            body.get("niche", "ecommerce"),
            int(body.get("count", 10)),
            body.get("location", "US"),
        )
        return batch.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/leads/scraper-stats")
async def leads_scraper_stats():
    try:
        from apps.acquisition.scraper.lead_scraper import get_lead_scraper

        return get_lead_scraper().scraper_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/media/generate-script")
async def media_generate_script(request: Request):
    try:
        body = await request.json()
        from apps.video.media.media_pipeline import get_media_pipeline

        script = await get_media_pipeline().generate_script(
            body.get("topic", "AI for business"),
            body.get("platform", "tiktok"),
            int(body.get("duration_s", 60)),
        )
        return script.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/v1/media/run-pipeline")
async def media_run_pipeline(request: Request):
    try:
        body = await request.json()
        from apps.video.media.media_pipeline import get_media_pipeline

        result = await get_media_pipeline().run_pipeline(
            body.get("topic", "AI business tips"),
            body.get("platform", "tiktok"),
        )
        return result.to_dict()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/media/pipeline-stats")
async def media_pipeline_stats():
    try:
        from apps.video.media.media_pipeline import get_media_pipeline

        return get_media_pipeline().pipeline_stats()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/scheduler/status")
async def scheduler_status_endpoint():
    try:
        from apps.runtime.scheduler import get_aria_scheduler

        return get_aria_scheduler().scheduler_status()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/scheduler/executions")
async def scheduler_executions():
    try:
        from apps.runtime.scheduler import get_aria_scheduler

        return {"executions": get_aria_scheduler().recent_executions(limit=20)}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/income/status")
async def income_status():
    """Real-time income loop status: cycles, strategies, revenue, recent URLs."""
    import json as _json

    try:
        from apps.core.memory.redis_client import get_cache
        from apps.core.tools.income_loop import INTERVAL_SECONDS, STRATEGIES, get_income_loop

        cache = get_cache()
        loop = get_income_loop()

        total_cycles = 0
        success_cycles = 0
        total_urls = 0
        strategy_stats: list[dict] = []
        recent_urls: list[str] = []
        total_revenue = 0.0
        last_run_ts = None

        if cache:
            total_cycles = int(await cache.get("aria:income:total_cycles") or 0)
            success_cycles = int(await cache.get("aria:income:successful_cycles") or 0)
            total_urls = int(await cache.get("aria:income:total_urls_published") or 0)
            last_run_raw = await cache.get("aria:income:last_run_ts")
            if last_run_raw:
                last_run_ts = last_run_raw

            for name, _weight in STRATEGIES:
                runs = int(await cache.get(f"aria:income:strategy:{name}:runs") or 0)
                wins = int(await cache.get(f"aria:income:strategy:{name}:successes") or 0)
                rev_raw = await cache.get(f"aria:income:strategy:{name}:revenue")
                rev = float(rev_raw) if rev_raw else 0.0
                total_revenue += rev
                if runs > 0:
                    strategy_stats.append(
                        {
                            "name": name,
                            "runs": runs,
                            "wins": wins,
                            "success_rate": round(wins / runs, 2),
                            "revenue_usd": round(rev, 2),
                        }
                    )

            history_raw = await cache.lrange("aria:income:loop_history", -20, -1)
            for raw in history_raw or []:
                try:
                    c = _json.loads(raw) if isinstance(raw, str) else raw
                    recent_urls.extend(c.get("urls_created", []))
                except Exception:
                    pass
            recent_urls = [u for u in dict.fromkeys(recent_urls) if u][:10]

        strategy_stats.sort(key=lambda s: -s["revenue_usd"])
        creds = loop.check_credentials()

        return {
            "status": "running",
            "cycle_interval_seconds": INTERVAL_SECONDS,
            "total_cycles": total_cycles,
            "successful_cycles": success_cycles,
            "success_rate": round(success_cycles / max(total_cycles, 1), 2),
            "total_urls_published": total_urls,
            "total_revenue_potential_usd": round(total_revenue, 2),
            "last_run_ts": last_run_ts,
            "top_strategies": strategy_stats[:10],
            "recent_urls": recent_urls,
            "active_channels": list(creds.get("active", {}).keys()),
            "inactive_channels": list(creds.get("inactive", {}).keys()),
        }
    except Exception as exc:
        return {"error": str(exc), "status": "error"}


@app.post("/api/v1/income/run-now")
async def income_run_now(strategy: str | None = None):
    """Trigger one income cycle immediately. Pass ?strategy=name to force a specific strategy."""
    try:
        from apps.core.tools.income_loop import get_income_loop

        loop = get_income_loop()
        result = await loop._run_one_cycle(force_strategy=strategy)
        return {
            "success": result.success,
            "strategy": result.strategy,
            "summary": result.summary,
            "revenue_potential": result.revenue_potential,
            "urls": getattr(result, "urls_created", []),
        }
    except Exception as exc:
        return {"error": str(exc), "success": False}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """ARIA AI Control Center — Professional web interface."""
    import os

    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(template_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "<h1>Dashboard</h1><p>Template not found. Check apps/core/templates/dashboard.html</p>"
        )


@app.get("/oauth/callback/{service}")
async def oauth_callback(service: str, request: Request):
    """
    OAuth callback endpoint — recibe el code de Google/Slack/etc.
    State = chat_id del usuario de Telegram que inició la conexión.
    """
    params = dict(request.query_params)
    code = params.get("code", "")
    state = params.get("state", "")  # chat_id
    error = params.get("error", "")

    if error:
        logger.warning("[OAuth] Error en callback %s: %s", service, error)
        return HTMLResponse(
            f"<h2>Error conectando {service}</h2><p>{error}</p>"
            "<p>Puedes cerrar esta ventana y reintentar desde Telegram.</p>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse("<h2>Parámetros inválidos</h2>", status_code=400)

    try:
        from apps.core.connections.manager import get_connection_manager

        mgr = get_connection_manager()
        success = await mgr.handle_callback(service, code, state)
        if success:
            # Notify user via Telegram
            msg = f"✅ <b>{service.capitalize()} conectado</b> — ARIA ya puede acceder a tu cuenta."
            await send_telegram(msg)
            return HTMLResponse(
                f"<h2>✅ {service.capitalize()} conectado exitosamente</h2>"
                "<p>Puedes cerrar esta ventana. ARIA confirmará en Telegram.</p>"
                "<style>body{{font-family:sans-serif;text-align:center;padding:50px;background:#0f172a;color:#e2e8f0}}</style>",
            )
        return HTMLResponse(
            f"<h2>Error procesando {service}</h2><p>Revisa los logs de ARIA.</p>",
            status_code=500,
        )
    except Exception as exc:
        logger.error("[OAuth] Callback error %s: %s", service, exc)
        return HTMLResponse(f"<h2>Error interno: {exc}</h2>", status_code=500)


def _serve_doc(filename: str, fallback: str = "") -> HTMLResponse:
    """Serve a static HTML page from docs/ (works in the container and locally)."""
    import pathlib

    for base in (
        pathlib.Path("/app/docs"),
        pathlib.Path(__file__).resolve().parents[2] / "docs",
    ):
        try:
            f = base / filename
            if f.is_file():
                return HTMLResponse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return HTMLResponse(fallback or f"<h2>{filename} not found</h2>", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the public ARIA landing page (lead-capture funnel front door)."""
    return _serve_doc(
        "index.html",
        fallback='<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=/dashboard">'
        "<title>ARIA AI</title></head><body><p>Redirecting to the "
        '<a href="/dashboard">ARIA dashboard</a>…</p></body></html>',
    )


@app.get("/saraph", response_class=HTMLResponse)
async def saraph_page():
    """Serve the Saraph company page (products, approach, launches)."""
    return _serve_doc("saraph.html")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    """Serve the privacy policy."""
    return _serve_doc("privacy.html")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    """Serve the terms of service."""
    return _serve_doc("terms.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)
