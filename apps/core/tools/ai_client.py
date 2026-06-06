"""
Aria AI — Cliente de IA con HuggingFace como Motor Principal.
Orden: HuggingFace (rotación de 3 modelos) → Groq → OpenAI

HF Serverless Inference API es gratuita y admite los mejores modelos open-source.
Si el modelo primario está bajo carga, rota automáticamente a modelos alternativos
ANTES de caer a Groq — maximizando el uso del tier gratuito de HuggingFace.
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


class AIProvider(str, Enum):
    HUGGINGFACE = "huggingface"
    GROQ = "groq"
    OPENAI = "openai"


class AIModel(str, Enum):
    STRATEGY = "strategy"
    CODE = "code"
    FAST = "fast"
    CREATIVE = "creative"


# ══════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL: HuggingFace — 3 modelos por tarea
# Si el modelo primario está ocupado o en cold start, rota
# automáticamente ANTES de caer a Groq.
# ══════════════════════════════════════════════════════════════
HF_MODEL_ROTATION: dict[AIModel, list[str]] = {
    AIModel.STRATEGY: [
        "Qwen/Qwen2.5-72B-Instruct",           # Primario — más potente
        "mistralai/Mistral-7B-Instruct-v0.3",  # Respaldo HF 1
        "HuggingFaceH4/zephyr-7b-beta",        # Respaldo HF 2
    ],
    AIModel.CODE: [
        "Qwen/Qwen2.5-Coder-7B-Instruct",     # Primario — código
        "microsoft/Phi-3.5-mini-instruct",     # Respaldo HF 1
        "mistralai/Mistral-7B-Instruct-v0.3",  # Respaldo HF 2
    ],
    AIModel.FAST: [
        "microsoft/Phi-3-mini-4k-instruct",    # Primario — más rápido
        "HuggingFaceH4/zephyr-7b-beta",        # Respaldo HF 1
        "mistralai/Mistral-7B-Instruct-v0.3",  # Respaldo HF 2
    ],
    AIModel.CREATIVE: [
        "HuggingFaceH4/zephyr-7b-beta",        # Primario — mejor para creativo
        "mistralai/Mistral-7B-Instruct-v0.3",  # Respaldo HF 1
        "Qwen/Qwen2.5-72B-Instruct",           # Respaldo HF 2
    ],
}

# Modelo primario por proveedor (para _dispatch directo)
MODEL_REGISTRY: dict[AIModel, dict[AIProvider, str]] = {
    AIModel.STRATEGY: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-72B-Instruct",
        AIProvider.GROQ:        "llama-3.3-70b-versatile",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.CODE: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-Coder-7B-Instruct",
        AIProvider.GROQ:        "llama-3.3-70b-versatile",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.FAST: {
        AIProvider.HUGGINGFACE: "microsoft/Phi-3-mini-4k-instruct",
        AIProvider.GROQ:        "llama-3.1-8b-instant",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.CREATIVE: {
        AIProvider.HUGGINGFACE: "HuggingFaceH4/zephyr-7b-beta",
        AIProvider.GROQ:        "llama-3.3-70b-versatile",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
}

PROVIDER_TIMEOUTS: dict[AIProvider, float] = {
    AIProvider.HUGGINGFACE: 35.0,  # HF puede tener cold start — más margen
    AIProvider.GROQ:        12.0,
    AIProvider.OPENAI:      15.0,
}


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
    """Circuit breaker por proveedor con cooldown automático."""
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
            logger.warning("Circuit breaker ABIERTO — cooldown %.0fs", self._cooldown)


class AriaAIClient:
    """
    Motor de IA de ARIA — HuggingFace como proveedor primario.
    Rota entre 3 modelos HF antes de caer a Groq.
    """

    _HF_ENDPOINT = "https://api-inference.huggingface.co/v1/chat/completions"
    _OAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self._health: dict[AIProvider, ProviderHealth] = {
            p: ProviderHealth() for p in AIProvider
        }
        self._groq = AsyncGroq(api_key=settings.GROQ_API_KEY or "no-key")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(40.0, connect=8.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._total_tokens = 0
        self._total_fallbacks = 0
        hf_status = "HF_TOKEN configurado" if settings.hf_key else "SIN HF_TOKEN"
        groq_status = "GROQ configurado" if settings.GROQ_API_KEY else "SIN GROQ"
        logger.info("AriaAIClient — Motor: HF(%s) → Groq(%s) → OpenAI", hf_status, groq_status)

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
        Ejecuta llamada de IA con failover completo.
        Orden: HuggingFace (3 modelos en rotación) → Groq → OpenAI
        """
        if json_mode:
            user = (
                f"{user}\n\n"
                "Responde UNICAMENTE con JSON valido y bien formado. "
                "Sin markdown, sin bloques de codigo, sin explicaciones. "
                "Solo el objeto JSON."
            )

        providers = self._get_available_providers()
        last_error: Optional[str] = None
        attempts = 0

        for provider in providers:
            attempts += 1

            # HuggingFace: rotar entre 3 modelos antes de pasar al siguiente proveedor
            if provider == AIProvider.HUGGINGFACE:
                hf_result = await self._try_hf_with_rotation(
                    model, system, user, max_tokens, temperature, agent_name
                )
                if hf_result and hf_result.success:
                    hf_result.attempts = attempts
                    if json_mode:
                        hf_result.content = self._extract_json_safe(hf_result.content)
                    return hf_result
                last_error = hf_result.error if hf_result else "HF sin respuesta"
                self._total_fallbacks += 1
                logger.warning("[%s] HF agoto rotacion → probando Groq", agent_name)
                continue

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
                    "[%s] OK %s via %s — %dms — %d tokens",
                    agent_name, model.value, provider.value,
                    response.latency_ms, response.tokens_used,
                )
                return response

            except asyncio.TimeoutError:
                self._health[provider].record_failure()
                last_error = f"{provider.value}: timeout tras {PROVIDER_TIMEOUTS[provider]:.0f}s"
                self._total_fallbacks += 1
                logger.warning("[%s] Timeout en %s", agent_name, provider.value)

            except Exception as exc:
                self._health[provider].record_failure()
                last_error = f"{provider.value}: {str(exc)[:100]}"
                self._total_fallbacks += 1
                logger.warning("[%s] Error en %s: %s", agent_name, provider.value, last_error)

        logger.error("[%s] Todos los proveedores fallaron. Ultimo error: %s", agent_name, last_error)
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
        """Atajo tipado — retorna dict directamente."""
        response = await self.complete(
            system=system, user=user, model=model,
            max_tokens=max_tokens, json_mode=True, agent_name=agent_name,
        )
        if not response.success or not response.content:
            return None
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as exc:
            logger.error("JSON invalido: %s | contenido: %s", exc, response.content[:200])
            return None

    # ── HF MODEL ROTATION ─────────────────────────────────

    async def _try_hf_with_rotation(
        self,
        model: AIModel,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        agent_name: str,
    ) -> Optional[AIResponse]:
        """
        Intenta hasta 3 modelos HF distintos antes de rendirse.
        Maneja cold starts y modelos bajo carga de forma transparente.
        """
        if not settings.hf_key:
            return AIResponse(
                content="", provider=AIProvider.HUGGINGFACE, model="none",
                success=False, error="HF_TOKEN no configurado"
            )

        models_to_try = HF_MODEL_ROTATION.get(
            model, [MODEL_REGISTRY[model][AIProvider.HUGGINGFACE]]
        )

        for model_id in models_to_try:
            short_name = model_id.split("/")[-1]
            try:
                t0 = time.time()
                content, tokens = await asyncio.wait_for(
                    self._call_huggingface(model_id, system, user, max_tokens, temperature),
                    timeout=PROVIDER_TIMEOUTS[AIProvider.HUGGINGFACE],
                )
                latency = int((time.time() - t0) * 1000)
                self._total_tokens += tokens
                self._health[AIProvider.HUGGINGFACE].record_success()
                logger.info(
                    "[%s] HF[%s] OK — %dms — %d tokens",
                    agent_name, short_name, latency, tokens
                )
                return AIResponse(
                    content=content,
                    provider=AIProvider.HUGGINGFACE,
                    model=model_id,
                    tokens_used=tokens,
                    latency_ms=latency,
                    success=True,
                )

            except asyncio.TimeoutError:
                logger.warning("[%s] HF timeout en %s — rotando", agent_name, short_name)
                continue
            except Exception as exc:
                err_str = str(exc).lower()
                if any(k in err_str for k in ["loading", "503", "currently loading", "model is loading"]):
                    logger.info("[%s] HF cargando %s — rotando modelo", agent_name, short_name)
                elif "rate" in err_str or "429" in err_str:
                    logger.info("[%s] HF rate limit en %s — rotando", agent_name, short_name)
                else:
                    # DNS / connection error — cuenta para el circuit breaker
                    self._health[AIProvider.HUGGINGFACE].record_failure()
                    logger.warning("[%s] HF error %s: %s", agent_name, short_name, str(exc)[:80])
                continue

        self._health[AIProvider.HUGGINGFACE].record_failure()
        return AIResponse(
            content="", provider=AIProvider.HUGGINGFACE, model="none",
            success=False, error="HF: todos los modelos de rotacion fallaron"
        )

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
        if provider == AIProvider.GROQ:
            content, tokens = await self._call_groq(model_id, system, user, max_tokens, temperature)
        else:
            content, tokens = await self._call_openai(model_id, system, user, max_tokens, temperature)
        latency = int((time.time() - t0) * 1000)
        self._total_tokens += tokens
        return AIResponse(
            content=content, provider=provider, model=model_id,
            tokens_used=tokens, latency_ms=latency, success=True,
        )

    async def _call_huggingface(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        hf_key = settings.hf_key
        if not hf_key:
            raise ValueError("HF_TOKEN no configurado")

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": min(max_tokens, 2048),
            "temperature": temperature,
            "stream": False,
        }
        resp = await self._http.post(
            self._HF_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {hf_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code == 503:
            raise Exception("503 currently loading")
        if resp.status_code == 429:
            raise Exception("429 rate limit")
        resp.raise_for_status()

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"HF sin choices: {str(data)[:100]}")
        content = choices[0].get("message", {}).get("content", "").strip()
        tokens = data.get("usage", {}).get("total_tokens", len(content.split()) * 2)
        return content, tokens

    async def _call_groq(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY no configurado")
        resp = await self._groq.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else len(content.split()) * 2
        return content.strip(), tokens

    async def _call_openai(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int]:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY no configurado")
        resp = await self._http.post(
            self._OAI_ENDPOINT,
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    # ── UTILIDADES ────────────────────────────────────────

    def _get_available_providers(self) -> list[AIProvider]:
        order = [AIProvider.HUGGINGFACE, AIProvider.GROQ, AIProvider.OPENAI]
        return [p for p in order if self._health[p].is_available()]

    def _extract_json_safe(self, text: str) -> str:
        text = text.strip()
        # Remover markdown code blocks
        text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("```").strip()
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            idx = text.find(start_char)
            if idx != -1:
                end_idx = text.rfind(end_char)
                if end_idx > idx:
                    return text[idx:end_idx + 1]
        return text

    def get_health_summary(self) -> dict:
        return {
            p.value: {
                "available": self._health[p].is_available(),
                "circuit_open": self._health[p].circuit_open,
                "success_rate_pct": self._health[p].success_rate,
                "total_calls": self._health[p].total_calls,
                "consecutive_failures": self._health[p].consecutive_failures,
            }
            for p in AIProvider
        } | {
            "_totals": {
                "tokens_used": self._total_tokens,
                "fallbacks_triggered": self._total_fallbacks,
            }
        }


# ── SINGLETON ─────────────────────────────────────────────
_client_instance: Optional[AriaAIClient] = None
_client_lock = asyncio.Lock()


async def get_ai_client_async() -> AriaAIClient:
    global _client_instance
    async with _client_lock:
        if _client_instance is None:
            _client_instance = AriaAIClient()
    return _client_instance


def get_ai_client() -> Optional[AriaAIClient]:
    global _client_instance
    if _client_instance is None:
        _client_instance = AriaAIClient()
    return _client_instance
