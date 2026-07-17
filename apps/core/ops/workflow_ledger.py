"""
workflow_ledger.py — Registro de ejecuciones de Flujos Dinámicos.

Cada Deep Workflow que termina se registra aquí (objetivo, nº de subagentes,
verificados/reparados, tokens, duración). Da al usuario **observabilidad de su
uso** — como los paneles de consumo de las IA frontera — y es el cimiento del
modelo "cobra por resultado": los `deliverables` (flujos completados) son la
unidad de valor, no los tokens.

Almacenamiento: en memoria (anillo acotado por usuario). Un proceso Fly = un
registro; suficiente para el panel. Si en el futuro se necesita persistencia
multi-instancia, este es el punto único donde enchufar Redis/DB.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Cuántas ejecuciones recientes se conservan por usuario.
MAX_RUNS_PER_USER = 100


@dataclass
class WorkflowRun:
    goal: str
    subtasks: int
    verified: int
    repaired: int
    tokens: int
    duration_ms: int
    ok: bool
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "subtasks": self.subtasks,
            "verified": self.verified,
            "repaired": self.repaired,
            "tokens": self.tokens,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "ts": self.ts,
        }


class WorkflowLedger:
    """Registro thread-safe de ejecuciones de flujos, por usuario."""

    def __init__(self) -> None:
        self._runs: dict[str, deque[WorkflowRun]] = defaultdict(
            lambda: deque(maxlen=MAX_RUNS_PER_USER)
        )
        self._lock = threading.Lock()

    def record(
        self,
        email: str,
        *,
        goal: str,
        subtasks: int,
        verified: int,
        repaired: int,
        tokens: int,
        duration_ms: int,
        ok: bool,
    ) -> None:
        """Registra un flujo terminado. Nunca lanza — la contabilidad jamás debe
        romper la petición que la invoca."""
        key = (email or "anon").strip().lower()
        run = WorkflowRun(
            goal=(goal or "").strip()[:160],
            subtasks=max(0, int(subtasks)),
            verified=max(0, int(verified)),
            repaired=max(0, int(repaired)),
            tokens=max(0, int(tokens)),
            duration_ms=max(0, int(duration_ms)),
            ok=bool(ok),
        )
        with self._lock:
            self._runs[key].appendleft(run)

    def recent(self, email: str, limit: int = 10) -> list[dict[str, Any]]:
        key = (email or "anon").strip().lower()
        with self._lock:
            runs = list(self._runs.get(key, ()))[: max(1, limit)]
        return [r.to_dict() for r in runs]

    def stats(self, email: str) -> dict[str, Any]:
        """Agregados de por vida para el usuario (lo que ARIA ha entregado)."""
        key = (email or "anon").strip().lower()
        with self._lock:
            runs = list(self._runs.get(key, ()))
        total = len(runs)
        subagents = sum(r.subtasks for r in runs)
        verified = sum(r.verified for r in runs)
        tokens = sum(r.tokens for r in runs)
        completed = sum(1 for r in runs if r.ok)
        verify_rate = round(verified / subagents * 100) if subagents else 0
        return {
            "deliverables": completed,  # flujos completados = unidad de "cobro por resultado"
            "workflows": total,
            "subagents": subagents,
            "verified": verified,
            "verify_rate_pct": verify_rate,
            "tokens": tokens,
        }


_ledger: WorkflowLedger | None = None


def get_workflow_ledger() -> WorkflowLedger:
    global _ledger
    if _ledger is None:
        _ledger = WorkflowLedger()
    return _ledger
