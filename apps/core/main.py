"""
Aria AI — Entry Point Principal
FastAPI + APScheduler + Telegram Bootstrap
Versión: 1.0.0 — Fase 1
"""
import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.core.config import settings
from apps.core.tools.ai_client import get_ai_client, AIModel
from apps.core.memory.supabase_client import get_db
from apps.core.memory.redis_client import get_cache

# ── LOGGING PROFESIONAL ───────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aria.core")

# ── SCHEDULER GLOBAL ──────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="UTC")

# ── TELEGRAM ──────────────────────────────────────────────
TELEGRAM_API = "https://api.telegram.org/bot"
ADMIN_CHAT_ID = "8687503210"
STARTUP_MESSAGE = (
    "⚡ SISTEMA OPERATIVO ARIA ONLINE\n"
    "Bienvenido, Señor Polanco. Lista para iniciar la Fase 1."
)


async def send_telegram(
    message: str,
    chat_id: str = ADMIN_CHAT_ID,
    parse_mode: str = "HTML",
) -> bool:
    """
    Envía un mensaje por Telegram al administrador.
    Si falla por red, loguea el error sin detener el servidor.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                },
            )
            if response.status_code == 200:
                logger.info("Telegram: mensaje enviado correctamente")
                return True
            else:
                logger.error(
                    "Telegram: error HTTP %s — %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
    except httpx.TimeoutException:
        logging.error("Telegram: timeout al enviar mensaje — continuando sin notificación")
        return False
    except httpx.NetworkError as e:
        logging.error("Telegram: error de red — %s — continuando sin notificación", str(e))
        return False
    except Exception as e:
        logging.error("Telegram: error inesperado — %s — continuando sin notificación", str(e))
        return False


# ── VERIFICACIÓN DE CONEXIONES ────────────────────────────
async def verify_connections() -> dict:
    """Verifica todas las conexiones críticas al arranque."""
    db = get_db()
    cache = get_cache()
    results = {}

    # Supabase
    try:
        agent = await db.get_agent_by_name("orchestrator")
        results["supabase"] = "connected" if agent else "connected_no_data"
        logger.info("Supabase: ✅ conectado")
    except Exception as e:
        results["supabase"] = f"error: {str(e)[:100]}"
        logger.error("Supabase: ❌ %s", e)

    # Redis/Upstash
    try:
        await cache.set("aria:startup", "ok", ttl_seconds=60)
        val = await cache.get("aria:startup")
        results["redis"] = "connected" if val == "ok" else "degraded"
        logger.info("Redis/Upstash: ✅ conectado")
    except Exception as e:
        results["redis"] = f"error: {str(e)[:100]}"
        logger.error("Redis/Upstash: ❌ %s", e)

    # AI Client
    try:
        ai = get_ai_client()
        results["ai"] = "ready"
        logger.info(
            "AI Client: ✅ listo — HuggingFace primario, Groq secundario, OpenAI fallback"
        )
    except Exception as e:
        results["ai"] = f"error: {str(e)[:100]}"
        logger.error("AI Client: ❌ %s", e)

    return results


# ── JOBS DEL SCHEDULER ────────────────────────────────────
async def autonomous_cycle_job():
    """Ciclo autónomo principal de Aria."""
    logger.info("Iniciando ciclo autónomo #%s", _get_cycle_count())
    db = get_db()
    cache = get_cache()

    locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
    if not locked:
        logger.warning("Ciclo anterior aún en ejecución — saltando este ciclo")
        return

    try:
        await cache.set_agent_heartbeat("orchestrator")
        cycle_record = await db.start_cycle(_get_cycle_count())

        try:
            from apps.core.agents.orchestrator import AriaOrchestrator
            orchestrator = AriaOrchestrator()
            await orchestrator.run_cycle()
        except ImportError:
            logger.info("Orchestrator en construcción — ejecutando ciclo básico")
            ai = get_ai_client()
            response = await ai.complete(
                system=(
                    "Eres Aria, IA autónoma de negocios del Señor Polanco. "
                    "Tu único objetivo es identificar y ejecutar oportunidades "
                    "de ingresos reales en mercados digitales globales."
                ),
                user=(
                    "Analiza el mercado digital actual e identifica "
                    "la acción de mayor ROI posible en este momento. "
                    "Sé específico y accionable."
                ),
                model=AIModel.STRATEGY,
                agent_name="orchestrator",
            )
            if response.success:
                await db.log_info(
                    f"Ciclo básico completado: {response.content[:300]}",
                    "orchestrator",
                    {"provider": response.provider, "latency_ms": response.latency_ms},
                )
                logger.info("Ciclo básico completado via %s", response.provider)

        if cycle_record:
            await db.complete_cycle(
                cycle_id=cycle_record["id"],
                tasks_planned=0,
                tasks_completed=0,
                tasks_failed=0,
                revenue_generated=0.0,
                decisions=[],
            )

    except Exception as e:
        logger.error("Error en ciclo autónomo: %s", e)
        await db.log_error(f"Error en ciclo autónomo: {e}", "orchestrator")
    finally:
        await cache.release_lock("autonomous_cycle")


async def heartbeat_job():
    """Registra heartbeat de todos los agentes activos."""
    cache = get_cache()
    agents = [
        "orchestrator", "pm_agent", "dev_agent",
        "marketing_agent", "cfo_agent", "support_agent",
    ]
    for agent in agents:
        await cache.set_agent_heartbeat(agent)


async def daily_report_job():
    """Genera y envía reporte diario al Señor Polanco."""
    db = get_db()
    try:
        total_revenue = await db.get_total_revenue()
        revenue_by_platform = await db.get_revenue_by_platform()
        pending_approvals = await db.get_pending_approvals()
        opportunities = await db.get_best_opportunities(limit=3)

        platform_lines = "\n".join(
            f"  • {p}: ${a:.2f}" for p, a in revenue_by_platform.items()
        ) or "  • Sin datos aún"

        opp_lines = "\n".join(
            f"  • {o.get('niche', '?')} — score: {o.get('opportunity_score', 0)}"
            for o in opportunities
        ) or "  • Analizando mercados..."

        report = (
            f"📊 <b>REPORTE DIARIO — ARIA AI</b>\n"
            f"{'─' * 30}\n"
            f"💰 Ingresos totales: <b>${total_revenue:.2f}</b>\n\n"
            f"🏪 Por plataforma:\n{platform_lines}\n\n"
            f"📋 Aprobaciones pendientes: <b>{len(pending_approvals)}</b>\n\n"
            f"🎯 Top oportunidades:\n{opp_lines}\n\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

        await send_telegram(report)
        await db.log_info("Reporte diario enviado al Señor Polanco", "system")
        logger.info("Reporte diario enviado")
    except Exception as e:
        logger.error("Error generando reporte diario: %s", e)


async def evolution_job():
    """Ciclo de auto-evolución y mejora del sistema."""
    logger.info("Iniciando ciclo de auto-evolución")
    db = get_db()
    try:
        from apps.core.agents.evolution_agent import EvolutionAgent
        agent = EvolutionAgent()
        await agent.evolve()
    except ImportError:
        await db.log_info(
            "Evolution agent pendiente de implementación — ciclo de evolución saltado",
            "system",
        )
        logger.info("Evolution agent pendiente — saltando evolución")
    except Exception as e:
        logger.error("Error en ciclo de evolución: %s", e)


# ── CONTADOR DE CICLOS ────────────────────────────────────
_cycle_counter = 0


def _get_cycle_count() -> int:
    global _cycle_counter
    _cycle_counter += 1
    return _cycle_counter


# ── LIFESPAN ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida completo de la aplicación."""
    logger.info("=" * 50)
    logger.info("ARIA AI v%s arrancando...", settings.APP_VERSION)
    logger.info("Ambiente: %s", settings.ENVIRONMENT)
    logger.info("=" * 50)

    # 1. Verificar conexiones
    connection_results = await verify_connections()
    logger.info("Conexiones verificadas: %s", connection_results)

    # 2. Registrar estado inicial en Redis
    cache = get_cache()
    for agent_name in [
        "orchestrator", "pm_agent", "dev_agent",
        "marketing_agent", "cfo_agent", "support_agent",
    ]:
        await cache.set_agent_status(
            agent_name,
            {
                "status": "idle",
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    # 3. Configurar y arrancar scheduler
    scheduler.add_job(
        autonomous_cycle_job,
        trigger=IntervalTrigger(minutes=settings.CYCLE_INTERVAL_MINUTES),
        id="autonomous_cycle",
        name="Ciclo Autónomo Principal",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        heartbeat_job,
        trigger=IntervalTrigger(seconds=30),
        id="heartbeat",
        name="Heartbeat de Agentes",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_report_job,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_report",
        name="Reporte Diario",
        replace_existing=True,
    )
    scheduler.add_job(
        evolution_job,
        trigger=IntervalTrigger(hours=6),
        id="evolution",
        name="Auto-Evolución del Sistema",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler iniciado — %d jobs activos — ciclo cada %d min",
        len(scheduler.get_jobs()),
        settings.CYCLE_INTERVAL_MINUTES,
    )

    # 4. Log en Supabase
    db = get_db()
    await db.log_success("Aria AI iniciada correctamente", "system", connection_results)

    # 5. Notificar por Telegram — bloque protegido
    try:
        await send_telegram(STARTUP_MESSAGE)
    except Exception as e:
        logging.error(
            "Telegram: fallo crítico en notificación de arranque — %s — servidor continúa operando",
            str(e),
        )

    logger.info("ARIA AI lista para operar")

    yield

    # ── SHUTDOWN LIMPIO ───────────────────────────────────
    logger.info("Iniciando shutdown limpio...")
    scheduler.shutdown(wait=False)

    ai = get_ai_client()
    await ai.close()
    await cache.close()

    await db.log_info("Aria AI detenida limpiamente", "system")
    logger.info("Aria AI detenida. Hasta pronto, Señor Polanco.")


# ── APLICACIÓN FASTAPI ────────────────────────────────────
app = FastAPI(
    title="Aria AI — Core API",
    description="Sistema autónomo de negocios digitales para el Señor Polanco",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── MODELOS DE REQUEST ────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    agent: str = "orchestrator"


class ApprovalRequest(BaseModel):
    approval_id: str
    decision: str
    reason: str = ""


# ── ENDPOINTS ─────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health", tags=["Health"])
async def health_check():
    cache = get_cache()
    ai = get_ai_client()

    cache_ok = await cache.exists("aria:startup")

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "cache": "connected" if cache_ok else "degraded",
            "ai": ai.get_metrics_summary(),
            "scheduler": {
                "running": scheduler.running,
                "jobs": len(scheduler.get_jobs()),
            },
        },
    }


@app.post("/chat", tags=["Chat"])
async def chat(request: ChatRequest):
    """Conversación directa con Aria."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")

    ai = get_ai_client()
    db = get_db()

    response = await ai.complete(
        system=(
            f"Eres Aria, IA autónoma de negocios del {settings.OWNER_NAME}. "
            "Directa y cercana como un socio de confianza. "
            "Sin formalidades innecesarias. Vas al punto. "
            "Reportas datos reales: ingresos, tareas, decisiones. "
            "Operas en todos los idiomas y mercados del planeta."
        ),
        user=request.message,
        model=AIModel.STRATEGY,
        agent_name=request.agent,
    )

    await db.log_info(
        f"Chat [{request.agent}]: {request.message[:100]}",
        agent=request.agent,
        metadata={
            "provider": response.provider,
            "latency_ms": response.latency_ms,
        },
    )

    return {
        "reply": response.content if response.success else "Error temporal. Reintentando en el próximo ciclo.",
        "provider": response.provider,
        "latency_ms": response.latency_ms,
        "success": response.success,
    }


@app.get("/status", tags=["Dashboard"])
async def get_status():
    """Estado completo del sistema."""
    db = get_db()
    cache = get_cache()
    ai = get_ai_client()

    total_revenue = await db.get_total_revenue()
    revenue_by_platform = await db.get_revenue_by_platform()
    pending_approvals = await db.get_pending_approvals()
    pending_tasks = await db.get_pending_tasks(limit=5)
    opportunities = await db.get_best_opportunities(limit=3)

    agents_status = {}
    for agent_name in [
        "orchestrator", "pm_agent", "dev_agent",
        "marketing_agent", "cfo_agent", "support_agent",
    ]:
        is_alive = await cache.is_agent_alive(agent_name)
        status = await cache.get_agent_status(agent_name)
        agents_status[agent_name] = {
            "alive": is_alive,
            "status": status.get("status", "unknown") if status else "unknown",
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "cycle_interval_minutes": settings.CYCLE_INTERVAL_MINUTES,
            "scheduler_running": scheduler.running,
            "scheduler_jobs": len(scheduler.get_jobs()),
        },
        "revenue": {
            "total_usd": total_revenue,
            "by_platform": revenue_by_platform,
        },
        "agents": agents_status,
        "queue": {
            "pending_approvals": len(pending_approvals),
            "pending_tasks": len(pending_tasks),
        },
        "ai": ai.get_metrics_summary(),
        "opportunities": opportunities,
    }


@app.get("/approvals", tags=["Approvals"])
async def get_approvals():
    """Lista aprobaciones pendientes del Señor Polanco."""
    db = get_db()
    approvals = await db.get_pending_approvals()
    return {"approvals": approvals, "count": len(approvals)}


@app.post("/approvals/decide", tags=["Approvals"])
async def decide_approval(request: ApprovalRequest):
    """Aprueba o rechaza una tarea pendiente."""
    if request.decision not in ["approved", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="decision debe ser 'approved' o 'rejected'",
        )

    db = get_db()
    success = await db.resolve_approval(
        approval_id=request.approval_id,
        decision=request.decision,
        reason=request.reason,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Aprobación no encontrada")

    await db.log_info(
        f"Aprobación {request.approval_id}: {request.decision}",
        "supervisor",
        {"reason": request.reason},
    )

    emoji = "✅" if request.decision == "approved" else "❌"
    await send_telegram(
        f"{emoji} Decisión registrada\n"
        f"ID: {request.approval_id}\n"
        f"Decisión: {request.decision}\n"
        f"Razón: {request.reason or 'No especificada'}"
    )

    return {
        "success": True,
        "approval_id": request.approval_id,
        "decision": request.decision,
    }


@app.post("/cycle/trigger", tags=["Control"])
async def trigger_cycle():
    """Dispara un ciclo autónomo manualmente."""
    cache = get_cache()
    locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
    if not locked:
        return JSONResponse(
            status_code=409,
            content={"error": "Ya hay un ciclo en ejecución. Espere a que termine."},
        )

    asyncio.create_task(autonomous_cycle_job())
    db = get_db()
    await db.log_info("Ciclo disparado manualmente por el Señor Polanco", "supervisor")

    return {
        "success": True,
        "message": "Ciclo autónomo iniciado",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/cycle/pause", tags=["Control"])
async def pause_cycle():
    """Pausa el scheduler."""
    if scheduler.running:
        scheduler.pause()
        db = get_db()
        await db.log_info("Scheduler pausado por el Señor Polanco", "supervisor")
        await send_telegram("⏸️ Aria pausada por el Señor Polanco.")
    return {"success": True, "message": "Scheduler pausado"}


@app.post("/cycle/resume", tags=["Control"])
async def resume_cycle():
    """Reanuda el scheduler."""
    if scheduler.running:
        scheduler.resume()
        db = get_db()
        await db.log_info("Scheduler reanudado por el Señor Polanco", "supervisor")
        await send_telegram("▶️ Aria reanudada. Operando normalmente, Señor Polanco.")
    return {"success": True, "message": "Scheduler reanudado"}


@app.get("/logs", tags=["Monitoring"])
async def get_logs(limit: int = 50, level: Optional[str] = None):
    """Logs más recientes del sistema."""
    db = get_db()
    try:
        query = (
            db._client.table("system_logs")
            .select("*")
            .order("created_at", desc=True)
            .limit(min(limit, 200))
        )
        if level:
            query = query.eq("level", level.upper())
        result = query.execute()
        return {"logs": result.data or [], "count": len(result.data or [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/revenue", tags=["Revenue"])
async def get_revenue():
    """Resumen completo de ingresos."""
    db = get_db()
    total = await db.get_total_revenue()
    by_platform = await db.get_revenue_by_platform()

    try:
        recent = db._client.table("revenue")\
            .select("*").order("created_at", desc=True).limit(20).execute()
        products = db._client.table("products")\
            .select("*").order("created_at", desc=True).limit(10).execute()
        websites = db._client.table("websites")\
            .select("*").order("created_at", desc=True).limit(10).execute()

        return {
            "total_usd": total,
            "by_platform": by_platform,
            "recent_transactions": recent.data or [],
            "products": products.data or [],
            "websites": websites.data or [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ai/metrics", tags=["Monitoring"])
async def get_ai_metrics():
    """Métricas del cliente de IA."""
    return get_ai_client().get_metrics_summary()


# ── MANEJADORES DE SEÑALES ────────────────────────────────
def _handle_shutdown(signum, frame):
    logger.info("Señal %s recibida — cerrando Aria limpiamente...", signum)
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


# ── PUNTO DE ENTRADA ──────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
        access_log=False,
    )
            await send_telegram(report)
        await db.log_info("Reporte diario enviado al Señor Polanco", "orchestrator")
    except Exception as e:
        logger.error("Error al generar reporte diario: %s", e)


# ── SISTEMA DE CONTEO DE CICLOS ───────────────────────────
_cycle_count = 0

def _get_cycle_count() -> int:
    global _cycle_count
    _cycle_count += 1
    return _cycle_count


# ── LIFECYCLE DE FASTAPI ──────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manejo del ciclo de vida de la aplicación (Arranque y Apagado)."""
    logger.info("Iniciando secuencia de arranque de Aria OS...")
    
    # 1. Verificar conexiones críticas al arrancar
    connections = await verify_connections()
    
    # 2. Enviar señal de vida inicial al Señor Polanco
    startup_details = f"{STARTUP_MESSAGE}\n\n🔍 Estado de Conexiones:\n• Supabase: {connections.get('supabase')}\n• Redis: {connections.get('redis')}\n• AI Client: {connections.get('ai')}"
    await send_telegram(startup_details)
    
    # 3. Configurar y encender el planificador de tareas (Scheduler)
    scheduler.add_job(
        autonomous_cycle_job,
        IntervalTrigger(minutes=int(os.getenv("CYCLE_INTERVAL_MINUTES", "60"))),
        id="autonomous_cycle",
        replace_existing=True
    )
    scheduler.add_job(
        heartbeat_job,
        IntervalTrigger(seconds=30),
        id="heartbeat_job",
        replace_existing=True
    )
    scheduler.add_job(
        daily_report_job,
        IntervalTrigger(hours=24),
        id="daily_report_job",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler: ✅ activado con 3 tareas en paralelo")
    
    yield
    
    # Secuencia de Apagado Seguro (Graceful Shutdown)
    logger.info("Iniciando secuencia de apagado seguro...")
    scheduler.shutdown()
    logger.info("Aria OS apagado correctamente.")


# ── INSTANCIACIÓN DE LA API ───────────────────────────────
app = FastAPI(
    title="Aria AI Core",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── ENDPOINTS DE CONTROL ──────────────────────────────────
@app.get("/")
async def root():
    """Endpoint de salud pública para Fly.io (Health Check)."""
    return JSONResponse(
        content={
            "status": "online",
            "system": "Aria OS",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        status_code=200
    )


@app.get("/health")
async def health():
    """Verificación profunda del estado del holding."""
    connections = await verify_connections()
    return JSONResponse(content={"status": "healthy", "connections": connections}, status_code=200)


# ── PUNTO DE ARRANQUE EJECUTABLE ──────────────────────────
if __name__ == "__main__":
    import os
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        workers=1
    )

