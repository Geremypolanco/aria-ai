"""
BaseAgent — Clase base para todos los agentes de Aria AI.

Funcionalidades:
- Registro automático en Supabase
- Sistema de aprobación humana via Telegram
- Circuit breaker por agente
- Métricas de rendimiento
- Heartbeat en Redis
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

import httpx

from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.base_agent")

TELEGRAM_API = "https://api.telegram.org/bot"


@dataclass
class AgentMetrics:
    tasks_attempted: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    total_latency_ms: int = 0
    revenue_generated: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.tasks_attempted == 0:
            return 100.0
        return round(self.tasks_succeeded / self.tasks_attempted * 100, 1)

    @property
    def avg_latency_ms(self) -> int:
        if self.tasks_succeeded == 0:
            return 0
        return self.total_latency_ms // self.tasks_succeeded


class BaseAgent(ABC):
    """
    Clase base para todos los agentes especializados de Aria AI.
    Cada agente hereda de esta clase obligatoriamente.
    """

    # Límite de gasto sin aprobación (0 = siempre pide aprobación para pagos)
    APPROVAL_THRESHOLD_USD: float = float(
        settings.MAX_SPEND_WITHOUT_APPROVAL_USD
        if hasattr(settings, "MAX_SPEND_WITHOUT_APPROVAL_USD")
        else 0.0
    )
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True

    def __init__(self, name: str, description: str, capabilities: list[str]) -> None:
        self.name = name
        self.description = description
        self.capabilities = capabilities
        self.agent_id = str(uuid.uuid4())
        self.metrics = AgentMetrics()
        self._http = httpx.AsyncClient(timeout=15.0)
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_open_until: float = 0.0
        logger.info("[%s] Agente inicializado", self.name)

    # ── CICLO DE VIDA ─────────────────────────────────────

    async def start(self) -> None:
        """Registra el agente y arranca el heartbeat."""
        await self._register_in_supabase()
        logger.info("[%s] Agente listo", self.name)

    async def stop(self) -> None:
        """Cierra conexiones y libera recursos."""
        await self._http.aclose()
        logger.info("[%s] Agente detenido", self.name)

    # ── EJECUCIÓN PRINCIPAL ───────────────────────────────

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Punto de entrada principal. Aplica circuit breaker antes de ejecutar.
        Sobreescribir _execute() en cada agente concreto.
        """
        if not self._is_circuit_available():
            return {"success": False, "error": f"{self.name} circuit breaker abierto"}

        t0 = time.time()
        self.metrics.tasks_attempted += 1
        await self._set_heartbeat("running")

        try:
            result = await self._execute(context)
            latency = int((time.time() - t0) * 1000)
            self.metrics.tasks_succeeded += 1
            self.metrics.total_latency_ms += latency
            self._consecutive_failures = 0
            self._circuit_open = False
            await self._log("task_completed", str(result)[:500], "success")
            await self._set_heartbeat("idle")
            return result

        except Exception as exc:
            latency = int((time.time() - t0) * 1000)
            self.metrics.tasks_failed += 1
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._circuit_open = True
                self._circuit_open_until = time.time() + 120.0
                logger.warning("[%s] Circuit breaker ABIERTO", self.name)
            await self._log("task_failed", str(exc)[:500], "error")
            await self._set_heartbeat("error")
            logger.error("[%s] Error en ejecución: %s", self.name, exc)
            return {"success": False, "error": str(exc)}

    @abstractmethod
    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Implementación concreta de cada agente."""
        ...

    # ── APROBACIÓN HUMANA ─────────────────────────────────

    async def request_approval(
        self,
        action: str,
        details: str,
        amount_usd: float = 0.0,
        timeout_seconds: int = 300,
    ) -> bool:
        """
        Solicita aprobación al supervisor via Telegram.
        Devuelve True si aprobado, False si rechazado o timeout.
        """
        if not self.REQUIRE_APPROVAL_FOR_PAYMENTS and amount_usd == 0.0:
            return True
        if amount_usd <= self.APPROVAL_THRESHOLD_USD and amount_usd == 0.0:
            return True

        approval_id = str(uuid.uuid4())[:8]
        message = (
            f"🤖 <b>ARIA — APROBACIÓN REQUERIDA</b>\n\n"
            f"<b>Agente:</b> {self.name}\n"
            f"<b>Acción:</b> {action}\n"
            f"<b>Detalles:</b> {details[:300]}\n"
            f"<b>Costo estimado:</b> ${amount_usd:.2f} USD\n"
            f"<b>ID:</b> <code>{approval_id}</code>\n\n"
            f"Responde con:\n"
            f"✅ <code>APROBAR {approval_id}</code>\n"
            f"❌ <code>RECHAZAR {approval_id}</code>"
        )
        await self._send_telegram(message)

        # Guardar en cola de aprobaciones en Supabase
        await self._create_approval_record(approval_id, action, details, amount_usd)

        # Polling de la respuesta
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = await self._check_approval_status(approval_id)
            if status == "approved":
                logger.info("[%s] Aprobación %s: APROBADA", self.name, approval_id)
                return True
            if status == "rejected":
                logger.info("[%s] Aprobación %s: RECHAZADA", self.name, approval_id)
                return False
            await asyncio.sleep(10)

        logger.warning("[%s] Aprobación %s: TIMEOUT", self.name, approval_id)
        await self._send_telegram(
            f"⏱ <b>TIMEOUT</b> — Aprobación <code>{approval_id}</code> expiró sin respuesta."
        )
        return False

    async def execute_with_approval(
        self,
        action: str,
        details: str,
        fn: Callable[[], Coroutine[Any, Any, Any]],
        amount_usd: float = 0.0,
    ) -> Any:
        """Ejecuta fn() solo si el supervisor aprueba."""
        approved = await self.request_approval(action, details, amount_usd)
        if not approved:
            raise PermissionError(f"Acción '{action}' rechazada por el supervisor")
        return await fn()

    # ── IA ────────────────────────────────────────────────

    async def think(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.STRATEGY,
        json_mode: bool = False,
    ) -> Any:
        """Wrapper de conveniencia sobre el cliente de IA."""
        ai = await get_ai_client()
        if json_mode:
            return await ai.complete_json(
                system=system, user=user, model=model, agent_name=self.name
            )
        response = await ai.complete(
            system=system, user=user, model=model, agent_name=self.name
        )
        return response.content if response.success else None

    # ── SUPABASE ──────────────────────────────────────────

    async def _register_in_supabase(self) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            await db.update_agent_status(self.name, "idle")
            logger.info("[%s] Registrado en Supabase", self.name)
        except Exception as exc:
            logger.warning("[%s] No se pudo registrar en Supabase: %s", self.name, exc)

    async def _log(self, action: str, message: str, level: str = "info") -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            if level == "error":
                await db.log_error(message, self.name)
            else:
                await db.log_info(f"[{action}] {message}", self.name)
        except Exception:
            pass

    async def _create_approval_record(
        self, approval_id: str, action: str, details: str, amount: float
    ) -> None:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            db._client.table("approvals").insert({
                "id": approval_id,
                "agent_name": self.name,
                "action": action,
                "details": details,
                "amount_usd": amount,
                "status": "pending",
            }).execute()
        except Exception as exc:
            logger.warning("[%s] No se pudo crear aprobación: %s", self.name, exc)

    async def _check_approval_status(self, approval_id: str) -> str:
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            result = db._client.table("approvals").select("status").eq("id", approval_id).single().execute()
            return result.data.get("status", "pending") if result.data else "pending"
        except Exception:
            return "pending"

    # ── REDIS ─────────────────────────────────────────────

    async def _set_heartbeat(self, status: str) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            cache = get_cache()
            await cache.set(f"agent:{self.name}:status", status, ttl_seconds=120)
        except Exception:
            pass

    # ── TELEGRAM ──────────────────────────────────────────

    async def _send_telegram(self, message: str) -> bool:
        try:
            res = await self._http.post(
                f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=10.0,
            )
            return res.status_code == 200
        except Exception as exc:
            logger.warning("[%s] Telegram error: %s", self.name, exc)
            return False

    # ── CIRCUIT BREAKER ───────────────────────────────────

    def _is_circuit_available(self) -> bool:
        if not self._circuit_open:
            return True
        if time.time() >= self._circuit_open_until:
            self._circuit_open = False
            self._consecutive_failures = 0
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "circuit_open": self._circuit_open,
            "metrics": {
                "tasks_attempted": self.metrics.tasks_attempted,
                "tasks_succeeded": self.metrics.tasks_succeeded,
                "tasks_failed": self.metrics.tasks_failed,
                "success_rate_pct": self.metrics.success_rate,
                "avg_latency_ms": self.metrics.avg_latency_ms,
                "revenue_generated_usd": self.metrics.revenue_generated,
            },
        }
