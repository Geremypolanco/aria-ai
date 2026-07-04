"""
ARIA Agent System — API Routes.
Endpoints REST para gestión completa de tareas y agentes.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.models import ChatRequest, ChatResponse, TaskCreateRequest, TaskResponse, TaskListResponse
from api.server import lifecycle, tool_registry, sandbox, browser
from core.db.repository import TaskRepository, TaskLogRepository

logger = logging.getLogger("aria.api.routes")

router = APIRouter(prefix="/api/v1", tags=["Tasks"])


# ── Tareas ───────────────────────────────────────────────

@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(req: TaskCreateRequest):
    """
    Crea una nueva tarea y la pasa al sistema multi-agente.

    El ciclo completo: Planner → Execution → Verification
    """
    try:
        # Crear task_id via lifecycle
        task_id = await lifecycle.create_task(
            task_type=req.task_type,
            title=req.title or req.task_type,
            input_data=req.input,
            max_retries=req.max_retries,
            session_id=req.session_id,
        )

        # Persistir en DB (async)
        try:
            await TaskRepository.create(
                task_type=req.task_type,
                title=req.title or req.task_type,
                input_data=req.input,
                priority=req.priority,
                max_retries=req.max_retries,
                session_id=req.session_id,
            )
        except Exception as e:
            logger.warning("No se pudo persistir tarea en DB: %s", e)

        return TaskResponse(
            id=task_id,
            status="pending",
            task_type=req.task_type,
            title=req.title or req.task_type,
            created_at=__import__("datetime").datetime.utcnow(),
        )

    except Exception as e:
        logger.exception("Error creando tarea")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
):
    """Lista tareas con paginación y filtro opcional."""
    try:
        tasks = await TaskRepository.list(
            status=status,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = await TaskRepository.count(status=status)

        return TaskListResponse(
            tasks=[TaskResponse(**t) for t in tasks],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.exception("Error listando tareas")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """Obtiene el estado de una tarea por ID."""
    # Primero buscar en memory (lifecycle manager)
    task = lifecycle.get_task_status(task_id)

    if not task:
        # Fallback a DB
        try:
            task = await TaskRepository.get(task_id)
        except Exception:
            pass

    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    return TaskResponse(
        id=task["id"],
        status=task["status"],
        task_type=task.get("task_type", "custom"),
        title=task.get("title", ""),
        created_at=__import__("datetime").datetime.utcnow(),
        started_at=__import__("datetime").datetime.utcnow() if task.get("started_at") else None,
        completed_at=__import__("datetime").datetime.utcnow() if task.get("completed_at") else None,
        error_message=task.get("error"),
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancela una tarea activa."""
    success = await lifecycle.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tarea no encontrada o ya completada")
    return {"status": "cancelled", "task_id": task_id}


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, limit: int = Query(50, ge=1, le=500)):
    """Obtiene los logs de una tarea."""
    try:
        logs = await TaskLogRepository.get_logs(task_id, limit=limit)
        return {"task_id": task_id, "logs": logs, "count": len(logs)}
    except Exception as e:
        logger.exception("Error obteniendo logs")
        raise HTTPException(status_code=500, detail=str(e))


# ── Agentes ──────────────────────────────────────────────

@router.get("/agents")
async def list_agents():
    """Lista los agentes activos y su estado."""
    return {
        "agents": [
            {
                "type": agent_type.value,
                "id": agent.agent_id,
                "uptime_seconds": agent.uptime_seconds,
                "messages_processed": agent._message_count,
                "errors": agent._error_count,
                "running": agent._running,
            }
            for agent_type, agent in lifecycle.agents.items()
        ],
        "count": len(lifecycle.agents),
    }


# ── Herramientas ─────────────────────────────────────────

@router.get("/tools")
async def list_tools(category: str | None = Query(None)):
    """Lista las herramientas disponibles."""
    if category:
        tools = tool_registry.list_by_category(category)
    else:
        tools = tool_registry.list_tools()
    return {"tools": tools, "count": len(tools)}


@router.post("/tools/{tool_name}/execute")
async def execute_tool(tool_name: str, params: dict[str, Any] = {}, task_id: str | None = None):
    """Ejecuta una herramienta directamente."""
    result = await tool_registry.execute(
        tool_name=tool_name,
        params=params,
        task_id=task_id or "direct",
    )
    return result


# ── Chat ─────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Chat con ARIA. Convierte texto en ejecución de tareas multi-agente.
    """
    import time
    start = time.time()

    # Crear tarea de tipo "custom" con el mensaje como input
    task_id = await lifecycle.create_task(
        task_type="custom",
        title=req.message[:100],
        input_data={"message": req.message},
        session_id=req.session_id,
    )

    # Esperar resultado (con timeout)
    timeout = 30.0
    elapsed = 0.0
    result_text = "Procesando..."

    while elapsed < timeout:
        status = lifecycle.get_task_status(task_id)
        if status and status.get("status") == "completed":
            result_data = status.get("result", [])
            result_text = str(result_data[-1].get("output", {}).get("output_text", "Completado")) if result_data else "Completado"
            break
        elif status and status.get("status") == "failed":
            result_text = f"Error: {status.get('error', 'Desconocido')}"
            break
        await asyncio.sleep(0.5)
        elapsed += 0.5

    execution_time_ms = int((time.time() - start) * 1000)

    return ChatResponse(
        reply=result_text,
        task_id=task_id,
        execution_time_ms=execution_time_ms,
    )


# ── Estado del Sistema ───────────────────────────────────

@router.get("/system/status")
async def system_status():
    """Estado completo del sistema."""
    return {
        "lifecycle": lifecycle.stats,
        "sandbox": sandbox.stats if sandbox else {"status": "unavailable"},
        "browser": browser.stats if browser else {"status": "unavailable"},
        "tools": tool_registry.list_tools(),
    }