"""
ARIA AI — Public REST + WebSocket API  (v1)

Mount this router in main.py:
    from apps.core.routes.api import router as api_router
    app.include_router(api_router)
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from apps.core.config_pkg import settings

logger = logging.getLogger("aria.api")

# ── ACTIVITY LOG (in-memory ring buffer) ─────────────────────────────────────

_activity_log: deque = deque(maxlen=200)


def _log_activity(level: str, message: str, category: str = "info") -> None:
    _activity_log.append({
        "ts": datetime.utcnow().isoformat(),
        "level": level,
        "category": category,
        "message": message,
    })


# ── API KEY AUTH ──────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-ARIA-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(_api_key_header)) -> None:
    """
    If ARIA_API_KEY is configured, requests must supply it via X-ARIA-Key header.
    If ARIA_API_KEY is not set, all requests are allowed (open mode).
    """
    required = settings.ARIA_API_KEY
    if not required:
        return  # open mode — no key configured
    if api_key != required:
        raise HTTPException(status_code=401, detail="Invalid or missing X-ARIA-Key")


# ── ROUTER ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1", tags=["ARIA API"])

# ── REQUEST / RESPONSE MODELS ─────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class RunRequest(BaseModel):
    mission: str
    agent: str = "auto"
    use_pipeline: bool = True


class ScheduleRequest(BaseModel):
    task: str
    interval_minutes: int


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def api_status() -> dict:
    """Full system status: trainer, agents, scheduler."""
    try:
        from apps.core.training.continuous_trainer import get_trainer
        trainer_status = get_trainer().get_status()
    except Exception as exc:
        trainer_status = {"error": str(exc)}

    try:
        from apps.core.agents.business_hub import _AGENT_REGISTRY
        agent_count = len(set(_AGENT_REGISTRY.values()))  # unique classes
    except Exception:
        agent_count = 0

    try:
        from apps.core.main import scheduler
        scheduler_running = scheduler.running
        jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
    except Exception:
        scheduler_running = False
        jobs = []

    return {
        "aria": "running",
        "trainer": trainer_status,
        "agents": {"registered": agent_count},
        "scheduler": {"running": scheduler_running, "jobs": jobs},
        "ts": datetime.utcnow().isoformat(),
    }


@router.post("/chat", dependencies=[Depends(verify_api_key)])
async def api_chat(req: ChatRequest) -> dict:
    """Chat with ARIA mind. Returns a text reply."""
    try:
        from apps.core.cognition.aria_mind import get_aria_mind
        mind = get_aria_mind()
        session_id = req.session_id or "api_default"
        response = await mind.handle(req.message, session_id)
        _log_activity("info", f"Chat [{session_id}]: {req.message[:60]}", "chat")
        return {
            "reply": response.text or "",
            "tool_used": response.tool_used,
            "media_type": (
                "image" if response.image_bytes else
                "video" if response.video_bytes else
                "audio" if response.audio_bytes else
                "document" if response.document_bytes else
                None
            ),
        }
    except Exception as exc:
        logger.error("[API /chat] %s", exc, exc_info=True)
        _log_activity("error", f"Chat error: {exc}", "chat")
        return {"error": str(exc)}


@router.post("/run", dependencies=[Depends(verify_api_key)])
async def api_run(req: RunRequest) -> dict:
    """Execute a mission via pipeline or direct dispatch."""
    _log_activity("info", f"Run: agent={req.agent} mission={req.mission[:60]}", "run")
    try:
        if req.use_pipeline:
            from apps.core.agents.execution_pipeline import get_pipeline
            pipeline = get_pipeline()
            run = await pipeline.run(req.mission, req.agent)
            return {
                "run_id": run.id,
                "result": run.summary(),
            }
        else:
            from apps.core.agents.business_hub import get_business_hub
            hub = get_business_hub()
            result = await hub.dispatch(req.agent, req.mission)
            return {
                "run_id": None,
                "result": result,
            }
    except Exception as exc:
        logger.error("[API /run] %s", exc, exc_info=True)
        _log_activity("error", f"Run error: {exc}", "run")
        return {"error": str(exc)}


@router.get("/agents", dependencies=[Depends(verify_api_key)])
async def api_agents() -> list:
    """List all registered agents with metadata."""
    try:
        from apps.core.agents.business_hub import _AGENT_REGISTRY
        business_agents = list(_AGENT_REGISTRY.keys())
    except Exception:
        business_agents = []

    descriptions: dict[str, str] = {
        "ceo":        "Estrategia ejecutiva, decisiones y delegación",
        "marketing":  "SEO, redes sociales, campañas y crecimiento",
        "sales":      "Revenue: productos, pagos, conversión",
        "developer":  "Código, deploy, debugging autónomo",
        "dev":        "Código, deploy, debugging autónomo (alias)",
        "research":   "Investigación profunda de mercado e internet",
        "content":    "Artículos, newsletters, publicación multi-plataforma",
        "finance":    "Revenue tracking, P&L y forecasting",
        "cfo":        "Chief Financial Officer — finanzas y reporting",
        "cmo":        "Chief Marketing Officer — marketing estratégico",
        "cto":        "Chief Technology Officer — arquitectura y desarrollo",
        # system agents
        "orchestrator":        "Coordina ciclos autónomos y agentes especializados",
        "aria_mind":           "Motor cognitivo central de ARIA",
        "continuous_trainer":  "Loop de auto-mejora y evaluación 24/7",
    }

    seen: set[str] = set()
    agents_list: list[dict] = []

    for name in business_agents:
        if name in seen:
            continue
        seen.add(name)
        agents_list.append({
            "name": name,
            "description": descriptions.get(name, "Agente de negocio especializado"),
            "type": "business",
            "available": True,
        })

    for name in ("orchestrator", "aria_mind", "continuous_trainer"):
        if name in seen:
            continue
        seen.add(name)
        agents_list.append({
            "name": name,
            "description": descriptions.get(name, "Agente del sistema"),
            "type": "system",
            "available": True,
        })

    return agents_list


@router.get("/goals", dependencies=[Depends(verify_api_key)])
async def api_goals() -> dict:
    """Return ARIA's active goals."""
    try:
        from apps.core.cognition.aria_mind import get_aria_mind
        mind = get_aria_mind()
        goals = await mind._load_goals()
        return {"goals": goals, "count": len(goals)}
    except Exception as exc:
        logger.error("[API /goals] %s", exc)
        return {"error": str(exc), "goals": []}


