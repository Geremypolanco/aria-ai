"""
Aria AI — Cliente de IA con Failover Automático y Circuit Breaker
Primario:    HuggingFace Inference API (gratis)
Secundario:  Groq API (gratis, ultra rápido)
Fallback:    OpenAI (pago, último recurso)

Diseñado para Replit Free — asíncrono puro, sin estado local.
Correcciones aplicadas:
  - Circuit breaker con cooldown automático (no se queda bloqueado para siempre)
  - Timeouts por proveedor con asyncio.wait_for (HF: 25s, Groq: 10s, OAI: 15s)
  - Singleton async-safe con asyncio.Lock
  - Eliminado doble conteo de errores
  - Añadido AIModel.CREATIVE y campo attempts en AIResponse
  - Logging estructurado
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx
from groq import AsyncGroq

from apps.core.config import settings

logger = logging.getLogger("aria.ai_client")


# ── ENUMERACIONES ─────────────────────────────────────────
class AIProvider(str, Enum):
    HUGGINGFACE = "huggingface"
    GROQ = "groq"
    OPENAI = "openai"


class AIModel(str, Enum):
    STRATEGY = "strategy"    # Razonamiento profundo
    CODE = "code"            # Generación de código
    FAST = "fast"            # Respuestas rápidas
    CREATIVE = "creative"    # Contenido creativo


# ── MODELOS POR PROVEEDOR ─────────────────────────────────
MODEL_REGISTRY: dict[AIModel, dict[AIProvider, str]] = {
    AIModel.STRATEGY: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_STRATEGY,
        AIProvider.GROQ:        settings.GROQ_MODEL,
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.CODE: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_CODE,
        AIProvider.GROQ:        "llama-3.3-70b-versatile",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.FAST: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_FAST,
        AIProvider.GROQ:        "llama-3.1-8b-instant",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.CREATIVE: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_STRATEGY,
        AIProvider.GROQ:        settings.GROQ_MODEL,
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
}

# Timeouts agresivos por proveedor — evita bloquear el event loop
PROVIDER_TIMEOUTS: dict[AIProvider, float] = {
    AIProvider.HUGGINGFACE: 25.0,  # HF puede estar en cold start
    AIProvider.GROQ:        10.0,  # Groq es ultra rápido
    AIProvider.OPENAI:      15.0,
}


# ── TIPOS DE RESPUESTA ────────────────────────────────────
@dataclass
class AIResponse:
    content: str
    provider: AIProvider
    model: str
    tokens_used: int = 0
    latency_ms: int = 0
    success: bool = True
    error: Optional[str] = None
    attempts: int = 1


@dataclass
class ProviderHealth:
    """
    Circuit breaker por proveedor con cooldown automático.
    Después del cooldown el proveedor vuelve a intentarse — no se queda
    bloqueado permanentemente como en la versión anterior.
    """
    consecutive_failures: int = 0
    total_calls: int = 0
    total_errors: int = 0
    last_success_ts: float = field(default_factory=time.time)
    circuit_open: bool = False
    circuit_open_until: float = 0.0
    _break_after: int = 3
    _cooldown: float = 60.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 100.0
        return round((self.total_calls - self.total_errors) / self.total_calls * 100, 1)

    def is_available(self) -> bool:
        if not self.circuit_open:
            return True
        # Auto-reset tras el cooldown
        if time.time() >= self.circuit_open_until:
            self.circuit_open = False
            self.consecutive_failures = 0
            logger.info("Circuit breaker CERRADO — proveedor disponible de nuevo")
            return True
        return False

    def record_success(self) -> None:
        self.total_calls += 1
        self.consecutive_failures = 0
        self.circuit_open = False
        self.last_success_ts = time.time()

    def record_failure(self) -> None:
        self.total_calls += 1
        self.total_errors += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= self._break_after:
            self.circuit_open = True
            self.circuit_open_until = time.time() + self._cooldown
            logger.warning(
                "Circuit breaker ABIERTO — cooldown %.0fs",
                self._cooldown,
            )


# ── CLIENTE PRINCIPAL ─────────────────────────────────────
class AriaAIClient:
    """
    Cliente de IA con circuit breaker y failover automático.
    Stateless — seguro para Replit Free y entornos serverless.
    """

    _HF_ENDPOINT = "https://api-inference.huggingface.co/v1/chat/completions"
    _OAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self._health: dict[AIProvider, ProviderHealth] = {
            p: ProviderHealth() for p in AIProvider
        }
        self._groq = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._total_tokens = 0
        self._total_fallbacks = 0
        logger.info("AriaAIClient inicializado — HF → Groq → OpenAI")

    # ── API PÚBLICA ───────────────────────────────────────

    async def complete(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.STRATEGY,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        json_mode: bool = False,
        agent_name: str = "aria",
    ) -> AIResponse:
        """
        Ejecuta una llamada de IA con failover automático.
        Orden: HuggingFace → Groq → OpenAI
        """
        if json_mode:
            user = (
                f"{user}\n\n"
                "Responde ÚNICAMENTE con JSON válido y bien formado. "
                "Sin markdown, sin bloques de código, sin explicaciones. "
                "Solo el objeto JSON."
            )

        providers = self._get_available_providers()
        last_error: Optional[str] = None
        attempts = 0

        for provider in providers:
            attempts += 1
            try:
                response = await asyncio.wait_for(
                    self._dispatch(provider, model, system, user, max_tokens, temperature),
                    timeout=PROVIDER_TIMEOUTS[provider] + 2.0,
                )
                self._health[provider].record_success()
                response.attempts = attempts

                if json_mode:
                    response.content = self._extract_json_safe(response.content)

                logger.info(
                    "[%s] ✅ %s via %s — %dms — %d tokens",
                    agent_name, model.value, provider.value,
                    response.latency_ms, response.tokens_used,
                )
                return response

            except asyncio.TimeoutError:
                self._health[provider].record_failure()
                last_error = f"{provider.value}: timeout tras {PROVIDER_TIMEOUTS[provider]:.0f}s"
                logger.warning(
                    "[%s] ⏱ Timeout en %s — intentando siguiente",
                    agent_name, provider.value
                )
                self._total_fallbacks += 1

            except Exception as exc:
                self._health[provider].record_failure()
                last_error = f"{provider.value}: {str(exc)[:120]}"
                logger.warning(
                    "[%s] ❌ Error en %s: %s — intentando siguiente",
                    agent_name, provider.value, last_error
                )
                self._total_fallbacks += 1

        logger.error(
            "[%s] 💀 Todos los proveedores fallaron. Último error: %s",
            agent_name, last_error
        )
        return AIResponse(
            content="",
            provider=AIProvider.HUGGINGFACE,
            model="none",
            success=False,
            error=last_error or "Todos los proveedores de IA fallaron",
            attempts=attempts,
        )

    async def complete_json(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.STRATEGY,
        max_tokens: int = 2000,
        agent_name: str = "aria",
    ) -> Optional[dict]:
        """Atajo tipado para obtener dict directamente."""
        response = await self.complete(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            json_mode=True,
            agent_name=agent_name,
        )
        if not response.success or not response.content:
            return None
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as exc:
            logger.error(
                "JSON inválido tras extracción: %s | contenido: %s",
                exc, response.content[:200]
            )
            return None

    # ── DISPATCH POR PROVEEDOR ────────────────────────────

    async def _dispatch(
        self,
        provider: AIProvider,
        model: AIModel,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        model_id = MODEL_REGISTRY[model][provider]
        t0 = time.time()

        if provider == AIProvider.HUGGINGFACE:
            content, tokens = await self._call_huggingface(model_id, system, user, max_tokens, temperature)
        elif provider == AIProvider.GROQ:
            content, tokens = await self._call_groq(model_id, system, user, max_tokens, temperature)
        else:
            content, tokens = await self._call_openai(model_id, system, user, max_tokens, temperature)

        latency = int((time.time() - t0) * 1000)
        self._total_tokens += tokens

        return AIResponse(
            content=content,
            provider=provider,
            model=model_id,
            tokens_used=tokens,
            latency_ms=latency,
            success=True,
        )

    async def _call_huggingface(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        response = await self._http.post(
            self._HF_ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.HF_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
            timeout=PROVIDER_TIMEOUTS[AIProvider.HUGGINGFACE],
        )
        if response.status_code == 503:
            raise RuntimeError(f"HuggingFace modelo en cold start (503) — {model_id}")
        if response.status_code != 200:
            raise RuntimeError(f"HuggingFace HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        content = data["choices"][0]["message"]["content"] or ""
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    async def _call_groq(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        completion = await self._groq.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = completion.choices[0].message.content or ""
        tokens = completion.usage.total_tokens if completion.usage else 0
        return content, tokens

    async def _call_openai(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OpenAI API key no configurada — saltando fallback")

        response = await self._http.post(
            self._OAI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=PROVIDER_TIMEOUTS[AIProvider.OPENAI],
        )
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        content = data["choices"][0]["message"]["content"] or ""
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    # ── UTILIDADES ────────────────────────────────────────

    def _get_available_providers(self) -> list[AIProvider]:
        """Retorna proveedores disponibles ordenados por prioridad."""
        order = [AIProvider.HUGGINGFACE, AIProvider.GROQ, AIProvider.OPENAI]
        available = [p for p in order if self._health[p].is_available()]
        if not available:
            logger.error("Todos los circuit breakers abiertos — forzando reset")
            for p in order:
                self._health[p].circuit_open = False
                self._health[p].consecutive_failures = 0
            return order
        return available

    def _extract_json_safe(self, text: str) -> str:
        """Extrae JSON limpio de cualquier respuesta de texto."""
        text = text.strip()
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        if text.startswith(("{", "[")):
            return text
        start_brace = text.find("{")
        start_bracket = text.find("[")
        starts = [s for s in [start_brace, start_bracket] if s != -1]
        if starts:
            return text[min(starts):]
        return text

    def get_health_report(self) -> dict[str, Any]:
        return {
            provider.value: {
                "available": health.is_available(),
                "circuit_open": health.circuit_open,
                "success_rate_pct": health.success_rate,
                "total_calls": health.total_calls,
                "consecutive_failures": health.consecutive_failures,
            }
            for provider, health in self._health.items()
        } | {
            "_totals": {
                "tokens_used": self._total_tokens,
                "fallbacks_triggered": self._total_fallbacks,
            }
        }

    async def close(self) -> None:
        await self._http.aclose()


# ── SINGLETON ASYNC-SAFE ──────────────────────────────────
_client_instance: Optional[AriaAIClient] = None
_client_lock = asyncio.Lock()


async def get_ai_client() -> AriaAIClient:
    """Retorna el singleton del cliente de IA — async-safe."""
    global _client_instance
    if _client_instance is None:
        async with _client_lock:
            if _client_instance is None:
                _client_instance = AriaAIClient()
    return _client_instance
