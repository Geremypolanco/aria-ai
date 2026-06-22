"""
Aria AI — Cliente de IA con HuggingFace como Motor Principal.
Orden: HuggingFace AsyncInferenceClient (rotación de providers + modelos) → Groq → OpenAI

HuggingFace Inference Providers:
  - "hf-inference": tier gratuito con cold start
  - "together": Together AI via HF token (rápido, muchos modelos)
  - "nebius": Nebius AI Studio via HF token
  - "featherless-ai": especializado en 7B-70B
  Todos accesibles con un solo HF_TOKEN — maximiza el crédito mensual gratuito.

Usa huggingface_hub.AsyncInferenceClient — compatible con OpenAI API,
soporta structured outputs (response_format), function calling, streaming,
embeddings (feature_extraction) e imagen (text_to_image).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

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
# MOTOR PRINCIPAL: HuggingFace AsyncInferenceClient
# Rota entre providers Y modelos antes de caer a Groq.
#
# HF Inference Providers accesibles con un HF_TOKEN:
#   "hf-inference" → gratuito (cold start posible)
#   "together"     → Together AI, muy rápido, sin cold start
#   "nebius"       → Nebius AI Studio, buena latencia
#   "featherless-ai" → especializado en chat models
#
# Modelos actualizados a SOTA 2025:
#   STRATEGY: Qwen2.5-72B (mejor razonamiento open-source)
#   CODE:     Qwen2.5-Coder-32B (SOTA en coding benchmarks)
#   FAST:     Qwen2.5-7B / Llama-3.2-3B (< 2s latency)
#   CREATIVE: Llama-3.3-70B (mejor para generación creativa)
# ══════════════════════════════════════════════════════════════

# Provider rotation per task — tried in order before falling to Groq
HF_PROVIDER_ROTATION: list[str] = [
    "hf-inference",   # free tier first (uses monthly credits)
    "together",       # Together AI via HF token — fast fallback
    "nebius",         # Nebius — second paid fallback
    "featherless-ai", # Featherless — third paid fallback
]

HF_MODEL_ROTATION: dict[AIModel, list[str]] = {
    AIModel.STRATEGY: [
        "Qwen/Qwen2.5-72B-Instruct",              # SOTA — complex reasoning
        "meta-llama/Llama-3.3-70B-Instruct",      # SOTA — instruction follow
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503",  # Good mid-size
    ],
    AIModel.CODE: [
        "Qwen/Qwen2.5-Coder-32B-Instruct",        # SOTA coding benchmark
        "Qwen/Qwen2.5-Coder-7B-Instruct",         # Fast coding model
        "meta-llama/Llama-3.3-70B-Instruct",      # Code-capable fallback
    ],
    AIModel.FAST: [
        "Qwen/Qwen2.5-7B-Instruct",               # Fast + capable
        "meta-llama/Llama-3.2-3B-Instruct",       # Ultra-fast
        "Qwen/Qwen2.5-Coder-7B-Instruct",         # Fast fallback
    ],
    AIModel.CREATIVE: [
        "meta-llama/Llama-3.3-70B-Instruct",      # Best for creative text
        "Qwen/Qwen2.5-72B-Instruct",              # Creative fallback
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503",  # Creative alt
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
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-Coder-32B-Instruct",
        AIProvider.GROQ:        "llama-3.3-70b-versatile",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.FAST: {
        AIProvider.HUGGINGFACE: "Qwen/Qwen2.5-7B-Instruct",
        AIProvider.GROQ:        "llama-3.1-8b-instant",
        AIProvider.OPENAI:      settings.OPENAI_MODEL,
    },
    AIModel.CREATIVE: {
        AIProvider.HUGGINGFACE: "meta-llama/Llama-3.3-70B-Instruct",
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
        Rota entre providers HF Y modelos HF antes de rendirse.
        Strategy: intenta cada modelo con hf-inference primero; si falla por
        cold start / rate limit, prueba el mismo modelo con el siguiente provider
        (together, nebius). Así maximizamos el uso del tier gratuito.
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
            for hf_provider in HF_PROVIDER_ROTATION:
                try:
                    t0 = time.time()
                    content, tokens = await asyncio.wait_for(
                        self._call_huggingface(
                            model_id, system, user, max_tokens, temperature,
                            provider=hf_provider,
                        ),
                        timeout=PROVIDER_TIMEOUTS[AIProvider.HUGGINGFACE],
                    )
                    latency = int((time.time() - t0) * 1000)
                    self._total_tokens += tokens
                    self._health[AIProvider.HUGGINGFACE].record_success()
                    logger.info(
                        "[%s] HF[%s@%s] OK — %dms — %d tokens",
                        agent_name, short_name, hf_provider, latency, tokens
                    )
                    return AIResponse(
                        content=content,
                        provider=AIProvider.HUGGINGFACE,
                        model=f"{hf_provider}/{model_id}",
                        tokens_used=tokens,
                        latency_ms=latency,
                        success=True,
                    )

                except asyncio.TimeoutError:
                    logger.warning(
                        "[%s] HF timeout en %s@%s — rotando provider",
                        agent_name, short_name, hf_provider
                    )
                    continue
                except Exception as exc:
                    err_str = str(exc).lower()
                    if any(k in err_str for k in [
                        "loading", "503", "currently loading", "model is loading",
                        "cold", "unavailable",
                    ]):
                        logger.info(
                            "[%s] HF cold start %s@%s — rotando provider",
                            agent_name, short_name, hf_provider
                        )
                    elif "rate" in err_str or "429" in err_str:
                        logger.info(
                            "[%s] HF rate limit %s@%s — rotando provider",
                            agent_name, short_name, hf_provider
                        )
                    elif "not supported" in err_str or "404" in err_str:
                        # Model not on this provider — skip remaining providers for this model
                        logger.debug(
                            "[%s] HF modelo %s no soportado por %s — siguiente modelo",
                            agent_name, short_name, hf_provider
                        )
                        break
                    else:
                        self._health[AIProvider.HUGGINGFACE].record_failure()
                        logger.warning(
                            "[%s] HF error %s@%s: %s",
                            agent_name, short_name, hf_provider, str(exc)[:80]
                        )
                    continue

        self._health[AIProvider.HUGGINGFACE].record_failure()
        return AIResponse(
            content="", provider=AIProvider.HUGGINGFACE, model="none",
            success=False, error="HF: todos los modelos y providers de rotacion fallaron"
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
        provider: str = "hf-inference",
    ) -> tuple[str, int]:
        """
        Uses huggingface_hub.AsyncInferenceClient when available.
        Falls back to raw httpx if the library isn't installed.
        The AsyncInferenceClient is OpenAI-compatible and handles:
          - provider routing (hf-inference / together / nebius / featherless-ai)
          - automatic retries on cold starts
          - structured outputs via response_format
          - streaming, function calling
        """
        hf_key = settings.hf_key
        if not hf_key:
            raise ValueError("HF_TOKEN no configurado")

        try:
            from huggingface_hub import AsyncInferenceClient
            client = AsyncInferenceClient(
                provider=provider,
                api_key=hf_key,
            )
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=min(max_tokens, 2048),
                temperature=temperature,
            )
            content = (response.choices[0].message.content or "").strip()
            tokens = response.usage.total_tokens if response.usage else len(content.split()) * 2
            return content, tokens

        except ImportError:
            # huggingface_hub not installed — fall back to raw httpx
            pass

        # Raw httpx fallback (original implementation)
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

    # ── STREAMING ─────────────────────────────────────────

    async def stream_complete(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.FAST,
        max_tokens: int = 1500,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        Streams response tokens via Groq (fastest streaming provider).
        Falls back to chunked non-streaming if Groq unavailable.
        Yields text delta strings.
        """
        groq_model = MODEL_REGISTRY[model][AIProvider.GROQ]
        if settings.GROQ_API_KEY and self._health[AIProvider.GROQ].is_available():
            try:
                stream = await self._groq.chat.completions.create(
                    model=groq_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
                return
            except Exception as exc:
                logger.warning("[stream_complete] Groq stream failed: %s — falling back", exc)

        # Fallback: full response, yield in ~30-char chunks to simulate streaming
        try:
            resp = await self.complete(system=system, user=user, model=model,
                                        max_tokens=max_tokens, temperature=temperature)
            text = resp.content or ""
            chunk_size = 28
            for i in range(0, len(text), chunk_size):
                yield text[i:i + chunk_size]
                await asyncio.sleep(0.012)
        except Exception as exc:
            yield f"[Error: {exc}]"

    # ── VISION ────────────────────────────────────────────

    async def analyze_image(
        self,
        image_base64: str,
        media_type: str = "image/jpeg",
        question: str = "Describe this image in detail.",
        max_tokens: int = 1000,
    ) -> str:
        """
        Analyze an image with vision. Tries Groq (llama-3.2-vision) first,
        then falls back to OpenAI GPT-4o-mini vision.
        Returns the analysis text.
        """
        # Try Groq vision (llama-3.2-11b-vision-preview)
        if settings.GROQ_API_KEY and self._health[AIProvider.GROQ].is_available():
            try:
                from groq import AsyncGroq
                groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
                resp = await asyncio.wait_for(
                    groq_client.chat.completions.create(
                        model="llama-3.2-11b-vision-preview",
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_base64}"}},
                                {"type": "text", "text": question},
                            ],
                        }],
                        max_tokens=max_tokens,
                    ),
                    timeout=30.0,
                )
                content = resp.choices[0].message.content or ""
                if content:
                    return content.strip()
            except Exception as exc:
                logger.warning("[Vision] Groq vision failed: %s", exc)

        # Fall back to OpenAI GPT-4o-mini vision
        if settings.OPENAI_API_KEY:
            try:
                resp = await self._http.post(
                    self._OAI_ENDPOINT,
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_base64}"}},
                                {"type": "text", "text": question},
                            ],
                        }],
                        "max_tokens": max_tokens,
                    },
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            except Exception as exc:
                logger.warning("[Vision] OpenAI vision failed: %s", exc)

        # Fall back to text description using HF BLIP-2
        if settings.hf_key:
            try:
                res = await self._http.post(
                    "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-large",
                    headers={"Authorization": f"Bearer {settings.hf_key}"},
                    content=base64.b64decode(image_base64),
                    timeout=30.0,
                )
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list) and data:
                        return data[0].get("generated_text", "")
            except Exception as exc:
                logger.warning("[Vision] HF BLIP fallback failed: %s", exc)

        return "No se pudo analizar la imagen (configura GROQ_API_KEY u OPENAI_API_KEY para visión)."

    # ── EMBEDDINGS ────────────────────────────────────────

    async def get_embeddings(
        self,
        texts: list[str],
        model_id: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> Optional[list[list[float]]]:
        """
        Generate sentence embeddings using HF feature_extraction.
        Uses AsyncInferenceClient.feature_extraction when available.
        Useful for semantic search, clustering, RAG systems.

        Returns list of embedding vectors (one per input text).
        """
        if not settings.hf_key:
            return None
        try:
            from huggingface_hub import AsyncInferenceClient
            client = AsyncInferenceClient(
                provider="hf-inference",
                api_key=settings.hf_key,
            )
            embeddings = await client.feature_extraction(
                text=texts,
                model=model_id,
            )
            # Returns numpy array or list; convert to Python lists
            if hasattr(embeddings, "tolist"):
                return embeddings.tolist()
            return list(embeddings)
        except Exception as exc:
            logger.warning("[AriaAI] get_embeddings failed: %s", exc)
            return None

    # ── IMAGE GENERATION ──────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        model_id: str = "black-forest-labs/FLUX.1-schnell",
        provider: str = "hf-inference",
    ) -> Optional[bytes]:
        """
        Generate an image from text using FLUX via HF Inference.
        Uses AsyncInferenceClient.text_to_image.
        Returns raw image bytes (PNG/JPEG) or None on failure.

        Supported providers for text_to_image:
          "hf-inference", "fal-ai", "together", "replicate", "nebius"
        """
        if not settings.hf_key:
            return None
        try:
            from huggingface_hub import AsyncInferenceClient
            client = AsyncInferenceClient(
                provider=provider,
                api_key=settings.hf_key,
            )
            image = await asyncio.wait_for(
                client.text_to_image(prompt, model=model_id),
                timeout=60.0,
            )
            # image is a PIL.Image object
            import io
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            logger.warning("[AriaAI] generate_image failed (%s): %s", provider, exc)
            return None

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


async def refresh_model_rotation_from_redis() -> bool:
    """
    Carga HF_MODEL_ROTATION dinámico desde Redis (generado por model_router).
    Si no hay datos en Redis, mantiene la configuración estática.
    Llama esto al inicio o cuando model_discovery_job actualiza la tabla.
    """
    global HF_MODEL_ROTATION
    try:
        from apps.core.memory.redis_client import get_cache
        cache = get_cache()
        raw = await cache.get("aria:model_router:hf_rotation")
        if not raw:
            logger.debug("[AIClient] Sin rotación dinámica en Redis — usando config estática")
            return False
        dynamic = __import__('json').loads(raw)
        if not dynamic:
            return False
        # Validar y mergear: el config dinámico tiene prioridad pero se usan enum keys
        updated = 0
        for model_enum in AIModel:
            key = model_enum.value
            if key in dynamic and dynamic[key]:
                HF_MODEL_ROTATION[model_enum] = dynamic[key]
                updated += 1
        if updated:
            logger.info("[AIClient] HF_MODEL_ROTATION actualizado desde Redis: %d modelos", updated)
        return updated > 0
    except Exception as exc:
        logger.debug("[AIClient] No se pudo cargar rotación dinámica: %s", exc)
        return False
