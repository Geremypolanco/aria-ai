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
