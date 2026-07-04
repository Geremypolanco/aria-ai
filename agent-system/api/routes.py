"""
ARIA Agent System — API Routes (REST endpoints).
Implementación completa en Fase 5.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from api.models import TaskCreateRequest, TaskResponse, TaskListResponse

router = APIRouter(prefix="/api/v1", tags=["Tasks"])


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(req: TaskCreateRequest):
    """
    Crea una nueva tarea.
    El PlannerAgent recogerá la tarea y generará un plan.
    """
    raise HTTPException(status_code=501, detail="Fase 5: endpoint no implementado")


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(page: int = 1, page_size: int = 20, status: str | None = None):
    """Lista tareas con paginación y filtro opcional por estado."""
    raise HTTPException(status_code=501, detail="Fase 5: endpoint no implementado")


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """Obtiene una tarea por ID."""
    raise HTTPException(status_code=501, detail="Fase 5: endpoint no implementado")


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancela una tarea en ejecución."""
    raise HTTPException(status_code=501, detail="Fase 5: endpoint no implementado")
