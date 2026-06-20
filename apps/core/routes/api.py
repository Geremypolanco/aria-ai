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

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
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


# ── INCOME LOOP ───────────────────────────────────────────────────────────────


@router.get("/income", dependencies=[Depends(verify_api_key)])
async def api_income_status() -> dict:
    """Return IncomeLoop status: running state, cycle stats, recent history."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        loop = get_income_loop()
        return await loop.get_status_dict()
    except Exception as exc:
        logger.error("[API /income] %s", exc)
        return {"error": str(exc)}


class IncomeCycleRequest(BaseModel):
    strategy: Optional[str] = None


@router.post("/income/cycle", dependencies=[Depends(verify_api_key)])
async def api_income_run_cycle(req: IncomeCycleRequest | None = None) -> dict:
    """Execute one income cycle immediately (optionally with a specific strategy)."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        loop = get_income_loop()
        strategy = req.strategy if req else None
        result = await loop._run_one_cycle(force_strategy=strategy)
        _log_activity("info", f"Income cycle: {result.strategy} — {result.summary[:60]}", "income")
        return {
            "cycle_id": result.cycle_id,
            "strategy": result.strategy,
            "success": result.success,
            "summary": result.summary,
            "revenue_potential": result.revenue_potential,
            "urls_created": result.urls_created,
            "elapsed_seconds": result.elapsed_seconds,
        }
    except Exception as exc:
        logger.error("[API /income/cycle] %s", exc)
        return {"error": str(exc)}


