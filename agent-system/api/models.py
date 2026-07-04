"""
ARIA Agent System — API Models (Pydantic schemas).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TaskCreateRequest(BaseModel):
    """Request para crear una nueva tarea."""
    task_type: str = Field(..., description="Tipo de tarea (browser, terminal, research, custom)")
    title: str = Field(default="", max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=3, ge=0, le=10)
    session_id: str | None = None

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, v: str) -> str:
        allowed = {"browser", "terminal", "research", "custom", "extract", "monitor"}
        if v not in allowed:
            raise ValueError(f"task_type debe ser uno de: {allowed}")
        return v


class TaskResponse(BaseModel):
    """Respuesta con información de una tarea."""
    id: str
    status: str
    task_type: str
    title: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class TaskListResponse(BaseModel):
    """Lista paginada de tareas."""
    tasks: list[TaskResponse]
    total: int
    page: int
    page_size: int


class ChatRequest(BaseModel):
    """Request para chat con el agente."""
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: str | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    """Respuesta del chat."""
    reply: str
    task_id: str | None = None
    execution_time_ms: int = 0
