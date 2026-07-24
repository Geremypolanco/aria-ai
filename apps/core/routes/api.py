"""
Shared in-memory activity log used by a few background tools
(apps/core/tools/deep_think.py, apps/core/tools/task_manager.py).

The REST API surface this module used to define was a superseded, never-
mounted duplicate of the live routes in apps/core/main.py (chat, workflow,
status, run, billing, connectors, etc.) — main.py owns all of that now.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

_activity_log: deque = deque(maxlen=200)


def _log_activity(level: str, message: str, category: str = "info") -> None:
    _activity_log.append(
        {
            "ts": datetime.utcnow().isoformat(),
            "level": level,
            "category": category,
            "message": message,
        }
    )