@router.post("/income/start", dependencies=[Depends(verify_api_key)])
async def api_income_start() -> dict:
    """Start the IncomeLoop if not already running."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        loop = get_income_loop()
        if not loop.is_running:
            await loop.start()
        return {"running": loop.is_running}
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/income/stop", dependencies=[Depends(verify_api_key)])
async def api_income_stop() -> dict:
    """Stop the IncomeLoop."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        loop = get_income_loop()
        loop.stop()
        return {"running": loop.is_running}
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/income/strategies", dependencies=[Depends(verify_api_key)])
async def api_income_strategies() -> dict:
    """Return all income strategies with weights and channel requirements."""
    try:
        from apps.core.tools.income_loop import STRATEGIES, get_income_loop
        loop = get_income_loop()
        creds = loop.check_credentials()
        total_weight = sum(w for _, w in STRATEGIES)
        return {
            "strategies": [
                {
                    "name": name,
                    "weight": weight,
                    "probability_pct": round(weight / total_weight * 100, 1),
                }
                for name, weight in STRATEGIES
            ],
            "total_weight": total_weight,
            "channels": creds,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/income/credentials", dependencies=[Depends(verify_api_key)])
async def api_income_credentials() -> dict:
    """Show which income channels are configured vs. missing."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        loop = get_income_loop()
        creds = loop.check_credentials()
        active_count   = len(creds.get("active", {}))
        inactive_count = len(creds.get("inactive", {}))
        return {
            "active_count": active_count,
            "inactive_count": inactive_count,
            "active": list(creds.get("active", {}).keys()),
            "inactive": {
                k: v.get("keys_needed", [])
                for k, v in creds.get("inactive", {}).items()
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/income/catalog", dependencies=[Depends(verify_api_key)])
async def api_income_catalog(limit: int = 50) -> dict:
    """Return the product catalog — all published products, articles, and resources."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        from apps.core.memory.redis_client import get_cache
        import json as _json
        cache = get_cache()
        if not cache:
            return {"items": [], "total": 0, "error": "Redis unavailable"}
        raw_items = await cache.lrange("aria:products:catalog", -limit, -1)
        items = []
        total_revenue = 0.0
        for raw in reversed(raw_items or []):
            try:
                item = _json.loads(raw) if isinstance(raw, str) else raw
                items.append(item)
                total_revenue += item.get("revenue", 0)
            except Exception:
                pass
        return {
            "total": len(items),
            "total_revenue_potential": round(total_revenue, 2),
            "items": items,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/income/run/{strategy}", dependencies=[Depends(verify_api_key)])
async def api_income_run_strategy(strategy: str) -> dict:
    """Immediately run a specific income strategy."""
    from apps.core.tools.income_loop import get_income_loop, STRATEGIES
    valid = [s[0] for s in STRATEGIES]
    if strategy not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown strategy '{strategy}'. Valid: {valid}")
    try:
        loop   = get_income_loop()
        result = await loop._run_one_cycle(force_strategy=strategy)
        return {
            "strategy": result.strategy,
            "success": result.success,
            "summary": result.summary,
            "revenue_potential": result.revenue_potential,
            "urls_created": result.urls_created,
            "elapsed_seconds": result.elapsed_seconds,
        }
    except Exception as exc:
        return {"error": str(exc), "strategy": strategy}


@router.get("/income/analytics", dependencies=[Depends(verify_api_key)])
async def api_income_analytics() -> dict:
    """Per-strategy analytics: runs, success rate, revenue, URLs published."""
    try:
        from apps.core.tools.income_loop import get_income_loop, STRATEGIES
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            return {"error": "Redis unavailable"}
        loop = get_income_loop()
        total_cycles   = int(await cache.get("aria:income:total_cycles") or 0)
        success_cycles = int(await cache.get("aria:income:successful_cycles") or 0)
        total_urls     = int(await cache.get("aria:income:total_urls_published") or 0)
        per_strategy = []
        for name, weight in STRATEGIES:
            runs  = int(await cache.get(f"aria:income:strategy:{name}:runs") or 0)
            wins  = int(await cache.get(f"aria:income:strategy:{name}:successes") or 0)
            raw_r = await cache.get(f"aria:income:strategy:{name}:revenue")
            rev   = float(raw_r) if raw_r else 0.0
            per_strategy.append({
                "strategy": name,
                "weight": weight,
                "runs": runs,
                "successes": wins,
                "win_rate": round(wins / runs * 100, 1) if runs else 0,
                "revenue": round(rev, 2),
            })
        per_strategy.sort(key=lambda x: (-x["revenue"], -x["runs"]))
        return {
            "total_cycles": total_cycles,
            "successful_cycles": success_cycles,
            "overall_success_rate": round(success_cycles / total_cycles * 100, 1) if total_cycles else 0,
            "total_urls_published": total_urls,
            "per_strategy": per_strategy,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/income/projection", dependencies=[Depends(verify_api_key)])
async def api_income_projection() -> dict:
    """Revenue projection based on actual cycle performance."""
    try:
        from apps.core.tools.income_loop import INTERVAL_SECONDS
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            return {"error": "Redis unavailable"}
        total_cycles   = int(await cache.get("aria:income:total_cycles") or 0)
        total_urls     = int(await cache.get("aria:income:total_urls_published") or 0)
        from apps.core.tools.income_loop import STRATEGIES
        total_rev = 0.0
        for name, _ in STRATEGIES:
            raw_r = await cache.get(f"aria:income:strategy:{name}:revenue")
            if raw_r:
                total_rev += float(raw_r)
        if total_cycles == 0:
            return {"message": "No cycles yet — loop hasn't started", "projected_7d": 0, "projected_30d": 0}
        cycles_per_day = (24 * 3600) / INTERVAL_SECONDS
        rev_per_cycle  = total_rev / total_cycles
        return {
            "total_cycles": total_cycles,
            "total_revenue_potential": round(total_rev, 2),
            "revenue_per_cycle": round(rev_per_cycle, 4),
            "cycles_per_day": round(cycles_per_day, 1),
            "projected_7d": round(rev_per_cycle * cycles_per_day * 7, 2),
            "projected_30d": round(rev_per_cycle * cycles_per_day * 30, 2),
            "projected_90d": round(rev_per_cycle * cycles_per_day * 90, 2),
            "total_urls_published": total_urls,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/github/traction", dependencies=[Depends(verify_api_key)])
async def api_github_traction() -> dict:
    """Monitor star/fork/watcher counts on ARIA's public repos."""
    try:
        from apps.core.tools.github_client import AriaGitHubClient
        from apps.core.config_pkg import settings as _s
        gh    = AriaGitHubClient()
        owner = _s.GITHUB_USERNAME or "Geremypolanco"

        # Repos ARIA creates autonomously
        aria_repos = [
            "aria-insights", "aria-portfolio", "aria-free-resources",
            "aria-newsletter", "aria-ai",
        ]
        traction = []
        total_stars = 0
        for repo in aria_repos:
            info = await gh.get_repo(owner, repo)
            if "error" not in info:
                stars = info.get("stargazers_count", 0)
                forks = info.get("forks_count", 0)
                total_stars += stars
                traction.append({
                    "repo": repo,
                    "stars": stars,
                    "forks": forks,
                    "watchers": info.get("watchers_count", 0),
                    "open_issues": info.get("open_issues_count", 0),
                    "url": info.get("html_url", ""),
                })
        traction.sort(key=lambda x: -x["stars"])
        return {
            "owner": owner,
            "repos_tracked": len(traction),
            "total_stars": total_stars,
            "repos": traction,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── AUTONOMOUS OBJECTIVES API ─────────────────────────────────────────────────


@router.get(
    "/income/objectives",
    dependencies=[Depends(verify_api_key)],
    summary="List all 22+ strategic objectives and their status",
)
async def api_income_objectives() -> dict:
    """Returns the full list of autonomous strategic objectives with next-run times."""
    try:
        import time
        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
        scheduler = get_autonomous_scheduler()
        objs = await scheduler.get_objectives()
        summary = scheduler.summary()
        now = time.time()
        return {
            "summary": summary,
            "objectives": [
                {
                    "id": o.obj_id,
                    "name": o.name,
                    "description": o.description,
                    "status": o.status.value,
                    "priority": o.priority.value,
                    "frequency_hours": o.frequency_hours,
                    "next_run_in_hours": max(0.0, round((o.next_run_ts - now) / 3600, 2)),
                    "total_runs": o.total_runs,
                    "success_count": o.success_count,
                    "total_value_usd": round(o.total_value_usd, 2),
                }
                for o in sorted(objs, key=lambda o: o.priority.value)
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class RunObjectiveRequest(BaseModel):
    objective: str


@router.post(
    "/income/run-objective",
    dependencies=[Depends(verify_api_key)],
    summary="Trigger a strategic objective immediately",
)
async def api_income_run_objective(req: RunObjectiveRequest) -> dict:
    """Runs a named strategic objective right now (bypasses scheduler timer)."""
    try:
        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
        scheduler = get_autonomous_scheduler()
        objs = await scheduler.get_objectives()
        target = next((o for o in objs if o.obj_id == req.objective), None)
        if not target:
            valid = [o.obj_id for o in objs]
            raise HTTPException(
                status_code=404,
                detail=f"Objective '{req.objective}' not found. Valid: {valid}",
            )
        record = await scheduler._run_objective(target)
        all_objs = {o.obj_id: o for o in objs}
        all_objs[target.obj_id] = target
        await scheduler._save_objectives(all_objs)
        return {
            "objective": req.objective,
            "success": record.success,
            "summary": record.output.get("summary", record.error or "completed"),
            "value_generated_usd": record.value_generated_usd,
            "duration_seconds": round(record.completed_at - record.started_at, 2),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/income/rapid-launch",
    dependencies=[Depends(verify_api_key)],
    summary="Rapid launch: trend → product → landing page → amplify (4-step pipeline)",
)
async def api_income_rapid_launch() -> dict:
    """
    Executes a full product launch pipeline in one API call:
    1. opportunity_scan → find trending niche
    2. product_factory → create a sellable product
    3. landing_page_deploy → deploy HTML landing page to GitHub Pages
    4. voice_of_aria → Telegram announcement + social post
    Returns all URLs created.
    """
    try:
        import asyncio
        from apps.core.tools.income_loop import get_income_loop
        loop = get_income_loop()
        steps = [
            "opportunity_scan",
            "product_factory",
            "landing_page_deploy",
            "voice_of_aria",
        ]
        results = []
        all_urls: list[str] = []
        for step in steps:
            r = await loop._run_one_cycle(force_strategy=step)
            results.append({
                "step": step,
                "success": r.success,
                "summary": r.summary,
                "revenue_potential": r.revenue_potential,
                "urls": r.urls_created,
            })
            all_urls.extend(r.urls_created)
        successes = sum(1 for r in results if r["success"])
        total_rev = sum(r["revenue_potential"] for r in results)
        _log_activity("info", f"Rapid launch: {successes}/{len(steps)} steps, {len(all_urls)} URLs", "income")
        return {
            "success": successes >= 2,
            "steps_completed": successes,
            "steps_total": len(steps),
            "total_revenue_potential": round(total_rev, 2),
            "urls_created": all_urls,
            "details": results,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/intel/competitor",
    dependencies=[Depends(verify_api_key)],
    summary="Get latest competitor intelligence scan",
)
async def api_intel_competitor() -> dict:
    """Returns the latest competitor intel from the 12h automated scan."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        raw = await cache.get("aria:intel:competitor_latest")
        if not raw:
            return {"status": "no_data", "message": "Run competitor_intel objective to generate data"}
        return _json.loads(raw)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/schedule/content-calendar",
    dependencies=[Depends(verify_api_key)],
    summary="Get the active 30-day content calendar",
)
async def api_content_calendar() -> dict:
    """Returns the current 30-day content calendar metadata and GitHub URL."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        raw = await cache.get("aria:schedule:content_calendar")
        if not raw:
            return {"status": "no_data", "message": "Run content_calendar_builder objective to generate"}
        return _json.loads(raw)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── STRIPE WEBHOOK ────────────────────────────────────────────────────────────


@router.post(
    "/webhooks/stripe",
    summary="Stripe payment webhook — ARIA reacts to real payments instantly",
    include_in_schema=False,
)
async def stripe_webhook(request: Request) -> dict:
    """
    Receives Stripe webhook events. On payment_intent.succeeded or
    checkout.session.completed, ARIA:
    1. Logs the payment to Redis revenue history
    2. Sends Telegram alert to owner
    3. Triggers a thank-you email via email_funnel_handler
    """
    try:
        import json as _json
        import hashlib as _hl
        import hmac as _hmac
        from apps.core.config import settings
        from apps.core.memory.redis_client import get_cache

        body = await request.body()
        sig = request.headers.get("stripe-signature", "")
        webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""

        # Verify signature when secret is configured
        if webhook_secret and sig:
            try:
                parts = {p.split("=")[0]: p.split("=")[1] for p in sig.split(",") if "=" in p}
                ts = parts.get("t", "")
                v1 = parts.get("v1", "")
                signed_payload = f"{ts}.{body.decode()}"
                expected = _hmac.new(
                    webhook_secret.encode(), signed_payload.encode(), _hl.sha256
                ).hexdigest()  # type: ignore[attr-defined]
                if not _hmac.compare_digest(expected, v1):
                    raise HTTPException(status_code=400, detail="Invalid Stripe signature")
            except HTTPException:
                raise
            except Exception:
                pass  # If signature verification fails gracefully, still process in dev

        event = _json.loads(body)
        event_type = event.get("type", "")
        data_obj = event.get("data", {}).get("object", {})

        if event_type in ("payment_intent.succeeded", "checkout.session.completed"):
            amount_received = data_obj.get("amount_received", data_obj.get("amount_total", 0))
            amount_usd = round(amount_received / 100, 2)
            customer_email = data_obj.get("receipt_email") or data_obj.get("customer_details", {}).get("email", "")
            payment_id = data_obj.get("id", "")

            # Log to Redis
            cache = get_cache()
            if cache:
                import datetime as _dt
                entry = {
                    "ts": _dt.datetime.utcnow().isoformat(),
                    "total_usd": amount_usd,
                    "source": "stripe_webhook",
                    "payment_id": payment_id,
                }
                history_raw = await cache.get("aria:revenue:history")
                history = _json.loads(history_raw) if history_raw else []
                history.append(entry)
                history = history[-120:]
                await cache.set("aria:revenue:history", _json.dumps(history), ex=86400 * 35)

                # Update latest snapshot
                latest_raw = await cache.get("aria:revenue:latest")
                latest = _json.loads(latest_raw) if latest_raw else {"total_usd": 0.0, "channels": []}
                latest["total_usd"] = round(latest.get("total_usd", 0) + amount_usd, 2)
                latest["last_payment_usd"] = amount_usd
                latest["last_payment_ts"] = entry["ts"]
                await cache.set("aria:revenue:latest", _json.dumps(latest), ex=86400 * 7)

                # Queue customer email for nurture
                if customer_email:
                    sub = _json.dumps({"email": customer_email, "name": "", "product": "purchase"})
                    await cache.rpush("aria:waitlist:new", sub)

            # Telegram alert
            try:
                import aiohttp as _aio
                bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
                chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "") or ""
                if bot_token and chat_id:
                    msg = f"🎉 NUEVA VENTA — ${amount_usd:.2f}\n\nPago ID: {payment_id}\nCliente: {customer_email or 'anónimo'}\n\n¡ARIA lo hizo! 💪"
                    async with _aio.ClientSession() as sess:
                        await sess.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": msg},
                            timeout=_aio.ClientTimeout(total=10),
                        )
            except Exception:
                pass

        return {"received": True, "type": event_type}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("stripe_webhook error: %s", exc)
        return {"received": True}


# ── REVENUE DASHBOARD ─────────────────────────────────────────────────────────


@router.get(
    "/revenue",
    dependencies=[Depends(verify_api_key)],
    summary="Real revenue data aggregated from Stripe, Gumroad, GitHub Sponsors",
)
async def api_revenue_dashboard() -> dict:
    """Returns the latest aggregated revenue report from all active channels."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        raw = await cache.get("aria:revenue:latest")
        if not raw:
            return {
                "status": "no_data",
                "message": "Run revenue_aggregator objective to collect real data",
            }
        report = _json.loads(raw)
        # Also include rolling history summary
        hist_raw = await cache.get("aria:revenue:history")
        history = _json.loads(hist_raw) if hist_raw else []
        if history:
            report["history_points"] = len(history)
            report["7d_total_usd"] = round(sum(h["total_usd"] for h in history[-28:]), 2)
            report["30d_total_usd"] = round(sum(h["total_usd"] for h in history), 2)
        return report
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/revenue/history",
    dependencies=[Depends(verify_api_key)],
    summary="Rolling 30-day revenue history snapshots",
)
async def api_revenue_history() -> dict:
    """Returns up to 120 revenue snapshots (6h intervals = 30 days)."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        raw = await cache.get("aria:revenue:history")
        history = _json.loads(raw) if raw else []
        return {"points": len(history), "history": history}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/revenue/notify",
    dependencies=[Depends(verify_api_key)],
    summary="Send a Telegram notification when real revenue is detected",
)
async def api_revenue_notify() -> dict:
    """Triggers immediate revenue aggregation and sends Telegram alert if revenue > $0."""
    try:
        import json as _json
        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
        scheduler = get_autonomous_scheduler()
        objs = await scheduler.get_objectives()
        target = next((o for o in objs if o.obj_id == "revenue_aggregator"), None)
        if not target:
            raise HTTPException(status_code=404, detail="revenue_aggregator objective not found")
        record = await scheduler._run_objective(target)
        result = record.output
        total = result.get("value_usd", 0.0) or 0.0
        if total > 0:
            try:
                from apps.core.config import settings
                import aiohttp as _aio
                bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
                chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "") or ""
                if bot_token and chat_id:
                    channels = result.get("channels", [])
                    ch_str = " | ".join(f"{c['channel']}: ${c.get('revenue_usd', 0):.2f}" for c in channels)
                    msg = f"💰 ARIA Revenue Alert\n\nTotal: ${total:.2f}\n{ch_str}\n\n#{_json.dumps({'ts': result.get('timestamp', '')})}"
                    async with _aio.ClientSession() as sess:
                        await sess.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": msg[:4000]},
                            timeout=_aio.ClientTimeout(total=10),
                        )
            except Exception:
                pass
        return {"success": record.success, "total_usd": total, "notified": total > 0}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GUMROAD WEBHOOK ───────────────────────────────────────────────────────────


@router.post(
    "/webhooks/gumroad",
    summary="Gumroad sale webhook — ARIA reacts to product sales instantly",
    include_in_schema=False,
)
async def gumroad_webhook(request: Request) -> dict:
    """
    Gumroad sends a POST on every sale. ARIA:
    1. Logs the sale to Redis revenue history
    2. Sends Telegram alert with product name + amount
    3. Queues buyer email for nurture sequence
    """
    try:
        import json as _json
        import datetime as _dt
        from apps.core.config import settings
        from apps.core.memory.redis_client import get_cache

        # Gumroad sends form-encoded data
        form = await request.form()
        sale_id = form.get("sale_id", "")
        price = float(form.get("price", "0") or "0") / 100  # cents to dollars
        product_name = form.get("product_name", "Unknown Product")
        buyer_email = form.get("email", "")
        buyer_name = form.get("full_name", "")

        if price <= 0:
            return {"received": True}

        cache = get_cache()
        if cache:
            entry = {
                "ts": _dt.datetime.utcnow().isoformat(),
                "total_usd": price,
                "source": "gumroad_webhook",
                "sale_id": sale_id,
                "product": product_name,
            }
            history_raw = await cache.get("aria:revenue:history")
            history = _json.loads(history_raw) if history_raw else []
            history.append(entry)
            history = history[-120:]
            await cache.set("aria:revenue:history", _json.dumps(history), ex=86400 * 35)

            latest_raw = await cache.get("aria:revenue:latest")
            latest = _json.loads(latest_raw) if latest_raw else {"total_usd": 0.0, "channels": []}
            latest["total_usd"] = round(latest.get("total_usd", 0) + price, 2)
            latest["last_payment_usd"] = price
            latest["last_payment_ts"] = entry["ts"]
            latest["last_payment_product"] = product_name
            await cache.set("aria:revenue:latest", _json.dumps(latest), ex=86400 * 7)

            if buyer_email:
                sub = _json.dumps({"email": buyer_email, "name": buyer_name, "product": product_name})
                await cache.rpush("aria:waitlist:new", sub)

        # Telegram alert
        try:
            import aiohttp as _aio
            bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
            chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "") or ""
            if bot_token and chat_id:
                msg = f"🛒 VENTA EN GUMROAD — ${price:.2f}\n\n📦 Producto: {product_name}\n👤 Comprador: {buyer_name or buyer_email or 'anónimo'}\n\n¡ARIA generó ingresos reales! 🚀"
                async with _aio.ClientSession() as sess:
                    await sess.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg},
                        timeout=_aio.ClientTimeout(total=10),
                    )
        except Exception:
            pass

        return {"received": True}
    except Exception as exc:
        logger.warning("gumroad_webhook error: %s", exc)
        return {"received": True}


