"""
Aria AI — Entry Point Principal
FastAPI + ARQ Workers + Scheduler
"""
import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from apps.core.config import settings
from apps.core.tools.ai_client import get_ai_client, AIModel
from apps.core.memory.supabase_client import get_db
from apps.core.memory.redis_client import get_cache


# ── SCHEDULER GLOBAL ──────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="UTC")


# ── STARTUP Y SHUTDOWN ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Maneja el ciclo de vida completo de la aplicación."""
    db = get_db()
    cache = get_cache()
    ai = get_ai_client()

    await db.log_info("Aria AI iniciando...", "system")
    print(f"[ARIA] 🚀 {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"[ARIA] 🌍 Ambiente: {settings.ENVIRONMENT}")

    # Verificar conexiones críticas
    await _verify_connections(db, cache)

    # Registrar agentes en Redis
    for agent_name in [
        "orchestrator", "pm_agent", "dev_agent",
        "marketing_agent", "cfo_agent", "support_agent"
    ]:
        await cache.set_agent_status(agent_name, {
            "status": "idle",
            "started_at": datetime.now(timezone.utc).isoformat()
        })

    # Iniciar scheduler
    _setup_scheduler()
    scheduler.start()
    print(f"[ARIA] ⏰ Scheduler iniciado — ciclo cada {settings.CYCLE_INTERVAL_MINUTES} minutos")

    await db.log_success("Aria AI lista para operar", "system")

    # Notificar por Telegram
    await _notify_startup()

    yield

    # Shutdown limpio
    scheduler.shutdown(wait=False)
    await ai.close()
    await cache.close()
    await db.log_info("Aria AI detenida limpiamente", "system")
    print("[ARIA] ⛔ Aria AI detenida")


async def _verify_connections(db, cache):
    """Verifica que las conexiones críticas estén activas."""
    print("[ARIA] 🔍 Verificando conexiones...")

    # Supabase
    try:
        agent = await db.get_agent_by_name("orchestrator")
        if agent:
            print("[ARIA] ✅ Supabase conectado")
        else:
            print("[ARIA] ⚠️  Supabase: agentes no encontrados — ejecuta las migrations")
    except Exception as e:
        print(f"[ARIA] ❌ Supabase error: {e}")

    # Redis
    try:
        await cache.set("aria:health_check", "ok", ttl_seconds=60)
        result = await cache.get("aria:health_check")
        if result == "ok":
            print("[ARIA] ✅ Redis/Upstash conectado")
        else:
            print("[ARIA] ⚠️  Redis: respuesta inesperada")
    except Exception as e:
        print(f"[ARIA] ❌ Redis error: {e}")

    # AI Client
    try:
        ai = get_ai_client()
        print(f"[ARIA] ✅ AI Client listo — Primario: HuggingFace, Secundario: Groq")
    except Exception as e:
        print(f"[ARIA] ❌ AI Client error: {e}")


def _setup_scheduler():
    """Configura todos los trabajos programados."""
    # Ciclo autónomo principal
    scheduler.add_job(
        _autonomous_cycle_job,
        trigger=IntervalTrigger(minutes=settings.CYCLE_INTERVAL_MINUTES),
        id="autonomous_cycle",
        name="Ciclo Autónomo Principal",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Heartbeat de agentes cada 30 segundos
    scheduler.add_job(
        _heartbeat_job,
        trigger=IntervalTrigger(seconds=30),
        id="heartbeat",
        name="Heartbeat de Agentes",
        replace_existing=True,
    )

    # Reporte diario a las 9am UTC
    scheduler.add_job(
        _daily_report_job,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_report",
        name="Reporte Diario",
        replace_existing=True,
    )

    # Evolución del sistema cada 6 horas
    scheduler.add_job(
        _evolution_job,
        trigger=IntervalTrigger(hours=6),
        id="evolution",
        name="Auto-Evolución del Sistema",
        replace_existing=True,
    )


async def _autonomous_cycle_job():
    """Trabajo principal del ciclo autónomo."""
    try:
        from apps.core.agents.orchestrator import AriaOrchestrator
        orchestrator = AriaOrchestrator()
        await orchestrator.run_cycle()
    except ImportError:
        db = get_db()
        ai = get_ai_client()
        await db.log_info("Ejecutando ciclo básico (orchestrator en construcción)", "system")
        response = await ai.complete(
            system="""Eres Aria, IA autónoma de negocios.
Analiza el mercado actual e identifica la mejor oportunidad de ingresos disponible ahora mismo.""",
            user="¿Cuál es la mejor acción para generar ingresos en este momento?",
            model=AIModel.STRATEGY,
            agent_name="orchestrator"
        )
        if response.success:
            await db.log_info(f"Ciclo básico completado: {response.content[:200]}", "orchestrator")


async def _heartbeat_job():
    """Registra heartbeat de todos los agentes."""
    cache = get_cache()
    agents = [
        "orchestrator", "pm_agent", "dev_agent",
        "marketing_agent", "cfo_agent", "support_agent"
    ]
    for agent in agents:
        await cache.set_agent_heartbeat(agent)


async def _daily_report_job():
    """Genera y envía reporte diario al señor Polanco."""
    db = get_db()
    total_revenue = await db.get_total_revenue()
    revenue_by_platform = await db.get_revenue_by_platform()
    pending_approvals = await db.get_pending_approvals()

    report = (
        f"📊 REPORTE DIARIO — ARIA AI\n\n"
        f"💰 Ingresos totales: ${total_revenue:.2f}\n"
        f"📋 Aprobaciones pendientes: {len(pending_approvals)}\n"
        f"🏪 Por plataforma: {revenue_by_platform}\n\n"
        f"Sistema operando correctamente."
    )

    await _send_telegram(report)
    await db.log_info("Reporte diario enviado", "system")


async def _evolution_job():
    """Ciclo de auto-evolución del sistema."""
    db = get_db()
    await db.log_info("Iniciando ciclo de evolución", "system")
    try:
        from apps.core.agents.evolution_agent import EvolutionAgent
        agent = EvolutionAgent()
        await agent.evolve()
    except ImportError:
        await db.log_info("Evolution agent pendiente de implementación", "system")


async def _send_telegram(message: str):
    """Envía mensaje por Telegram."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML"
                }
            )
    except Exception:
        pass


async def _notify_startup():
    """Notifica el inicio del sistema."""
    await _send_telegram(
        f"⚡ <b>ARIA AI INICIADA</b>\n\n"
        f"✅ Sistema operativo\n"
        f"🔄 Ciclo cada {settings.CYCLE_INTERVAL_MINUTES} minutos\n"
        f"🌍 Ambiente: {settings.ENVIRONMENT}\n\n"
        f"Buenos días, {settings.OWNER_NAME}. Lista para operar."
    )


# ── APLICACIÓN FASTAPI ────────────────────────────────────
app = FastAPI(
    title="Aria AI — Core API",
    description="Sistema autónomo de negocios digitales",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
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


class TaskRequest(BaseModel):
    task_type: str
    input_data: dict
    priority: int = 5
    requires_approval: bool = False


# ── MIDDLEWARE DE AUTENTICACIÓN ───────────────────────────
async def verify_internal_token(
    x_internal_token: Optional[str] = Header(None)
):
    """Verifica el token interno para endpoints sensibles."""
    if settings.ENVIRONMENT == "production":
        expected = settings.HF_TOKEN[-16:]
        if x_internal_token != expected:
            raise HTTPException(status_code=401, detail="Token inválido")


# ── ENDPOINTS ─────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health", tags=["Health"])
async def health_check():
    db = get_db()
    cache = get_cache()
    ai = get_ai_client()

    cache_ok = await cache.exists("aria:health_check")
    ai_metrics = ai.get_metrics_summary()

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": "connected",
            "cache": "connected" if cache_ok else "degraded",
            "ai": ai_metrics,
            "scheduler": "running" if scheduler.running else "stopped",
        },
        "scheduler_jobs": len(scheduler.get_jobs()),
    }


@app.post("/chat", tags=["Chat"])
async def chat(request: ChatRequest):
    """Endpoint de conversación con Aria."""
    ai = get_ai_client()
    db = get_db()

    response = await ai.complete(
        system=f"""Eres Aria, IA autónoma de negocios del {settings.OWNER_NAME}.
Directa, cercana, como un socio por WhatsApp.
Reportas datos reales: ingresos, tareas completadas, decisiones tomadas.
Operas en todos los idiomas y mercados del planeta.""",
        user=request.message,
        model=AIModel.STRATEGY,
        agent_name=request.agent,
    )

    await db.log_info(
        f"Chat: {request.message[:100]}",
        agent=request.agent,
        metadata={"provider": response.provider, "latency_ms": response.latency_ms}
    )

    return {
        "reply": response.content if response.success else "Error temporal. Reintentando.",
        "provider": response.provider,
        "latency_ms": response.latency_ms,
        "success": response.success,
    }


@app.get("/status", tags=["Dashboard"])
async def get_status():
    """Estado completo del sistema para el dashboard."""
    db = get_db()
    cache = get_cache()
    ai = get_ai_client()

    total_revenue = await db.get_total_revenue()
    revenue_by_platform = await db.get_revenue_by_platform()
    pending_approvals = await db.get_pending_approvals()
    pending_tasks = await db.get_pending_tasks(limit=5)
    opportunities = await db.get_best_opportunities(limit=3)
    ai_metrics = ai.get_metrics_summary()

    agents_status = {}
    for agent_name in [
        "orchestrator", "pm_agent", "dev_agent",
        "marketing_agent", "cfo_agent", "support_agent"
    ]:
        is_alive = await cache.is_agent_alive(agent_name)
        status = await cache.get_agent_status(agent_name)
        agents_status[agent_name] = {
            "alive": is_alive,
            "status": status.get("status", "unknown") if status else "unknown"
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "revenue": {
            "total_usd": total_revenue,
            "by_platform": revenue_by_platform,
        },
        "agents": agents_status,
        "queue": {
            "pending_approvals": len(pending_approvals),
            "pending_tasks": len(pending_tasks),
        },
        "ai": ai_metrics,
        "opportunities": opportunities,
        "scheduler_running": scheduler.running,
    }


@app.get("/approvals", tags=["Approvals"])
async def get_approvals():
    """Lista las aprobaciones pendientes."""
    db = get_db()
    approvals = await db.get_pending_approvals()
    return {"approvals": approvals, "count": len(approvals)}


@app.post("/approvals/decide", tags=["Approvals"])
async def decide_approval(request: ApprovalRequest):
    """Aprueba o rechaza una tarea pendiente."""
    db = get_db()

    if request.decision not in ["approved", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="decision debe ser 'approved' o 'rejected'"
        )

    success = await db.resolve_approval(
        approval_id=request.approval_id,
        decision=request.decision,
        reason=request.reason
    )

    if not success:
        raise HTTPException(status_code=404, detail="Aprobación no encontrada")

    await db.log_info(
        f"Aprobación {request.approval_id}: {request.decision}",
        agent="supervisor",
        metadata={"reason": request.reason}
    )

    return {
        "success": True,
        "approval_id": request.approval_id,
        "decision": request.decision
    }


@app.post("/cycle/trigger", tags=["Control"])
async def trigger_cycle():
    """Dispara un ciclo autónomo manualmente."""
    db = get_db()
    cache = get_cache()

    locked = await cache.acquire_lock("cycle_trigger", ttl_seconds=300)
    if not locked:
        return JSONResponse(
            status_code=409,
            content={"error": "Ya hay un ciclo en ejecución"}
        )

    asyncio.create_task(_autonomous_cycle_job())
    await db.log_info("Ciclo disparado manualmente", "supervisor")

    return {
        "success": True,
        "message": "Ciclo autónomo iniciado",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.post("/cycle/stop", tags=["Control"])
async def stop_cycle():
    """Detiene el scheduler."""
    if scheduler.running:
        scheduler.pause()
        db = get_db()
        await db.log_info("Scheduler pausado por el supervisor", "supervisor")
        await _send_telegram("⛔ Aria pausada por el señor Polanco.")
    return {"success": True, "message": "Scheduler pausado"}


@app.post("/cycle/resume", tags=["Control"])
async def resume_cycle():
    """Reanuda el scheduler."""
    if scheduler.running:
        scheduler.resume()
        db = get_db()
        await db.log_info("Scheduler reanudado", "supervisor")
        await _send_telegram("▶️ Aria reanudada. Operando normalmente.")
    return {"success": True, "message": "Scheduler reanudado"}


@app.get("/logs", tags=["Monitoring"])
async def get_logs(limit: int = 50, level: Optional[str] = None):
    """Obtiene los logs más recientes."""
    db = get_db()
    try:
        query = db._client.table("system_logs")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(limit)
        if level:
            query = query.eq("level", level.upper())
        result = query.execute()
        return {"logs": result.data or [], "count": len(result.data or [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/revenue", tags=["Revenue"])
async def get_revenue():
    """Obtiene el resumen completo de ingresos."""
    db = get_db()
    total = await db.get_total_revenue()
    by_platform = await db.get_revenue_by_platform()

    try:
        result = db._client.table("revenue")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(20)\
            .execute()
        recent = result.data or []
    except Exception:
        recent = []

    try:
        products_result = db._client.table("products")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()
        products = products_result.data or []
    except Exception:
        products = []

    try:
        websites_result = db._client.table("websites")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()
        websites = websites_result.data or []
    except Exception:
        websites = []

    return {
        "total_usd": total,
        "by_platform": by_platform,
        "recent_transactions": recent,
        "products": products,
        "websites": websites,
    }


@app.get("/ai/metrics", tags=["Monitoring"])
async def get_ai_metrics():
    """Métricas del cliente de IA."""
    ai = get_ai_client()
    return ai.get_metrics_summary()


# ── MANEJADOR DE SEÑALES ──────────────────────────────────
def handle_shutdown(signum, frame):
    print(f"\n[ARIA] Señal {signum} recibida. Cerrando limpiamente...")
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)


# ── PUNTO DE ENTRADA ──────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
        access_log=settings.DEBUG,
    )

