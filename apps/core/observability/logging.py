"""
Structured JSON logging with OpenTelemetry trace correlation.

Every log record automatically includes:
  - trace_id and span_id from the active OTel span
  - component name (logger name)
  - environment
  - timestamp (ISO 8601 UTC)

In production the handler emits minified JSON.
In development it emits human-readable colored output.

Usage:
    from apps.core.observability.logging import get_logger
    log = get_logger(__name__)
    log.info("Income cycle completed", extra={"strategy": "content_pipeline", "revenue": 42.0})
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any


class _TraceInjectingFilter(logging.Filter):
    """Injects OTel trace/span IDs into every LogRecord as extra fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from apps.core.observability.tracing import get_span_id, get_trace_id

            record.trace_id = get_trace_id()
            record.span_id = get_span_id()
        except Exception:
            record.trace_id = ""
            record.span_id = ""
        return True


class _JSONFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Output fields:
      ts, level, logger, message, trace_id, span_id, env
      + any extras added via record.__dict__
    """

    _SKIP_FIELDS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "trace_id": getattr(record, "trace_id", ""),
            "span_id": getattr(record, "span_id", ""),
            "env": os.getenv("ENVIRONMENT", "production"),
        }

        # Merge extra fields
        for key, value in record.__dict__.items():
            if key not in self._SKIP_FIELDS and not key.startswith("_"):
                try:
                    json.dumps(value)  # only include JSON-serializable values
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"))


class _DevFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    COLORS = {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        trace_id = getattr(record, "trace_id", "")
        trace_suffix = f" [{trace_id[:8]}]" if trace_id else ""
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return (
            f"{color}{record.levelname:8}{self.RESET} "
            f"\033[2m{record.name}{trace_suffix}\033[0m "
            f"{msg}"
        )


# ── Setup ──────────────────────────────────────────────────────────────────

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """
    Configure the root logging pipeline.

    Call once at application startup. Subsequent calls are no-ops.
    Uses JSON format in production, colored text in development.
    """
    global _configured
    if _configured:
        return
    _configured = True

    env = os.getenv("ENVIRONMENT", "production")
    is_prod = env == "production"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove default handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_TraceInjectingFilter())
    handler.setFormatter(_JSONFormatter() if is_prod else _DevFormatter())
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger pre-wired with ARIA's structured log pipeline.

    Idempotent — safe to call at module level.
    """
    configure_logging()
    return logging.getLogger(name)
