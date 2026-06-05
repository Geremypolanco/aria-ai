"""
Aria AI — Sistema Operativo Núcleo
FastAPI + APScheduler + 4 jobs autónomos
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.core.config import settings
from apps.core.memory.redis_client import get_cache
from apps.core.memory.supabase_client import get_db
from apps.core.tools.ai_client import AIModel, get_ai_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("aria.core")

TELEGRAM_API = "https://api.telegram.org/bot"
scheduler = AsyncIOScheduler(timezone="UTC")

# Orchestrator instancia global (lazy)
_orchestrator: Optional[Any] = None


async def get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is None:
        from apps.core.agents.orchestrator import Orchestrator
        _orchestrator = Orchestrator()
        await _orchestrator.start()
    return _orchestrator


# ── TELEGRAM ──────────────────────────────────────────────

async def send_telegram(message: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
            return res.status_code == 200
    except Exception as exc:
        logger.error("Telegram error: %s", exc)
        return False


# ── SCHEDULER JOBS ────────────────────────────────────────

async def autonomous_cycle_job() -> None:
    logger.info("Scheduler: iniciando ciclo autónomo...")
    cache = get_cache()
    locked = await cache.acquire_lock("autonomous_cycle", ttl_seconds=300)
    if not locked:
        logger.info("Scheduler: ciclo ya en ejecución — skip")
        return
    try:
        await cache.set_agent_heartbeat("orchestrator")
        orch = await get_orchestrator()
        await orch.run_cycle()
    except Exception as exc:
        logger.error("Error en ciclo autónomo: %s", exc)
    finally:
        await cache.release_lock("autonomous_cycle")


async def agent_heartbeat_job() -> None:
    try:
        cache = get_cache()
        await cache.set_agent_heartbeat("system")
    except Exception:
        pass


async def daily_report_job() -> None:
    try:
        orch = await get_orchestrator()
        await orch.send_daily_report()
    except Exception as exc:
        logger.error("Error en reporte diario: %s", exc)


async def auto_evolve_job() -> None:
    try:
        orch = await get_orchestrator()
        await orch.auto_evolve()
    except Exception as exc:
        logger.error("Error en auto-evolución: %s", exc)


# ── LIFESPAN ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Aria OS iniciando...")

    interval = int(os.getenv("CYCLE_INTERVAL_MINUTES", "60"))
    scheduler.add_job(autonomous_cycle_job, IntervalTrigger(minutes=interval), id="autonomous_cycle", replace_existing=True)
    scheduler.add_job(agent_heartbeat_job, IntervalTrigger(seconds=30), id="heartbeat", replace_existing=True)
    scheduler.add_job(daily_report_job, CronTrigger(hour=9, minute=0), id="daily_report", replace_existing=True)
    scheduler.add_job(auto_evolve_job, IntervalTrigger(hours=6), id="auto_evolve", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler: 4 jobs activos (ciclo=%dmin, heartbeat=30s, reporte=9am, evolución=6h)", interval)

    await send_telegram(
        "⚡ <b>SISTEMA OPERATIVO ARIA ONLINE</b>\n"
        "Bienvenido, Señor Polanco. Lista para iniciar la Fase 1.\n\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    yield

    scheduler.shutdown()
    logger.info("Aria OS detenido")


app = FastAPI(title="Aria AI Core", version="1.0.0", lifespan=lifespan)


# ── MODELOS DE REQUEST ────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str = "strategy"


class ApprovalDecision(BaseModel):
    approval_id: str
    decision: str  # "approved" | "rejected"


# ── ENDPOINTS ─────────────────────────────────────────────

@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({"status": "online", "system": "Aria OS", "version": "1.0.0"})


@app.get("/health")
async def health() -> JSONResponse:
    """Estado completo del sistema."""
    try:
        cache = get_cache()
        redis_ok = await cache.exists("__health_check__") or True

        ai = await get_ai_client()
        ai_health = ai.get_health_report()

        jobs = [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in scheduler.get_jobs()
        ]

        return JSONResponse({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scheduler": {"running": scheduler.running, "jobs": jobs},
            "ai_providers": ai_health,
            "redis": "connected" if redis_ok else "error",
        })
    except Exception as exc:
        return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=503)


@app.post("/chat")
async def chat(request: ChatRequest) -> JSONResponse:
    """Conversación directa con Aria."""
    try:
        model_map = {
            "strategy": AIModel.STRATEGY,
            "code": AIModel.CODE,
            "fast": AIModel.FAST,
            "creative": AIModel.CREATIVE,
        }
        ai_model = model_map.get(request.model, AIModel.STRATEGY)
        ai = await get_ai_client()
        response = await ai.complete(
            system=(
                "Eres Aria, la IA de negocios digitales del Señor Geremy Polanco. "
                "Eres directa, inteligente y orientada a resultados reales. "
                "Nunca dices que no puedes hacer algo — propones alternativas."
            ),
            user=request.message,
            model=ai_model,
            agent_name="aria_chat",
        )
        return JSONResponse({
            "response": response.content,
            "provider": response.provider,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "success": response.success,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/status")
async def status() -> JSONResponse:
    """Dashboard completo del sistema."""
    try:
        db = get_db()
        total_revenue = await db.get_total_revenue()
        revenue_by_platform = await db.get_revenue_by_platform()
        opportunities = await db.get_best_opportunities(limit=3)

        orch = await get_orchestrator()
        agent_statuses = orch.get_all_agent_statuses()

        jobs = [
            {
                "id": job.id,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in scheduler.get_jobs()
        ]

        return JSONResponse({
            "system": "Aria OS v1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "revenue": {
                "total_usd": total_revenue,
                "by_platform": revenue_by_platform,
            },
            "agents": agent_statuses,
            "scheduler": {"running": scheduler.running, "jobs": jobs},
            "top_opportunities": opportunities,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/approvals")
async def get_approvals() -> JSONResponse:
    """Lista de aprobaciones pendientes."""
    try:
        db = get_db()
        result = db._client.table("approvals").select("*").eq("status", "pending").order("created_at", desc=True).limit(20).execute()
        return JSONResponse({"approvals": result.data or []})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/approvals/decide")
async def decide_approval(decision: ApprovalDecision) -> JSONResponse:
    """Aprobar o rechazar una acción pendiente."""
    if decision.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision debe ser 'approved' o 'rejected'")
    try:
        db = get_db()
        db._client.table("approvals").update({
            "status": decision.decision,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", decision.approval_id).execute()
        emoji = "✅" if decision.decision == "approved" else "❌"
        await send_telegram(
            f"{emoji} <b>Aprobación {decision.decision.upper()}</b>\n"
            f"ID: <code>{decision.approval_id}</code>"
        )
        return JSONResponse({"success": True, "decision": decision.decision})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cycle/trigger")
async def trigger_cycle() -> JSONResponse:
    """Dispara un ciclo autónomo manualmente."""
    try:
        scheduler.add_job(autonomous_cycle_job, id="manual_cycle", replace_existing=True)
        await send_telegram("🚀 <b>Ciclo manual disparado</b> por el supervisor.")
        return JSONResponse({"success": True, "message": "Ciclo en ejecución"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cycle/pause")
async def pause_cycle() -> JSONResponse:
    """Pausa el scheduler."""
    try:
        scheduler.pause()
        await send_telegram("⏸ <b>Scheduler PAUSADO</b> por el supervisor.")
        return JSONResponse({"success": True, "status": "paused"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/cycle/resume")
async def resume_cycle() -> JSONResponse:
    """Reanuda el scheduler."""
    try:
        scheduler.resume()
        await send_telegram("▶️ <b>Scheduler REANUDADO</b> por el supervisor.")
        return JSONResponse({"success": True, "status": "running"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/logs")
async def get_logs(limit: int = 50) -> JSONResponse:
    """Últimos logs del sistema."""
    try:
        db = get_db()
        result = db._client.table("system_logs").select("*").order("created_at", desc=True).limit(limit).execute()
        return JSONResponse({"logs": result.data or []})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/revenue")
async def get_revenue() -> JSONResponse:
    """Dashboard de ingresos."""
    try:
        db = get_db()
        total = await db.get_total_revenue()
        by_platform = await db.get_revenue_by_platform()
        recent = db._client.table("revenue").select("*").order("created_at", desc=True).limit(20).execute()
        return JSONResponse({
            "total_usd": total,
            "by_platform": by_platform,
            "recent_transactions": recent.data or [],
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/ai/metrics")
async def get_ai_metrics() -> JSONResponse:
    """Métricas del cliente de IA."""
    try:
        ai = await get_ai_client()
        return JSONResponse(ai.get_health_report())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── ENTRY POINT ───────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "apps.core.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