# ── ARIA INTELLIGENCE DASHBOARD ───────────────────────────────────────────────


@router.get(
    "/intelligence",
    dependencies=[Depends(verify_api_key)],
    summary="ARIA full operational intelligence: revenue + objectives + content + competitors",
)
async def api_intelligence_dashboard() -> dict:
    """One-stop intelligence endpoint combining all ARIA's active intelligence streams."""
    try:
        import json as _json
        import datetime as _dt
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()

        result: dict = {"generated_at": _dt.datetime.utcnow().isoformat()}

        if not cache:
            result["error"] = "Redis unavailable"
            return result

        # Revenue
        rev_raw = await cache.get("aria:revenue:latest")
        result["revenue"] = _json.loads(rev_raw) if rev_raw else {"total_usd": 0.0}

        # Competitor intel
        intel_raw = await cache.get("aria:intel:competitor_latest")
        result["competitor_intel"] = _json.loads(intel_raw) if intel_raw else None

        # Content calendar
        cal_raw = await cache.get("aria:schedule:content_calendar")
        if cal_raw:
            cal = _json.loads(cal_raw)
            result["content_calendar"] = {
                "theme": cal.get("theme", ""),
                "entries_count": len(cal.get("entries", [])),
                "generated_at": cal.get("generated_at", ""),
            }

        # Smart prices
        prices_raw = await cache.get("aria:income:smart_prices")
        result["smart_prices"] = _json.loads(prices_raw) if prices_raw else None

        # Opportunity queue length
        opp_len = await cache.llen("aria:income:opportunity_queue")
        result["opportunity_queue_depth"] = opp_len or 0

        # Income loop stats
        stats_raw = await cache.get("aria:income:stats")
        result["income_loop_stats"] = _json.loads(stats_raw) if stats_raw else None

        # Published posts tracker
        pub_raw = await cache.get("aria:social:published_ids")
        pub_ids = _json.loads(pub_raw) if pub_raw else []
        result["posts_published"] = len(pub_ids)

        # Nurture queue size
        nurture_raw = await cache.get("aria:email:nurture_queue")
        nurture = _json.loads(nurture_raw) if nurture_raw else {}
        result["email_nurture_contacts"] = len(nurture)

        # Account health
        acct_raw = await cache.get("aria:accounts:health_report")
        result["account_health"] = _json.loads(acct_raw) if acct_raw else None

        # Latest social proof
        sp_raw = await cache.get("aria:social_proof:latest")
        result["social_proof_count"] = len(_json.loads(sp_raw)) if sp_raw else 0

        # Cross-sell campaign
        cs_raw = await cache.get("aria:campaigns:latest_cross_sell")
        result["latest_cross_sell"] = _json.loads(cs_raw) if cs_raw else None

        # Product update log count
        upd_raw = await cache.get("aria:products:update_log")
        upd_log = _json.loads(upd_raw) if upd_raw else []
        result["product_updates_count"] = len(upd_log)

        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── INCOME GOALS ──────────────────────────────────────────────────────────────