@router.get("/activity", dependencies=[Depends(verify_api_key)])
async def api_activity() -> dict:
    """Return last 50 activity log entries."""
    entries = list(_activity_log)[-50:]
    return {"entries": list(reversed(entries)), "total": len(_activity_log)}


@router.get("/pipeline/{run_id}", dependencies=[Depends(verify_api_key)])
async def api_pipeline_get(run_id: str) -> dict:
    """Get a pipeline run by ID."""
    try:
        from apps.core.agents.execution_pipeline import get_pipeline
        pipeline = get_pipeline()
        run = pipeline.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        return run.summary()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API /pipeline/%s] %s", run_id, exc)
        return {"error": str(exc)}


@router.get("/pipeline", dependencies=[Depends(verify_api_key)])
async def api_pipeline_list() -> dict:
    """List recent pipeline runs."""
    try:
        from apps.core.agents.execution_pipeline import get_pipeline
        pipeline = get_pipeline()
        runs = pipeline.list_runs(limit=20)
        return {"runs": runs, "count": len(runs)}
    except Exception as exc:
        logger.error("[API /pipeline] %s", exc)
        return {"error": str(exc), "runs": []}


@router.post("/schedule", dependencies=[Depends(verify_api_key)])
async def api_schedule(req: ScheduleRequest) -> dict:
    """Schedule a recurring task."""
    try:
        from apps.core.main import scheduler
        from apps.core.agents.business_hub import get_business_hub
        from apscheduler.triggers.interval import IntervalTrigger

        job_id = f"user_task_{hash(req.task) & 0xFFFFFF}"

        async def _run_task() -> None:
            _log_activity("info", f"Scheduled task running: {req.task[:60]}", "schedule")
            hub = get_business_hub()
            result = await hub.dispatch("auto", req.task)
            _log_activity(
                "info" if result.get("success") else "error",
                f"Task done: {req.task[:40]} — {str(result)[:80]}",
                "schedule",
            )

        scheduler.add_job(
            _run_task,
            IntervalTrigger(minutes=req.interval_minutes),
            id=job_id,
            replace_existing=True,
        )
        _log_activity("info", f"Scheduled '{req.task[:60]}' every {req.interval_minutes}m", "schedule")
        return {
            "job_id": job_id,
            "task": req.task,
            "interval_minutes": req.interval_minutes,
            "status": "scheduled",
        }
    except Exception as exc:
        logger.error("[API /schedule] %s", exc)
        return {"error": str(exc)}


# ── WEBSOCKET ─────────────────────────────────────────────────────────────────


@router.websocket("/ws")
async def websocket_aria(websocket: WebSocket) -> None:
    """Real-time bidirectional chat with ARIA via WebSocket."""
    await websocket.accept()
    session_id = f"ws_{id(websocket)}"
    _log_activity("info", f"WebSocket connected: {session_id}", "ws")

    try:
        from apps.core.cognition.aria_mind import get_aria_mind
        mind = get_aria_mind()

        while True:
            data = await websocket.receive_text()

            # Parse as JSON {type: "chat", message: "..."} or plain text
            try:
                payload = json.loads(data)
                message = payload.get("message", data)
            except Exception:
                message = data

            if not message or not message.strip():
                continue

            try:
                response = await mind.handle(message, session_id)
                await websocket.send_json({
                    "type": "reply",
                    "text": response.text or "",
                    "tool_used": response.tool_used,
                    "ts": datetime.utcnow().isoformat(),
                })
                _log_activity("info", f"WS [{session_id}]: {message[:60]}", "ws")
            except Exception as exc:
                logger.error("[WS] handle error: %s", exc)
                await websocket.send_json({
                    "type": "error",
                    "text": f"Error: {exc}",
                    "ts": datetime.utcnow().isoformat(),
                })

    except WebSocketDisconnect:
        _log_activity("info", f"WebSocket disconnected: {session_id}", "ws")
    except Exception as exc:
        logger.error("[WS] unexpected: %s", exc)
        _log_activity("error", f"WS error: {exc}", "ws")
