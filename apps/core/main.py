"""
Aria AI — Entry Point Principal
FastAPI + APScheduler + Telegram Bootstrap
Versión: 1.0.0 — Fase 1
"""
import os
import sys
import logging
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import httpx
import uvicorn
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

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
TELEGRAM_API = "https://telegram.org"
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
        await db.log_info("Reporte diario enviado al Señor Polanco", "orchestrator")
        logger.info("Reporte diario enviado exitosamente.")
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
    
    connections = await verify_connections()
    
    startup_details = (
        f"{STARTUP_MESSAGE}\n\n"
        f"🔍 Estado de Conexiones:\n"
        f"• Supabase: {connections.get('supabase')}\n"
        f"• Redis: {connections.get('redis')}\n"
        f"• AI Client: {connections.get('ai')}"
    )
    await send_telegram(startup_details)
    
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
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        workers=1
    )
