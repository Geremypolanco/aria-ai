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

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from apps.core.config_pkg import settings

# ── Observability bootstrap (FIRST — before any other imports) ────────────
from apps.core.observability.logging import configure_logging, get_logger
from apps.core.observability.tracing import setup_tracing
from apps.core.observability.sentry import setup_sentry
from apps.core.observability.metrics import get_metrics

configure_logging(level="INFO")
setup_tracing(service_name="aria-ai", service_version="2.0.0")
setup_sentry()

logger = get_logger("aria.core")

from apps.core.memory.redis_client import get_cache
from apps.core.memory.supabase_client import get_db
from apps.core.tools.ai_client import AIModel, get_ai_client

TELEGRAM_API = "https://api.telegram.org/bot"
scheduler    = AsyncIOScheduler(timezone="UTC")

_orchestrator: Optional[Any] = None


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
                json={"chat_id": settings.TELEGRAM_CHAT_ID,
                      "text": message, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
            return r.status_code == 200
    except Exception as exc:
        logger.error("Telegram error: %s", exc)
        return False


# ── LIFESPAN ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    # 1. Registrar webhook de Telegram
    try:
        from apps.core.tools.telegram_bot import get_bot
        bot = get_bot()
        webhook_url = f"https://aria-ai.fly.dev/telegram/webhook"
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

    # 2b. IncomeLoop 24/7 — autonomous income generation every 30 min
    try:
        from apps.core.tools.income_loop import get_income_loop
        await get_income_loop().start()
        logger.info("IncomeLoop 24/7 activo (cada 30 min)")
    except Exception as exc:
        logger.error("Error iniciando IncomeLoop: %s", exc)

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
        scheduler.add_job(autonomous_cycle_job, IntervalTrigger(minutes=settings.CYCLE_INTERVAL_MINUTES),
                          id="autonomous_cycle", replace_existing=True)
        scheduler.add_job(heartbeat_job, IntervalTrigger(minutes=5),
                          id="heartbeat", replace_existing=True)
        scheduler.start()
        logger.info("Scheduler iniciado (ciclo cada %d min)", settings.CYCLE_INTERVAL_MINUTES)
    except Exception as exc:
        logger.error("Error scheduler: %s", exc)

    # 5. Phase 5 autonomous business systems
    try:
        from apps.business.growth.growth_engine import get_growth_engine
        get_growth_engine()
        logger.info("Growth Engine initialized (8 loops: shopify_seo, content, social, email, affiliate, youtube, linkedin, paid)")
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
        get_autonomous_scheduler()
        logger.info("Autonomous Scheduler initialized (6 strategic objectives, 24/7 execution)")
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
        from apps.learning.prioritization.priority_engine import get_priority_engine as get_p11_priority_engine
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
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


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
                    "id": p.id, "name": p.name,
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
            "best_tools": [{"name": t.name, "success_rate": round(t.success_rate, 3)} for t in registry.best_tools(top_k=5)],
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
    return JSONResponse({
        "aria": "running",
        "trainer": trainer_status,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


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
                    "loop_id": l.loop_id, "name": l.name, "channel": l.channel,
                    "enabled": l.enabled, "success_rate": round(l.success_rate, 3),
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
                    "name": o.name, "priority": o.priority.value,
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
            "brands": [
                {"brand_id": b.brand_id, "name": b.name, "niche": b.niche}
                for b in brands
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/factory/stats")
async def factory_stats():
    """Content and ad factory production statistics."""
    try:
        from apps.factory.content.content_factory import get_content_factory
        from apps.factory.ads.ad_factory import get_ad_factory
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
        from apps.revenue.attribution.revenue_tracker import get_revenue_tracker, AttributionModel
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
async def cognition_run(task: str, context: dict = {}):
    """Run a task through the LangGraph cognitive workflow."""
    try:
        from apps.cognition.langgraph.cognitive_agent import get_cognitive_agent
        return await get_cognitive_agent().run(task, context)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/v1/memory/status")
async def memory_status():
    """Vector memory and knowledge graph status."""
    try:
        from apps.memory.vector.memory_retriever import get_memory_retriever
        from apps.memory.graph.knowledge_graph import get_knowledge_graph
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
        from apps.executive.coo_agent import get_coo_agent
        from apps.executive.cfo_agent import get_cfo_agent
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
async def roi_summary():
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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """ARIA AI Control Center — Professional web interface."""
    import os
    template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard</h1><p>Template not found. Check apps/core/templates/dashboard.html</p>"


@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirects to the dashboard."""
    return """<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=/dashboard">
    <title>ARIA AI</title></head><body>
    <p>Redirigiendo al <a href="/dashboard">Dashboard de ARIA</a>...</p>
    </body></html>"""


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)
