"""
ARIA Agent System — Prometheus Metrics.
Expone métricas del sistema multi-agente para scraping por Prometheus.
"""
from __future__ import annotations

import time
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from observability.config import obs_settings

logger = __import__("logging").getLogger("aria.observability.metrics")

# ── Contadores ─────────────────────────────────────────

# Tareas
tasks_created = Counter(
    "aria_tasks_created_total",
    "Total de tareas creadas",
    ["task_type", "source"],
)
tasks_completed = Counter(
    "aria_tasks_completed_total",
    "Total de tareas completadas exitosamente",
    ["task_type"],
)
tasks_failed = Counter(
    "aria_tasks_failed_total",
    "Total de tareas fallidas",
    ["task_type", "error_type"],
)
tasks_retried = Counter(
    "aria_tasks_retried_total",
    "Total de reintentos de tareas",
    ["task_type"],
)

# Agentes
agent_messages = Counter(
    "aria_agent_messages_total",
    "Total de mensajes procesados por agente",
    ["agent_type"],
)
agent_errors = Counter(
    "aria_agent_errors_total",
    "Total de errores por agente",
    ["agent_type", "error_type"],
)

# Herramientas
tool_executions = Counter(
    "aria_tool_executions_total",
    "Total de ejecuciones de herramientas",
    ["tool_name", "status"],
)

# WebSocket
ws_connections = Counter(
    "aria_ws_connections_total",
    "Total de conexiones WebSocket",
    ["session_id"],
)

# ── Histogramas ─────────────────────────────────────────

# Latencia de ejecución de herramientas (ms)
tool_latency = Histogram(
    "aria_tool_latency_ms",
    "Latencia de ejecución de herramientas en ms",
    ["tool_name"],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000],
)

# Latencia de pasos de agente (ms)
agent_step_latency = Histogram(
    "aria_agent_step_latency_ms",
    "Latencia de pasos de agentes en ms",
    ["agent_type", "action"],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000],
)

# Duración total de tareas (segundos)
task_duration = Histogram(
    "aria_task_duration_seconds",
    "Duración total de tareas en segundos",
    ["task_type"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800],
)

# Tamaño de payload de herramientas (bytes)
tool_payload_size = Histogram(
    "aria_tool_payload_size_bytes",
    "Tamaño del payload de herramientas",
    ["tool_name"],
    buckets=[100, 500, 1000, 5000, 10000, 50000, 100000, 500000],
)

# ── Gauges (valores actuales) ───────────────────────────

# Tareas activas
active_tasks = Gauge(
    "aria_active_tasks",
    "Número de tareas actualmente activas",
    ["status"],
)

# Contenedores activos
active_sandbox_containers = Gauge(
    "aria_active_sandbox_containers",
    "Número de contenedores sandbox activos",
)
active_browser_sessions = Gauge(
    "aria_active_browser_sessions",
    "Número de sesiones de navegador activas",
)

# Agentes
agent_uptime = Gauge(
    "aria_agent_uptime_seconds",
    "Tiempo de actividad del agente en segundos",
    ["agent_type"],
)

# Colas
queue_depth = Gauge(
    "aria_queue_depth",
    "Profundidad actual de las colas de mensajes",
    ["queue_name"],
)

# Conexiones WebSocket
active_ws_connections = Gauge(
    "aria_active_ws_connections",
    "Conexiones WebSocket activas",
)

# Memoria del sistema
system_memory_usage = Gauge(
    "aria_system_memory_usage_bytes",
    "Uso de memoria del sistema",
    ["component"],
)
system_cpu_usage = Gauge(
    "aria_system_cpu_usage_percent",
    "Uso de CPU del sistema",
    ["component"],
)

# Pool de base de datos
db_pool_size = Gauge(
    "aria_db_pool_size",
    "Tamaño del pool de conexiones de base de datos",
    ["state"],
)


def start_metrics_server() -> None:
    """Arranca el servidor HTTP de métricas Prometheus."""
    try:
        start_http_server(obs_settings.METRICS_PORT)
        logger.info(
            "Métricas Prometheus disponibles en :%d%s",
            obs_settings.METRICS_PORT,
            obs_settings.METRICS_PATH,
        )
    except Exception as e:
        logger.warning("No se pudo iniciar servidor de métricas: %s", e)


def record_tool_execution(
    tool_name: str,
    duration_ms: float,
    status: str = "success",
    payload_size: int = 0,
) -> None:
    """Registra la ejecución de una herramienta."""
    tool_executions.labels(tool_name=tool_name, status=status).inc()
    tool_latency.labels(tool_name=tool_name).observe(duration_ms)
    if payload_size > 0:
        tool_payload_size.labels(tool_name=tool_name).observe(payload_size)


def record_agent_step(
    agent_type: str,
    action: str,
    duration_ms: float,
    success: bool = True,
) -> None:
    """Registra un paso de agente."""
    agent_messages.labels(agent_type=agent_type).inc()
    agent_step_latency.labels(agent_type=agent_type, action=action).observe(duration_ms)
    if not success:
        agent_errors.labels(agent_type=agent_type, error_type=action).inc()


def record_task_created(task_type: str, source: str = "api") -> None:
    """Registra creación de tarea."""
    tasks_created.labels(task_type=task_type, source=source).inc()
    active_tasks.labels(status="pending").inc()


def record_task_completed(task_type: str, duration_seconds: float) -> None:
    """Registra tarea completada."""
    tasks_completed.labels(task_type=task_type).inc()
    task_duration.labels(task_type=task_type).observe(duration_seconds)
    active_tasks.labels(status="pending").dec()


def record_task_failed(task_type: str, error_type: str = "unknown") -> None:
    """Registra tarea fallida."""
    tasks_failed.labels(task_type=task_type, error_type=error_type).inc()
    active_tasks.labels(status="failed").dec()


def update_agent_stats(agent_type: str, uptime: float) -> None:
    """Actualiza estadísticas de agente."""
    agent_uptime.labels(agent_type=agent_type).set(uptime)


def update_sandbox_stats(containers: int, sessions: int) -> None:
    """Actualiza estadísticas de contenedores."""
    active_sandbox_containers.set(containers)
    active_browser_sessions.set(sessions)