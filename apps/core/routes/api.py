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
    image_base64: Optional[str] = None  # base64 image for vision analysis


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

    try:
        from apps.core.tools.task_manager import get_task_manager
        task_stats = get_task_manager().stats()
    except Exception:
        task_stats = {}

    return {
        "aria": "running",
        "trainer": trainer_status,
        "agents": {"registered": agent_count},
        "scheduler": {"running": scheduler_running, "jobs": jobs},
        "tasks": task_stats,
        "ts": datetime.utcnow().isoformat(),
    }


@router.post("/chat", dependencies=[Depends(verify_api_key)])
async def api_chat(req: ChatRequest) -> dict:
    """Chat with ARIA mind. Optionally analyze an image via image_base64."""
    try:
        session_id = req.session_id or "api_default"

        # Vision path: analyze image first, then pass description + user question to ARIA
        if req.image_base64:
            from apps.core.tools.ai_client import get_ai_client
            client = get_ai_client()
            description = await client.analyze_image(
                image_base64=req.image_base64,
                question=req.message or "Describe esta imagen en detalle.",
            )
            _log_activity("info", f"Vision [{session_id}]: {req.message[:40]}", "chat")
            return {"reply": description, "tool_used": "analyze_image"}

        from apps.core.cognition.aria_mind import get_aria_mind
        mind = get_aria_mind()
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


@router.get("/tasks", dependencies=[Depends(verify_api_key)])
async def api_tasks(status: str = "") -> dict:
    """List background tasks managed by TaskManager."""
    try:
        from apps.core.tools.task_manager import get_task_manager
        mgr = get_task_manager()
        tasks = mgr.list_tasks(status=status or None, limit=50)
        stats = mgr.stats()
        return {"tasks": tasks, "stats": stats}
    except Exception as exc:
        logger.error("[API /tasks] %s", exc)
        return {"error": str(exc), "tasks": []}


@router.delete("/tasks/{task_id}", dependencies=[Depends(verify_api_key)])
async def api_cancel_task(task_id: str) -> dict:
    """Cancel a queued background task."""
    try:
        from apps.core.tools.task_manager import get_task_manager
        ok = get_task_manager().cancel_task(task_id)
        return {"cancelled": ok, "task_id": task_id}
    except Exception as exc:
        return {"error": str(exc)}


# ── WORKFLOWS ─────────────────────────────────────────────────────────────────


class WorkflowCreateRequest(BaseModel):
    name: str
    description: str


@router.get("/workflows", dependencies=[Depends(verify_api_key)])
async def api_workflows_list() -> dict:
    """List all saved workflows."""
    try:
        from apps.core.tools.workflow_engine import get_workflow_engine
        engine = get_workflow_engine()
        await engine._ensure_loaded()
        return {"workflows": engine.list()}
    except Exception as exc:
        logger.error("[API /workflows] %s", exc)
        return {"error": str(exc), "workflows": []}


@router.post("/workflows", dependencies=[Depends(verify_api_key)])
async def api_workflows_create(req: WorkflowCreateRequest) -> dict:
    """Create a new workflow from a natural-language description."""
    try:
        from apps.core.tools.workflow_engine import get_workflow_engine
        result = await get_workflow_engine().create(req.name, req.description)
        _log_activity("info", f"Workflow created: {req.name}", "workflow")
        return result
    except Exception as exc:
        logger.error("[API /workflows POST] %s", exc)
        return {"error": str(exc)}


@router.post("/workflows/{workflow_id}/run", dependencies=[Depends(verify_api_key)])
async def api_workflows_run(workflow_id: str) -> dict:
    """Execute a workflow by ID."""
    try:
        from apps.core.tools.workflow_engine import get_workflow_engine
        result = await get_workflow_engine().run(workflow_id)
        _log_activity("info", f"Workflow run: {workflow_id}", "workflow")
        return result
    except Exception as exc:
        logger.error("[API /workflows/%s/run] %s", workflow_id, exc)
        return {"error": str(exc)}


@router.delete("/workflows/{workflow_id}", dependencies=[Depends(verify_api_key)])
async def api_workflows_delete(workflow_id: str) -> dict:
    """Delete a workflow by ID."""
    try:
        from apps.core.tools.workflow_engine import get_workflow_engine
        ok = get_workflow_engine().delete(workflow_id)
        return {"deleted": ok, "workflow_id": workflow_id}
    except Exception as exc:
        return {"error": str(exc)}


# ── KNOWLEDGE BASE ─────────────────────────────────────────────────────────────


class KBIngestRequest(BaseModel):
    source: str                         # URL or raw text
    is_url: bool = False
    category: Optional[str] = None
    title: Optional[str] = None         # optional display name for text blocks


