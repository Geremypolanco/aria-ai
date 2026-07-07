"""
ARIA Agent System — Structured JSON Logger.
Logs en formato JSON con correlation_id a través de todo el flujo.
Cada entrada incluye: timestamp, level, service, trace_id, correlation_id, agent, action.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from observability.config import obs_settings

# ── Contexto por request/tarea ──────────────────────────
# Usamos ContextVars para propagar correlation_id sin pasarlo explícitamente
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_task_id: ContextVar[str] = ContextVar("task_id", default="")
_agent_type: ContextVar[str] = ContextVar("agent_type", default="")


def set_correlation_id(corr_id: str) -> None:
    """Establece el correlation_id para el contexto actual."""
    _correlation_id.set(corr_id)


def set_task_context(task_id: str, agent_type: str = "") -> None:
    """Establece el contexto de la tarea actual."""
    _task_id.set(task_id)
    if agent_type:
        _agent_type.set(agent_type)


def get_correlation_id() -> str:
    """Obtiene el correlation_id del contexto actual."""
    return _correlation_id.get()


class JSONFormatter(logging.Formatter):
    """
    Formatea logs como JSON estructurado.
    
    Formato de salida:
    {
        "timestamp": "2026-07-04T12:00:00.000Z",
        "level": "INFO",
        "service": "aria-agent-system",
        "logger": "aria.agent.planner",
        "message": "...",
        "correlation_id": "corr-...",
        "task_id": "...",
        "agent_type": "planner",
        "extra": { ... }
    }
    """

    def __init__(self):
        super().__init__()
        self._service_name = obs_settings.SERVICE_NAME

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self._service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Correlation ID del contexto
        corr_id = _correlation_id.get()
        if corr_id:
            log_entry["correlation_id"] = corr_id

        # Task ID del contexto
        task_id = _task_id.get()
        if task_id:
            log_entry["task_id"] = task_id

        # Agent type del contexto
        agent_type = _agent_type.get()
        if agent_type:
            log_entry["agent_type"] = agent_type

        # Excepción
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Extra fields (si el log los incluye)
        extra = {}
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "levelname", "levelno", "lineno",
                "module", "msecs", "message", "msg", "name", "pathname",
                "process", "processName", "relativeCreated", "stack_info",
                "thread", "threadName",
            ):
                extra[key] = value

        if extra:
            log_entry["extra"] = extra

        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """
    Configura el logging estructurado JSON.

    - Logs a stdout en formato JSON
    - Opcionalmente a archivo con rotación
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(obs_settings.LOG_LEVEL)

    # Limpiar handlers existentes
    root_logger.handlers.clear()

    # Handler a stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(stdout_handler)

    # Handler opcional a archivo
    if obs_settings.LOG_FILE:
        try:
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(
                obs_settings.LOG_FILE,
                maxBytes=obs_settings.LOG_FILE_MAX_SIZE,
                backupCount=obs_settings.LOG_FILE_BACKUP_COUNT,
            )
            file_handler.setFormatter(JSONFormatter())
            root_logger.addHandler(file_handler)
        except Exception as e:
            root_logger.warning("No se pudo crear archivo de log: %s", e)

    # Silenciar logs ruidosos de librerías
    for noisy_logger in ("httpx", "docker", "urllib3", "asyncio"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    logging.getLogger("aria").info(
        "Logging estructurado JSON configurado (level=%s)",
        obs_settings.LOG_LEVEL,
    )