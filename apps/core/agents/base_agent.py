"""
BaseAgent — Clase base para todos los agentes de Aria AI.

Principio fundamental: ARIA nunca simula. Si no puede realizar una acción
porque le falta una API key o un servicio, lo declara explícitamente.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
    Clase base para todos los agentes de Aria AI.
    Politica: ningun metodo retorna datos falsos o simulados.
    Si falta una API key o servicio, se retorna error explicito.
    """

    APPROVAL_THRESHOLD_USD: float = float(
        getattr(settings, "MAX_SPEND_WITHOUT_APPROVAL_USD", 0.0)
    )
    REQUIRE_APPROVAL_FOR_PAYMENTS: bool = True

    # Mapa global: nombre_capacidad -> env_var requerida
    CAPABILITY_ENV_MAP: dict[str, str] = {
        "gumroad": "GUMROAD_TOKEN",
        "stripe": "STRIPE_SECRET_KEY",
        "paypal": "PAYPAL_CLIENT_ID",
        "shopify": "SHOPIFY_URL",
        "mailchimp": "MAILCHIMP_API_KEY",
        "buffer": "BUFFER_TOKEN",
        "google": "GOOGLE_API_KEY",
        "youtube": "GOOGLE_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "pexels": "PEXELS_API_KEY",
        "cloudinary": "CLOUDINARY_CLOUD_NAME",
        "canva": "CANVA_CLIENT_ID",
        "airtable": "AIRTABLE_TOKEN",
        "news": "NEWS_API_KEY",
        "serp": "SERP_API_KEY",
        "telegram": "TELEGRAM_TOKEN",
        "github": "GITHUB_TOKEN",
        "huggingface": "HF_TOKEN",
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "supabase": "SUPABASE_URL",
        "redis": "UPSTASH_REDIS_REST_URL",
        "medium": "MEDIUM_TOKEN",
        "devto": "DEVTO_API_KEY",
        "hashnode": "HASHNODE_TOKEN",
        "amazon": "AMAZON_ASSOCIATE_TAG",
        "affiliate": "AMAZON_ASSOCIATE_TAG",
        "notion": "NOTION_TOKEN",
        "vercel": "VERCEL_TOKEN",
        "meta_ads": "FACEBOOK_MARKETING_TOKEN",
        "gmail": "GOOGLE_API_KEY",
        "calendar": "GOOGLE_API_KEY",
        "drive": "GOOGLE_API_KEY",
    }

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
        await self._register_in_supabase()
        logger.info("[%s] Agente listo", self.name)

    async def stop(self) -> None:
        await self._http.aclose()
        logger.info("[%s] Agente detenido", self.name)

    # ── EJECUCIÓN PRINCIPAL ───────────────────────────────

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Punto de entrada principal con circuit breaker."""
        if not self._is_circuit_available():
            wait_secs = int(self._circuit_open_until - time.monotonic())
            return {
                "success": False,
                "error": (
                    f"{self.name}: circuit breaker abierto — demasiados fallos consecutivos. "
                    f"Vuelve a intentar en ~{wait_secs}s."
                ),
                "circuit_open": True,
            }

        self.metrics.tasks_attempted += 1
        start_ts = time.monotonic()
        try:
            result = await self._execute(context)
            elapsed_ms = int((time.monotonic() - start_ts) * 1000)
            if result.get("success", False):
                self.metrics.tasks_succeeded += 1
                self.metrics.total_latency_ms += elapsed_ms
                self._consecutive_failures = 0
                if rev := result.get("revenue_generated"):
                    self.metrics.revenue_generated += rev
            else:
                self.metrics.tasks_failed += 1
                self._consecutive_failures += 1
                self._check_circuit_breaker()
                logger.warning("[%s] Tarea fallida: %s", self.name, result.get("error", "sin detalle"))
            result["agent_metrics"] = {
                "tasks_attempted": self.metrics.tasks_attempted,
                "success_rate": self.metrics.success_rate,
                "avg_latency_ms": self.metrics.avg_latency_ms,
            }
            return result
        except Exception as exc:
            self.metrics.tasks_failed += 1
            self._consecutive_failures += 1
            self._check_circuit_breaker()
            logger.error("[%s] Excepcion en _execute: %s", self.name, exc, exc_info=True)
            return {"success": False, "error": str(exc), "agent": self.name}

    @abstractmethod
    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Implementar en cada agente concreto."""

    # ── CAPABILITY CHECK ──────────────────────────────────

    def check_capabilities(self) -> dict[str, Any]:
        """
        Verifica en tiempo real que puede y que NO puede hacer este agente.
        Nunca simula — reporta el estado real de cada dependencia de API.
        Llamar desde Telegram con /agentes para ver estado completo.
        """
        available: list[str] = []
        unavailable: list[str] = []

        for cap in self.capabilities:
            cap_lower = cap.lower()
            required_env: Optional[str] = None
            for keyword, env_var in self.CAPABILITY_ENV_MAP.items():
                if keyword in cap_lower:
                    required_env = env_var
                    break

            if required_env:
                val = getattr(settings, required_env, None)
                if val:
                    available.append(cap)
                else:
                    unavailable.append(f"{cap} [requiere {required_env}]")
            else:
                # Capacidad sin dependencia externa (ej: planificacion, IA base)
                available.append(cap)

        return {
            "agent": self.name,
            "description": self.description,
            "available": available,
            "unavailable": unavailable,
            "fully_operational": len(unavailable) == 0,
            "operational_pct": round(len(available) / max(len(self.capabilities), 1) * 100),
        }

    # ── PENSAMIENTO CON IA ────────────────────────────────

    async def think(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.FAST,
        json_mode: bool = False,
        max_tokens: int = 2000,
    ) -> Optional[str]:
        """
        Llama a la IA y retorna texto.
        Retorna None si la IA no esta disponible — el agente debe manejar None.
        """
        try:
            ai = await get_ai_client()
            response = await ai.complete(
                system=system,
                user=user,
                model=model,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )
            if response and response.success:
                return response.content if isinstance(response.content, str) else str(response.content)
            logger.warning("[%s] think() sin respuesta de IA — proveedor no disponible", self.name)
            return None
        except Exception as exc:
            logger.error("[%s] think() error: %s", self.name, exc)
            return None

    # ── APROBACIÓN HUMANA ─────────────────────────────────

    async def request_human_approval(
        self,
        action: str,
        details: str,
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """
        Solicita aprobacion del supervisor via Telegram.
        ERROR EXPLICITO si Telegram no esta configurado — nunca aprueba automaticamente.
        """
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return {
                "success": False,
                "error": (
                    "Aprobacion humana requerida pero TELEGRAM_TOKEN o TELEGRAM_CHAT_ID "
                    "no estan configurados. Accion bloqueada por seguridad."
                ),
                "action_blocked": True,
            }
        try:
            db = _get_db()
            approval_id = str(uuid.uuid4())[:8]
            db.table("approvals").insert({
                "id": approval_id,
                "agent": self.name,
                "action": action,
                "details": details,
                "amount_usd": amount_usd,
                "status": "pending",
            }).execute()

            msg = (
                f"⚠️ <b>Aprobacion requerida</b>\n\n"
                f"<b>Agente:</b> {self.name}\n"
                f"<b>Accion:</b> {action}\n"
                f"<b>Detalles:</b> {details}\n"
                + (f"<b>Monto:</b> ${amount_usd:.2f}\n" if amount_usd > 0 else "")
                + f"\n<b>ID:</b> <code>{approval_id}</code>\n\n"
                f"/aprobar {approval_id}  |  /rechazar {approval_id}"
            )
            await self._send_telegram(msg)
            return {
                "success": True,
                "approval_id": approval_id,
                "status": "pending",
                "message": f"Aprobacion solicitada al supervisor (ID: {approval_id})",
            }
        except Exception as exc:
            logger.error("[%s] request_approval error: %s", self.name, exc)
            return {"success": False, "error": str(exc)}

    async def execute_with_approval(
        self,
        action: str,
        details: str,
        fn: Callable[[], Coroutine],
        amount_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Ejecuta fn() directamente o solicita aprobacion segun el monto."""
        if amount_usd <= self.APPROVAL_THRESHOLD_USD and not self.REQUIRE_APPROVAL_FOR_PAYMENTS:
            return await fn()
        return await self.request_human_approval(action, details, amount_usd)

    # ── SUPABASE / LOGGING ────────────────────────────────

    async def _register_in_supabase(self) -> None:
        try:
            db = _get_db()
            db.table("agents").upsert({
                "name": self.name,
                "description": self.description,
                "capabilities": self.capabilities,
                "status": "active",
                "agent_id": self.agent_id,
            }).execute()
        except Exception as exc:
            logger.warning("[%s] No se pudo registrar en Supabase: %s", self.name, exc)

    async def _log(self, event: str, message: str, metadata: Optional[dict] = None) -> None:
        try:
            db = _get_db()
            db.table("system_logs").insert({
                "agent": self.name,
                "event": event,
                "message": message,
                "metadata": metadata or {},
            }).execute()
        except Exception as exc:
            logger.debug("[%s] _log error (no critico): %s", self.name, exc)

    # ── TELEGRAM ──────────────────────────────────────────

    async def _send_telegram(self, message: str) -> bool:
        """Envia mensaje Telegram. Retorna False (no excepcion) si no esta configurado."""
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.warning("[%s] Telegram no configurado — mensaje no enviado", self.name)
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{TELEGRAM_API}{settings.TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                return res.status_code == 200
        except Exception as exc:
            logger.error("[%s] Telegram error: %s", self.name, exc)
            return False

    # ── CIRCUIT BREAKER ───────────────────────────────────

    def _is_circuit_available(self) -> bool:
        if not self._circuit_open:
            return True
        if time.monotonic() > self._circuit_open_until:
            self._circuit_open = False
            self._consecutive_failures = 0
            logger.info("[%s] Circuit breaker cerrado — reiniciando", self.name)
            return True
        return False

    def _check_circuit_breaker(self) -> None:
        if self._consecutive_failures >= 5:
            cooldown = min(300, 60 * self._consecutive_failures)
            self._circuit_open = True
            self._circuit_open_until = time.monotonic() + cooldown
            logger.error(
                "[%s] Circuit breaker ABIERTO por %ds (%d fallos consecutivos)",
                self.name, cooldown, self._consecutive_failures,
            )


def _get_db():
    """Helper para obtener cliente Supabase."""
    from apps.core.memory.supabase_client import AriaDatabase
    return AriaDatabase()._client
