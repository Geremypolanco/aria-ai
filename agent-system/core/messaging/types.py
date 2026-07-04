"""
ARIA Agent System — Tipos de mensajes para el Message Bus.
Todos los mensajes entre agentes usan estos tipos Pydantic para validación.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    """Tipos de mensajes del bus."""

    # Gestión del ciclo de vida de tareas
    TASK_CREATED = "task.created"
    TASK_ASSIGNED = "task.assigned"
    TASK_PLANNED = "task.planned"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_NEEDS_REVIEW = "task.needs_review"

    # Comunicación entre agentes
    PLAN_GENERATED = "plan.generated"
    STEP_EXECUTED = "step.executed"
    STEP_FAILED = "step.failed"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"

    # Logs y monitoreo
    LOG_MESSAGE = "log.message"
    AGENT_HEARTBEAT = "agent.heartbeat"
    AGENT_ERROR = "agent.error"

    # Comandos del sistema
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_PAUSE = "system.pause"
    SYSTEM_RESUME = "system.resume"


class AgentType(StrEnum):
    PLANNER = "planner"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    ORCHESTRATOR = "orchestrator"


class MessagePriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SecurityMetadata(BaseModel):
    """Metadatos de seguridad adjuntos a cada mensaje."""
    vault_token_accessor: str | None = Field(default=None, description="Accessor del token Vault usado")
    user_id: str | None = Field(default=None, description="ID del usuario que originó la acción")
    session_id: str | None = Field(default=None, description="ID de sesión")
    client_ip: str | None = Field(default=None, description="IP del cliente")
    user_agent: str | None = Field(default=None, description="User agent del cliente")


class StepResult(BaseModel):
    """Resultado de un paso individual de ejecución."""
    step: int = Field(..., description="Número de paso")
    action: str = Field(..., description="Nombre de la acción ejecutada")
    status: str = Field(default="success", description="success | failed | skipped")
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = Field(default=None)
    error: str | None = Field(default=None)
    duration_ms: int = Field(default=0)
    security_metadata: SecurityMetadata | None = Field(default=None)


class Plan(BaseModel):
    """Plan generado por PlannerAgent."""
    task_id: str = Field(..., description="ID de la tarea")
    steps: list[dict[str, Any]] = Field(
        ...,
        description="Lista de pasos del plan. Cada paso tiene: tool, params, expected_output",
        min_length=1,
    )
    estimated_duration_seconds: int = Field(default=60)
    fallback_strategy: str | None = Field(
        default=None,
        description="Estrategia alternativa si falla",
    )


class AgentMessage(BaseModel):
    """Mensaje estándar del bus entre agentes."""
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    type: MessageType
    source: AgentType
    target: AgentType | None = Field(default=None, description="None = broadcast")
    priority: MessagePriority = MessagePriority.NORMAL

    # Payload
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    # Metadatos
    correlation_id: str | None = Field(
        default=None,
        description="ID para correlacionar mensajes relacionados",
    )
    security: SecurityMetadata | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ttl_seconds: int | None = Field(default=300, description="Tiempo de vida del mensaje")

    def is_expired(self) -> bool:
        """Verifica si el mensaje ha expirado."""
        if self.ttl_seconds is None:
            return False
        age = (datetime.utcnow() - self.timestamp).total_seconds()
        return age > self.ttl_seconds


class TaskEvent(BaseModel):
    """Evento de cambio de estado de tarea para WebSocket."""
    task_id: str
    status: str
    agent_type: AgentType | None = None
    step: int | None = None
    action: str | None = None
    message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