class SetGoalRequest(BaseModel):
    daily_revenue_usd: float = 100.0
    weekly_revenue_usd: float = 700.0


@router.post(
    "/goals/revenue",
    dependencies=[Depends(verify_api_key)],
    summary="Set daily and weekly revenue goals for ARIA",
)
async def api_set_revenue_goals(req: SetGoalRequest) -> dict:
    """Sets ARIA's income targets. daily_goal_tracker strategy will use these."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        await cache.set("aria:goals:daily_revenue_usd", str(req.daily_revenue_usd), ex=86400 * 365)
        await cache.set("aria:goals:weekly_revenue_usd", str(req.weekly_revenue_usd), ex=86400 * 365)
        return {
            "daily_goal_usd": req.daily_revenue_usd,
            "weekly_goal_usd": req.weekly_revenue_usd,
            "message": "Goals set. ARIA will auto-trigger high-conversion strategies when behind.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/goals/revenue",
    dependencies=[Depends(verify_api_key)],
    summary="View current revenue goals and daily performance",
)
async def api_get_revenue_goals() -> dict:
    """Returns current revenue goals and today's progress."""
    try:
        import json as _json
        import datetime as _dt
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        daily_raw = await cache.get("aria:goals:daily_revenue_usd")
        weekly_raw = await cache.get("aria:goals:weekly_revenue_usd")
        daily_goal = float(daily_raw) if daily_raw else 100.0
        weekly_goal = float(weekly_raw) if weekly_raw else 700.0

        today_str = _dt.datetime.utcnow().strftime("%Y-%m-%d")
        today_snap_raw = await cache.get(f"aria:goals:daily:{today_str}")
        today_snap = _json.loads(today_snap_raw) if today_snap_raw else {}

        weekly_snaps_raw = await cache.get("aria:goals:weekly_snaps")
        weekly_snaps = _json.loads(weekly_snaps_raw) if weekly_snaps_raw else {}
        week_total = sum(v.get("revenue_usd", 0) for v in list(weekly_snaps.values())[-7:])

        return {
            "daily_goal_usd": daily_goal,
            "weekly_goal_usd": weekly_goal,
            "today": today_snap,
            "week_total_usd": round(week_total, 2),
            "week_to_goal_pct": round(week_total / weekly_goal * 100, 1) if weekly_goal > 0 else 0,
            "days_tracked": len(weekly_snaps),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/goals/weekly-performance",
    dependencies=[Depends(verify_api_key)],
    summary="14-day rolling revenue performance vs goals",
)
async def api_weekly_performance() -> dict:
    """Returns 14-day daily revenue vs goals for trend analysis."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")
        snaps_raw = await cache.get("aria:goals:weekly_snaps")
        snaps = _json.loads(snaps_raw) if snaps_raw else {}
        daily_raw = await cache.get("aria:goals:daily_revenue_usd")
        daily_goal = float(daily_raw) if daily_raw else 100.0
        return {
            "daily_goal_usd": daily_goal,
            "snapshots": snaps,
            "days_on_track": sum(1 for v in snaps.values() if v.get("on_track", False)),
            "days_tracked": len(snaps),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GROWTH & AUDIENCE METRICS ─────────────────────────────────────────────────


@router.get(
    "/growth",
    dependencies=[Depends(verify_api_key)],
    summary="Audience growth metrics across all platforms",
)
async def api_growth_metrics() -> dict:
    """Returns follower counts, deltas, and audience builder history."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")

        gh_followers = int(await cache.get("aria:growth:github_followers_prev") or 0)
        devto_followers = int(await cache.get("aria:growth:devto_followers_prev") or 0)
        last_run = await cache.get("aria:growth:last_run")
        total_replies = int(await cache.get("aria:engagement:total_replies") or 0)
        total_aff_injections = int(await cache.get("aria:affiliate:total_injections") or 0)

        # Growth history (last 10 snapshots)
        raw_hist = await cache.lrange("aria:growth:history", -10, -1)
        history = []
        for raw in (raw_hist or []):
            try:
                entry = _json.loads(raw) if isinstance(raw, str) else raw
                history.append(entry)
            except Exception:
                pass

        # DM outreach stats
        total_dm_templates = int(await cache.get("aria:outreach:total_templates_generated") or 0)
        raw_dms = await cache.get("aria:outreach:dm_templates")
        dm_count = len(_json.loads(raw_dms)) if raw_dms else 0

        return {
            "platform_followers": {
                "github": gh_followers,
                "devto": devto_followers,
            },
            "engagement": {
                "total_auto_replies": total_replies,
                "affiliate_injections": total_aff_injections,
                "dm_templates_generated": total_dm_templates,
                "dm_templates_active": dm_count,
            },
            "last_audience_build_run": last_run,
            "growth_history": history[-10:],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/reputation",
    dependencies=[Depends(verify_api_key)],
    summary="Reputation and community engagement metrics",
)
async def api_reputation_metrics() -> dict:
    """Returns community engagement stats, HN comments queue, and reputation score."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")

        total_engagements = int(await cache.get("aria:reputation:total_engagements") or 0)

        # Recent reputation history
        raw_hist = await cache.lrange("aria:reputation:history", -10, -1)
        history = []
        for raw in (raw_hist or []):
            try:
                entry = _json.loads(raw) if isinstance(raw, str) else raw
                history.append(entry)
            except Exception:
                pass

        # Queued HN comments
        raw_hn = await cache.lrange("aria:reputation:hn_comments_queued", 0, -1)
        hn_queue = []
        for raw in (raw_hn or []):
            try:
                hn_queue.append(_json.loads(raw) if isinstance(raw, str) else raw)
            except Exception:
                pass

        # Podcast stats
        total_episodes = int(await cache.get("aria:podcast:episodes_produced") or 0)
        latest_ep_raw = await cache.get("aria:podcast:latest_episode")
        latest_episode = _json.loads(latest_ep_raw) if latest_ep_raw else None

        return {
            "total_community_engagements": total_engagements,
            "podcast_episodes_produced": total_episodes,
            "latest_episode": latest_episode,
            "hn_comments_queued": len(hn_queue),
            "hn_queue_preview": hn_queue[:3],
            "reputation_history": history[-10:],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/pipeline",
    dependencies=[Depends(verify_api_key)],
    summary="Full business pipeline: grants, freelance, investor deck, waitlists",
)
async def api_pipeline() -> dict:
    """Returns all pipeline stages: investor deck, grant applications, freelance proposals, SaaS waitlists."""
    try:
        import json as _json
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        if not cache:
            raise HTTPException(status_code=503, detail="Redis unavailable")

        # Grant pipeline
        raw_grants = await cache.lrange("aria:grants:applications", -5, -1)
        grants = []
        for raw in (raw_grants or []):
            try:
                grants.append(_json.loads(raw) if isinstance(raw, str) else raw)
            except Exception:
                pass
        grant_potential = float(await cache.get("aria:grants:total_potential") or 0)

        # Freelance proposals
        raw_proposals = await cache.lrange("aria:freelance:proposals", -5, -1)
        proposals = []
        for raw in (raw_proposals or []):
            try:
                proposals.append(_json.loads(raw) if isinstance(raw, str) else raw)
            except Exception:
                pass
        total_proposals = int(await cache.get("aria:freelance:total_proposals") or 0)

        # Investor deck
        investor_raw = await cache.get("aria:investor:latest_deck")
        investor_deck = _json.loads(investor_raw) if investor_raw else None

        # Waitlists
        waitlist_raw = await cache.get("aria:waitlist:latest")
        latest_waitlist = _json.loads(waitlist_raw) if waitlist_raw else None
        total_waitlists = int(await cache.get("aria:waitlist:total_launches") or 0)

        # Upsell stats
        upsell_raw = await cache.get("aria:upsell:last_campaign")
        latest_upsell = _json.loads(upsell_raw) if upsell_raw else None
        total_upsell_campaigns = int(await cache.get("aria:upsell:total_campaigns") or 0)

        return {
            "grants": {
                "total_potential_usd": grant_potential,
                "applications_count": len(grants),
                "recent": grants[-3:],
            },
            "freelance": {
                "total_proposals": total_proposals,
                "recent_proposals": proposals[-3:],
            },
            "investor": {
                "latest_deck": investor_deck,
            },
            "waitlists": {
                "total_launched": total_waitlists,
                "latest": latest_waitlist,
            },
            "upsell": {
                "total_campaigns": total_upsell_campaigns,
                "latest": latest_upsell,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/triggers/run-due",
    dependencies=[Depends(verify_api_key)],
    summary="Force run all due strategic objectives immediately",
)
async def api_run_due_objectives() -> dict:
    """Triggers an immediate check + execution of all due strategic objectives."""
    try:
        from apps.runtime.autonomy.autonomous_scheduler import get_autonomous_scheduler
        scheduler = get_autonomous_scheduler()
        records = await scheduler.run_due_objectives()
        return {
            "objectives_run": len(records),
            "successes": sum(1 for r in records if r.success),
            "total_value_usd": round(sum(r.value_generated_usd for r in records), 2),
            "results": [
                {
                    "obj_id": r.obj_id,
                    "success": r.success,
                    "value_usd": r.value_generated_usd,
                    "summary": r.output.get("summary", r.error or "done"),
                    "duration_s": round(r.completed_at - r.started_at, 1),
                }
                for r in records
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/triggers/income-cycle",
    dependencies=[Depends(verify_api_key)],
    summary="Run one income loop cycle immediately",
)
async def api_run_income_cycle(body: dict) -> dict:
    """Run one income loop cycle with optional strategy override."""
    try:
        from apps.core.tools.income_loop import get_income_loop
        strategy = body.get("strategy") if body else None
        loop = get_income_loop()
        result = await loop._run_one_cycle(force_strategy=strategy)
        return {
            "cycle_id": result.cycle_id,
            "strategy": result.strategy,
            "success": result.success,
            "summary": result.summary,
            "revenue_potential": result.revenue_potential,
            "urls_created": result.urls_created,
            "elapsed_seconds": result.elapsed_seconds,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
