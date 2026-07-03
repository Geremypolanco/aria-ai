"""
Aria AI — Cliente de IA con HuggingFace como Motor Principal.
Orden: HuggingFace AsyncInferenceClient (rotación de providers + modelos) → Groq → Gemini → OpenAI

HuggingFace Inference Providers:
  - "hf-inference": tier gratuito con cold start
  - "together": Together AI via HF token (rápido, muchos modelos)
  - "nebius": Nebius AI Studio via HF token
  - "featherless-ai": especializado en 7B-70B
  Todos accesibles con un solo HF_TOKEN — maximiza el crédito mensual gratuito.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx
from groq import AsyncGroq

from apps.core.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger("aria.ai_client")


class AIProvider(StrEnum):
    HUGGINGFACE = "huggingface"
    GROQ = "groq"
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class AIModel(StrEnum):
    STRATEGY = "strategy"
    CODE = "code"
    FAST = "fast"
    CREATIVE = "creative"
    VISION = "vision"


# Provider rotation per task — only free tier; paid providers require separate subscriptions
HF_PROVIDER_ROTATION: list[str] = [
    "together",  # Together AI via HF token — fast, no cold start
    "nebius",  # Nebius AI Studio — good latency, many models
    "hf-inference",  # Official HF — free tier (cold starts possible)
    "featherless-ai",  # Specialized in chat models
]

HF_MODEL_ROTATION: dict[AIModel, list[str]] = {
    AIModel.STRATEGY: [
        "deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        "Qwen/Qwen2.5-72B-Instruct",
        "meta-llama/Llama-3.3-70B-Instruct",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    ],
    AIModel.CODE: [
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "Qwen/Qwen2.5-72B-Instruct",
        "Qwen/Qwen2.5-Coder-7B-Instruct",
    ],
    AIModel.FAST: [
        "Qwen/Qwen2.5-7B-Instruct",
        "meta-llama/Llama-3.2-3B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3",
        "Qwen/Qwen2.5-Coder-7B-Instruct",
    ],
    AIModel.CREATIVE: [
        "meta-llama/Llama-3.3-70B-Instruct",
        "Qwen/Qwen2.5-72B-Instruct",
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    ],
    AIModel.VISION: [
        "meta-llama/Llama-3.2-11B-Vision-Instruct",
        "Qwen/Qwen2-VL-7B-Instruct",
        "microsoft/Phi-3.5-vision-instruct",
    ],
}

# Modelo primario por proveedor
MODEL_REGISTRY: dict[AIModel, dict[AIProvider, str]] = {
    AIModel.STRATEGY: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-72B-Instruct",
        AIProvider.GROQ: "llama-3.3-70b-versatile",
        AIProvider.GEMINI: "gemini-1.5-pro",
        AIProvider.OPENAI: settings.OPENAI_MODEL,
        AIProvider.ANTHROPIC: "claude-3-5-sonnet-20240620",
    },
    AIModel.CODE: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-Coder-32B-Instruct",
        AIProvider.GROQ: "llama-3.3-70b-versatile",
        AIProvider.GEMINI: "gemini-1.5-pro",
        AIProvider.OPENAI: settings.OPENAI_MODEL,
        AIProvider.ANTHROPIC: "claude-3-5-sonnet-20240620",
    },
    AIModel.FAST: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-7B-Instruct",
        AIProvider.GROQ: "llama-3.1-8b-instant",
        AIProvider.GEMINI: "gemini-1.5-flash",
        AIProvider.OPENAI: settings.OPENAI_MODEL,
        AIProvider.ANTHROPIC: "claude-3-5-haiku-20241022",
    },
    AIModel.CREATIVE: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-72B-Instruct",
        AIProvider.GROQ: "llama-3.3-70b-versatile",
        AIProvider.GEMINI: "gemini-1.5-pro",
        AIProvider.OPENAI: settings.OPENAI_MODEL,
        AIProvider.ANTHROPIC: "claude-3-5-sonnet-20240620",
    },
    AIModel.VISION: {
        AIProvider.HUGGINGFACE: "meta-llama/Llama-3.2-11B-Vision-Instruct",
        AIProvider.GROQ: "llava-v1.5-7b-4096-preview",
        AIProvider.GEMINI: "gemini-1.5-flash",
        AIProvider.OPENAI: "gpt-4o-mini",
        AIProvider.ANTHROPIC: "claude-3-5-sonnet-20240620",
    },
}

PROVIDER_TIMEOUTS: dict[AIProvider, float] = {
    AIProvider.HUGGINGFACE: 30.0,
    AIProvider.GROQ: 12.0,
    AIProvider.GEMINI: 20.0,
    AIProvider.OPENAI: 15.0,
    AIProvider.ANTHROPIC: 25.0,
}


@dataclass
class AIResponse:
    content: str
    provider: AIProvider
    model: str
    tokens_used: int = 0
    latency_ms: int = 0
    success: bool = True
    error: str | None = None
    attempts: int = 1


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderHealth:
    """Circuit breaker robusto con estado Half-Open y decaimiento."""

    provider: AIProvider
    consecutive_failures: int = 0
    total_calls: int = 0
    total_errors: int = 0
    last_failure_ts: float = 0.0
    state: CircuitState = CircuitState.CLOSED
    _break_after: int = 3
    _cooldown: float = 60.0  # segundos

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 100.0
        return round((self.total_calls - self.total_errors) / self.total_calls * 100, 1)

    def is_available(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        elapsed = time.time() - self.last_failure_ts
        if self.state == CircuitState.OPEN:
            if elapsed >= self._cooldown:
                self.state = CircuitState.HALF_OPEN
                logger.info("[%s] Circuit breaker en estado HALF-OPEN (probando recuperación)", self.provider)
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return True

        return False

    def record_success(self) -> None:
        self.total_calls += 1
        self.consecutive_failures = 0
        if self.state != CircuitState.CLOSED:
            logger.info("[%s] Circuit breaker CERRADO — proveedor recuperado", self.provider)
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.total_calls += 1
        self.total_errors += 1
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()

        if self.state == CircuitState.HALF_OPEN or self.consecutive_failures >= self._break_after:
            self.state = CircuitState.OPEN
            # Backoff exponencial para el cooldown
            current_cooldown = self._cooldown * (2 ** (self.consecutive_failures // self._break_after - 1))
            current_cooldown = min(current_cooldown, 3600)  # Max 1 hora
            logger.warning("[%s] Circuit breaker ABIERTO — cooldown %.0fs", self.provider, current_cooldown)


class AriaAIClient:
    """
    Motor de IA de ARIA — Resiliente y multi-proveedor.
    """

    _HF_ENDPOINT = "https://api-inference.huggingface.co/v1/chat/completions"
    _OAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self._zapier_mcp_url = settings.ZAPIER_MCP_URL
        self._health: dict[AIProvider, ProviderHealth] = {p: ProviderHealth(provider=p) for p in AIProvider}
        self._groq = AsyncGroq(api_key=settings.GROQ_API_KEY or "no-key")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        self._total_tokens = 0
        self._total_fallbacks = 0
        logger.info("AriaAIClient inicializado — Motor principal: HuggingFace")

    async def complete_json(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.STRATEGY,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        agent_name: str = "aria",
    ) -> dict:
        """Helper to get parsed JSON directly."""
        resp = await self.complete(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
            agent_name=agent_name,
        )
        if not resp.success:
            return {}
        try:
            return json.loads(resp.content)
        except Exception:
            return {}

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
        if json_mode:
            user = (
                f"{user}\n\n"
                "Responde UNICAMENTE con JSON valido y bien formado. "
                "Sin markdown, sin bloques de codigo, sin explicaciones. "
                "Solo el objeto JSON."
            )

        providers = self._get_available_providers()
        last_error: str | None = None
        attempts = 0

        for provider in providers:
            attempts += 1
            try:
                if provider == AIProvider.HUGGINGFACE:
                    response = await self._try_hf_with_rotation(
                        model, system, user, max_tokens, temperature, agent_name
                    )
                    if response and response.success:
                        response.attempts = attempts
                        if json_mode:
                            response.content = self._extract_json_safe(response.content)
                        return response
                    last_error = response.error if response else "HF sin respuesta"
                    self._total_fallbacks += 1
                    continue

                # Otros proveedores (Groq, Gemini, OpenAI, Anthropic)
                response = await asyncio.wait_for(
                    self._dispatch(provider, model, system, user, max_tokens, temperature),
                    timeout=PROVIDER_TIMEOUTS[provider] + 5.0,
                )
                self._health[provider].record_success()
                response.attempts = attempts
                if json_mode:
                    response.content = self._extract_json_safe(response.content)
                
                logger.info(
                    "[%s] OK %s via %s — %dms",
                    agent_name, model.value, provider.value, response.latency_ms
                )
                return response

            except (asyncio.TimeoutError, TimeoutError):
                self._health[provider].record_failure()
                last_error = f"{provider.value}: timeout"
                self._total_fallbacks += 1
                logger.warning("[%s] Timeout en %s", agent_name, provider.value)
            except Exception as exc:
                self._health[provider].record_failure()
                last_error = f"{provider.value}: {str(exc)[:100]}"
                self._total_fallbacks += 1
                logger.warning("[%s] Error en %s: %s", agent_name, provider.value, last_error)

        return AIResponse(
            content="",
            provider=AIProvider.HUGGINGFACE,
            model="none",
            success=False,
            error=last_error or "Todos los proveedores fallaron",
            attempts=attempts,
        )

    async def _try_hf_with_rotation(
        self,
        model: AIModel,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        agent_name: str,
    ) -> AIResponse | None:
        if not settings.hf_key:
            return None

        models_to_try = HF_MODEL_ROTATION.get(model, [])
        for model_id in models_to_try:
            short_name = model_id.split("/")[-1]
            for hf_provider in HF_PROVIDER_ROTATION:
                try:
                    t0 = time.time()
                    # Implementar reintento interno para 503 (Cold Start)
                    for retry in range(2):
                        try:
                            content, tokens = await asyncio.wait_for(
                                self._call_huggingface(
                                    model_id, system, user, max_tokens, temperature, hf_provider
                                ),
                                timeout=PROVIDER_TIMEOUTS[AIProvider.HUGGINGFACE]
                            )
                            latency = int((time.time() - t0) * 1000)
                            self._total_tokens += tokens
                            self._health[AIProvider.HUGGINGFACE].record_success()
                            return AIResponse(
                                content=content,
                                provider=AIProvider.HUGGINGFACE,
                                model=f"{hf_provider}/{model_id}",
                                tokens_used=tokens,
                                latency_ms=latency,
                                success=True,
                            )
                        except Exception as e:
                            err_str = str(e).lower()
                            if "503" in err_str or "loading" in err_str:
                                if retry == 0:
                                    logger.info("[%s] HF cold start %s@%s — reintentando en 2s", agent_name, short_name, hf_provider)
                                    await asyncio.sleep(2.0)
                                    continue
                            raise e

                except Exception as exc:
                    err_str = str(exc).lower()
                    if "404" in err_str or "not supported" in err_str:
                        logger.debug("[%s] HF %s no soportado en %s", agent_name, short_name, hf_provider)
                        break # Probar siguiente modelo
                    
                    logger.warning("[%s] HF fallo %s@%s: %s", agent_name, short_name, hf_provider, err_str[:60])
                    continue # Probar siguiente provider/modelo

        self._health[AIProvider.HUGGINGFACE].record_failure()
        return AIResponse(content="", provider=AIProvider.HUGGINGFACE, model="none", success=False, error="HF rotation exhausted")

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
        elif provider == AIProvider.GEMINI:
            content, tokens = await self._call_gemini(model_id, system, user, max_tokens, temperature)
        elif provider == AIProvider.ANTHROPIC:
            content, tokens = await self._call_anthropic(model_id, system, user, max_tokens, temperature)
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

    async def _call_huggingface(self, model_id: str, system: str, user: str, max_tokens: int, temperature: float, provider: str) -> tuple[str, int]:
        # Use the HF router (OpenAI-compatible) which auto-routes to a working
        # inference provider. Verified live against Qwen2.5-72B and DeepSeek-R1.
        # The previous AsyncInferenceClient(provider=...) path 403'd on providers
        # that don't serve the requested model, which tripped HF's circuit breaker
        # and left only Groq/Gemini (both currently 403) → total AI failure on
        # every tool. Routing through the router endpoint restores HF as primary.
        resp = await self._http.post(
            "https://router.huggingface.co/v1/chat/completions",
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": min(max_tokens, 4096),
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {settings.hf_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        content = (data["choices"][0]["message"]["content"] or "").strip()
        tokens = data.get("usage", {}).get("total_tokens") or len(content.split()) * 2
        return content, tokens

    async def _call_gemini(self, model_id: str, system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, int]:
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY no configurado para Gemini")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={settings.GOOGLE_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": f"System: {system}\n\nUser: {user}"}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}
        }
        resp = await self._http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return content, len(content.split()) * 2

    async def _call_groq(self, model_id: str, system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, int]:
        resp = await self._groq.chat.completions.create(
            model=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip(), resp.usage.total_tokens

    async def _call_openai(self, model_id: str, system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, int]:
        resp = await self._http.post(
            self._OAI_ENDPOINT,
            json={
                "model": model_id,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), data.get("usage", {}).get("total_tokens", 0)

    async def _call_anthropic(self, model_id: str, system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, int]:
        resp = await self._http.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": model_id,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        return data["content"][0]["text"].strip(), usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    def _get_available_providers(self) -> list[AIProvider]:
        base_order = [
            AIProvider.HUGGINGFACE,
            AIProvider.GROQ,
            AIProvider.GEMINI,
            AIProvider.ANTHROPIC,
            AIProvider.OPENAI,
        ]
        
        has_key = {
            AIProvider.HUGGINGFACE: bool(settings.hf_key),
            AIProvider.GROQ: bool(settings.GROQ_API_KEY),
            AIProvider.GEMINI: bool(settings.GOOGLE_API_KEY),
            AIProvider.ANTHROPIC: bool(settings.ANTHROPIC_API_KEY),
            AIProvider.OPENAI: bool(settings.OPENAI_API_KEY),
        }
        
        available = [p for p in base_order if has_key.get(p) and self._health[p].is_available()]
        
        # Si HF ha fallado recientemente, priorizar Groq
        if self._health[AIProvider.HUGGINGFACE].consecutive_failures >= 1 and AIProvider.GROQ in available:
            available.remove(AIProvider.GROQ)
            available.insert(0, AIProvider.GROQ)
            
        return available

    def _extract_json_safe(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("```").strip()
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            idx = text.find(start_char)
            if idx != -1:
                end_idx = text.rfind(end_char)
                if end_idx > idx:
                    return text[idx : end_idx + 1]
        return text

    def get_health_summary(self) -> dict:
        return {
            p.value: {
                "state": self._health[p].state.value,
                "success_rate_pct": self._health[p].success_rate,
                "total_calls": self._health[p].total_calls,
                "consecutive_failures": self._health[p].consecutive_failures,
            }
            for p in AIProvider
        } | {
            "_totals": {
                "tokens_used": self._total_tokens,
                "fallbacks_triggered": self._total_fallbacks,
                "zapier_mcp_active": bool(self._zapier_mcp_url),
            }
        }

    async def get_zapier_tools(self) -> list[dict]:
        """Fetch available tools from Zapier MCP server."""
        if not self._zapier_mcp_url:
            return []
        try:
            # Zapier MCP implementation for tool listing
            resp = await self._http.post(
                self._zapier_mcp_url,
                json={"method": "list_tools", "params": {}},
                timeout=10.0
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", {}).get("tools", [])
        except Exception as e:
            logger.error("Error fetching Zapier tools: %s", e)
        return []

    async def execute_zapier_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool via Zapier MCP server."""
        if not self._zapier_mcp_url:
            return {"success": False, "error": "Zapier MCP not configured"}
        try:
            resp = await self._http.post(
                self._zapier_mcp_url,
                json={
                    "method": "call_tool",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                },
                timeout=30.0
            )
            if resp.status_code == 200:
                return resp.json().get("result", {"success": False})
        except Exception as e:
            logger.error("Error executing Zapier tool %s: %s", tool_name, e)
        return {"success": False, "error": "Zapier MCP execution failed"}

    async def stream_complete(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.FAST,
        max_tokens: int = 1500,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        # Implementación simplificada de streaming vía Groq
        if settings.GROQ_API_KEY and self._health[AIProvider.GROQ].is_available():
            try:
                stream = await self._groq.chat.completions.create(
                    model=MODEL_REGISTRY[model][AIProvider.GROQ],
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                )
                async for chunk in stream:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            except Exception:
                pass
        
        # Fallback a no-streaming
        res = await self.complete(system, user, model, max_tokens, temperature)
        yield res.content

    async def analyze_image(self, image_base64: str, question: str) -> str:
        # Implementación simplificada para visión vía Gemini (mejor en visión gratuita)
        if settings.GOOGLE_API_KEY and self._health[AIProvider.GEMINI].is_available():
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GOOGLE_API_KEY}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": question},
                            {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}
                        ]
                    }]
                }
                resp = await self._http.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception:
                pass
        
        # Fallback a HF Vision si Gemini falla
        res = await self.complete(system="Analiza esta imagen.", user=question, model=AIModel.VISION)
        return res.content

# ── SINGLETON ─────────────────────────────────────────────
_client_instance: AriaAIClient | None = None
_client_lock = asyncio.Lock()

async def get_ai_client_async() -> AriaAIClient:
    global _client_instance
    if _client_instance is not None:
        return _client_instance
    async with _client_lock:
        if _client_instance is None:
            _client_instance = AriaAIClient()
    return _client_instance

def get_ai_client() -> AriaAIClient | None:
    global _client_instance
    if _client_instance is None:
        # Nota: En entornos async esto debería ser evitado, pero se mantiene por compatibilidad
        _client_instance = AriaAIClient()
    return _client_instance
