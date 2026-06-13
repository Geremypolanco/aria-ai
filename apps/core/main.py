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