@router.get("/knowledge/sources", dependencies=[Depends(verify_api_key)])
async def api_kb_sources() -> dict:
    """List all knowledge base sources."""
    try:
        from apps.core.tools.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        await kb._ensure_loaded()
        sources = kb.list_sources()
        stats = kb.stats()
        return {"sources": sources, "stats": stats}
    except Exception as exc:
        logger.error("[API /knowledge/sources] %s", exc)
        return {"error": str(exc), "sources": []}


@router.post("/knowledge/ingest", dependencies=[Depends(verify_api_key)])
async def api_kb_ingest(req: KBIngestRequest) -> dict:
    """Ingest a URL or text block into the knowledge base."""
    try:
        from apps.core.tools.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        if req.is_url:
            result = await kb.ingest_url(req.source)
        else:
            title = req.title or req.source[:60]
            result = await kb.ingest_text(req.source, title)
        _log_activity("info", f"KB ingest: {req.source[:60]}", "knowledge")
        return result
    except Exception as exc:
        logger.error("[API /knowledge/ingest] %s", exc)
        return {"error": str(exc)}


@router.get("/knowledge/search", dependencies=[Depends(verify_api_key)])
async def api_kb_search(q: str = "", top_k: int = 5) -> dict:
    """Semantic search over the knowledge base."""
    try:
        from apps.core.tools.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        if not q:
            return {"results": [], "query": q}
        results = await kb.search(q, top_k=top_k)
        return {
            "results": [
                {
                    "source": r.get("source", ""),
                    "category": r.get("category", ""),
                    "snippet": r.get("text", "")[:300],
                    "score": r.get("score"),
                    "id": r.get("id"),
                }
                for r in results
            ],
            "query": q,
            "count": len(results),
        }
    except Exception as exc:
        logger.error("[API /knowledge/search] %s", exc)
        return {"error": str(exc), "results": []}


@router.delete("/knowledge/sources/{source_id}", dependencies=[Depends(verify_api_key)])
async def api_kb_delete_source(source_id: str) -> dict:
    """Delete a knowledge base source by source identifier."""
    try:
        from apps.core.tools.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        count = kb.delete_source(source_id)
        await kb._persist()
        return {"deleted": count > 0, "chunks_removed": count, "source_id": source_id}
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/health/ai", dependencies=[Depends(verify_api_key)])
async def api_ai_health() -> dict:
    """Return AI provider health: circuit breakers, success rates, token counts."""
    try:
        from apps.core.tools.ai_client import get_ai_client
        client = get_ai_client()
        return client.get_health_summary()
    except Exception as exc:
        return {"error": str(exc)}


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
    """
    Real-time bidirectional chat with ARIA via WebSocket.

    Incoming JSON: {"type": "chat", "message": "...", "stream": true|false}
    Outgoing (streaming):
      {"type": "chunk",  "text": "..."} × N
      {"type": "reply",  "text": "", "tool_used": ..., "ts": "..."}  ← signals done
    Outgoing (non-streaming):
      {"type": "reply",  "text": "...", "tool_used": ..., "ts": "..."}
    """
    await websocket.accept()
    session_id = f"ws_{id(websocket)}"
    _log_activity("info", f"WebSocket connected: {session_id}", "ws")

    try:
        from apps.core.cognition.aria_mind import get_aria_mind
        mind = get_aria_mind()

        while True:
            data = await websocket.receive_text()

            # Parse as JSON or plain text
            try:
                payload = json.loads(data)
                message = payload.get("message", data)
                want_stream = bool(payload.get("stream", True))
            except Exception:
                message = data
                want_stream = True

            if not message or not message.strip():
                continue

            # Detect if the message likely needs tool execution (non-streamable)
            TOOL_TRIGGERS = [
                "busca", "search", "investiga", "crea", "create", "genera", "generate",
                "ejecuta", "run", "analiza", "analyze", "escribe", "write",
                "código", "code", "imagen", "image", "workflow", "crew",
            ]
            needs_tool = any(t in message.lower() for t in TOOL_TRIGGERS)

            try:
                if want_stream and not needs_tool:
                    # Stream direct AI response for conversational messages
                    from apps.core.tools.ai_client import get_ai_client
                    from apps.core.cognition.aria_mind import SYSTEM_TEMPLATE
                    client = get_ai_client()
                    full_text = ""
                    async for chunk in client.stream_complete(
                        system=SYSTEM_TEMPLATE,
                        user=message,
                        max_tokens=1200,
                        temperature=0.7,
                    ):
                        full_text += chunk
                        await websocket.send_json({"type": "chunk", "text": chunk})
                    await websocket.send_json({
                        "type": "reply",
                        "text": full_text,
                        "tool_used": None,
                        "ts": datetime.utcnow().isoformat(),
                    })
                else:
                    # Full mind: tool use, memory, agent dispatch
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
