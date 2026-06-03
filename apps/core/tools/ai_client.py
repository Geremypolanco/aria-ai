"""
Cliente de IA dinámico con fallback automático.
Primario: HuggingFace (gratis)
Secundario: Groq (gratis, ultra rápido)
Fallback: OpenAI (pago, último recurso)
"""
import asyncio
import time
import json
import re
from enum import Enum
from typing import Optional, Any
from dataclasses import dataclass, field
import httpx
from groq import AsyncGroq
from apps.core.config import settings


# ── TIPOS ─────────────────────────────────────────────────
class AIProvider(str, Enum):
    HUGGINGFACE = "huggingface"
    GROQ = "groq"
    OPENAI = "openai"


class AIModel(str, Enum):
    STRATEGY = "strategy"
    CODE = "code"
    FAST = "fast"


@dataclass
class AIResponse:
    content: str
    provider: AIProvider
    model: str
    tokens_used: int = 0
    latency_ms: int = 0
    success: bool = True
    error: Optional[str] = None


@dataclass
class AIMetrics:
    hf_calls: int = 0
    hf_errors: int = 0
    groq_calls: int = 0
    groq_errors: int = 0
    openai_calls: int = 0
    openai_errors: int = 0
    total_tokens: int = 0
    fallbacks_triggered: int = 0
    provider_history: list = field(default_factory=list)

    def success_rate(self, provider: AIProvider) -> float:
        if provider == AIProvider.HUGGINGFACE:
            total = self.hf_calls
            errors = self.hf_errors
        elif provider == AIProvider.GROQ:
            total = self.groq_calls
            errors = self.groq_errors
        else:
            total = self.openai_calls
            errors = self.openai_errors
        if total == 0:
            return 100.0
        return round((total - errors) / total * 100, 2)


# ── MAPA DE MODELOS ───────────────────────────────────────
MODEL_MAP = {
    AIModel.STRATEGY: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_STRATEGY,
        AIProvider.GROQ: settings.GROQ_MODEL,
        AIProvider.OPENAI: settings.OPENAI_MODEL,
    },
    AIModel.CODE: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_CODE,
        AIProvider.GROQ: "llama-3.3-70b-versatile",
        AIProvider.OPENAI: "gpt-4o-mini",
    },
    AIModel.FAST: {
        AIProvider.HUGGINGFACE: settings.HF_MODEL_FAST,
        AIProvider.GROQ: "llama-3.1-8b-instant",
        AIProvider.OPENAI: "gpt-4o-mini",
    },
}

# ── CLIENTE PRINCIPAL ─────────────────────────────────────
class AriaAIClient:
    """
    Cliente de IA con fallback automático entre proveedores.
    Detecta errores y cambia de proveedor sin interrumpir la operación.
    """

    def __init__(self):
        self.metrics = AIMetrics()
        self._groq = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self._hf_base = "https://api-inference.huggingface.co/v1/chat/completions"
        self._openai_base = "https://api.openai.com/v1/chat/completions"
        self._http = httpx.AsyncClient(timeout=120.0)
        self._provider_health = {
            AIProvider.HUGGINGFACE: True,
            AIProvider.GROQ: True,
            AIProvider.OPENAI: True,
        }
        self._provider_fail_count = {
            AIProvider.HUGGINGFACE: 0,
            AIProvider.GROQ: 0,
            AIProvider.OPENAI: 0,
        }
        self.MAX_FAILS_BEFORE_SKIP = 3

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
        Ejecuta una llamada de IA con fallback automático.
        Intenta HF → Groq → OpenAI en ese orden.
        """
        if json_mode:
            user = (
                user
                + "\n\nResponde ÚNICAMENTE con JSON válido. "
                "Sin markdown, sin explicaciones, solo el JSON."
            )

        providers = self._get_provider_order()

        for provider in providers:
            if not self._is_healthy(provider):
                continue
            try:
                response = await self._call_provider(
                    provider=provider,
                    model=model,
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if response.success:
                    self._reset_fail_count(provider)
                    self._record_metric(provider, success=True)
                    self.metrics.provider_history.append(
                        {"provider": provider, "agent": agent_name, "model": model}
                    )
                    if json_mode:
                        response.content = self._extract_json(response.content)
                    return response

            except Exception as e:
                self._record_metric(provider, success=False)
                self._increment_fail_count(provider)
                self.metrics.fallbacks_triggered += 1
                continue

        return AIResponse(
            content="",
            provider=AIProvider.HUGGINGFACE,
            model="none",
            success=False,
            error="Todos los proveedores de IA fallaron",
        )

    async def complete_json(
        self,
        system: str,
        user: str,
        model: AIModel = AIModel.STRATEGY,
        max_tokens: int = 2000,
        agent_name: str = "aria",
    ) -> Optional[dict]:
        """Atajo para obtener JSON directamente."""
        response = await self.complete(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            json_mode=True,
            agent_name=agent_name,
        )
        if not response.success:
            return None
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return None

    # ── PROVEEDORES ───────────────────────────────────────

    async def _call_provider(
        self,
        provider: AIProvider,
        model: AIModel,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        start = time.time()
        model_id = MODEL_MAP[model][provider]

        if provider == AIProvider.HUGGINGFACE:
            result = await self._call_huggingface(
                model_id, system, user, max_tokens, temperature
            )
        elif provider == AIProvider.GROQ:
            result = await self._call_groq(
                model_id, system, user, max_tokens, temperature
            )
        else:
            result = await self._call_openai(
                model_id, system, user, max_tokens, temperature
            )

        latency = int((time.time() - start) * 1000)
        result.latency_ms = latency
        return result

    async def _call_huggingface(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        self.metrics.hf_calls += 1
        response = await self._http.post(
            self._hf_base,
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
            },
        )
        if response.status_code != 200:
            self.metrics.hf_errors += 1
            raise Exception(f"HuggingFace error {response.status_code}: {response.text[:200]}")

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        self.metrics.total_tokens += tokens

        return AIResponse(
            content=content,
            provider=AIProvider.HUGGINGFACE,
            model=model_id,
            tokens_used=tokens,
            success=True,
        )

    async def _call_groq(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        self.metrics.groq_calls += 1
        completion = await self._groq.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = completion.choices[0].message.content
        tokens = completion.usage.total_tokens if completion.usage else 0
        self.metrics.total_tokens += tokens

        return AIResponse(
            content=content,
            provider=AIProvider.GROQ,
            model=model_id,
            tokens_used=tokens,
            success=True,
        )

    async def _call_openai(
        self,
        model_id: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> AIResponse:
        if not settings.OPENAI_API_KEY:
            raise Exception("OpenAI API key no configurada")

        self.metrics.openai_calls += 1
        response = await self._http.post(
            self._openai_base,
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
        )
        if response.status_code != 200:
            self.metrics.openai_errors += 1
            raise Exception(f"OpenAI error {response.status_code}")

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        self.metrics.total_tokens += tokens

        return AIResponse(
            content=content,
            provider=AIProvider.OPENAI,
            model=model_id,
            tokens_used=tokens,
            success=True,
        )

    # ── UTILIDADES ────────────────────────────────────────

    def _get_provider_order(self) -> list[AIProvider]:
        """Ordena proveedores por salud y tasa de éxito."""
        order = [AIProvider.HUGGINGFACE, AIProvider.GROQ, AIProvider.OPENAI]
        return [p for p in order if self._provider_health[p]]

    def _is_healthy(self, provider: AIProvider) -> bool:
        if self._provider_fail_count[provider] >= self.MAX_FAILS_BEFORE_SKIP:
            self._provider_health[provider] = False
            return False
        return True

    def _reset_fail_count(self, provider: AIProvider):
        self._provider_fail_count[provider] = 0
        self._provider_health[provider] = True

    def _increment_fail_count(self, provider: AIProvider):
        self._provider_fail_count[provider] += 1

    def _record_metric(self, provider: AIProvider, success: bool):
        if provider == AIProvider.HUGGINGFACE:
            if not success:
                self.metrics.hf_errors += 1
        elif provider == AIProvider.GROQ:
            if not success:
                self.metrics.groq_errors += 1
        else:
            if not success:
                self.metrics.openai_errors += 1

    def _extract_json(self, text: str) -> str:
        """Extrae JSON limpio de una respuesta de texto."""
        text = text.strip()
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        if text.startswith("{") or text.startswith("["):
            return text
        start = text.find("{")
        if start == -1:
            start = text.find("[")
        if start != -1:
            return text[start:]
        return text

    def get_metrics_summary(self) -> dict:
        return {
            "huggingface": {
                "calls": self.metrics.hf_calls,
                "errors": self.metrics.hf_errors,
                "success_rate": self.metrics.success_rate(AIProvider.HUGGINGFACE),
                "healthy": self._provider_health[AIProvider.HUGGINGFACE],
            },
            "groq": {
                "calls": self.metrics.groq_calls,
                "errors": self.metrics.groq_errors,
                "success_rate": self.metrics.success_rate(AIProvider.GROQ),
                "healthy": self._provider_health[AIProvider.GROQ],
            },
            "openai": {
                "calls": self.metrics.openai_calls,
                "errors": self.metrics.openai_errors,
                "success_rate": self.metrics.success_rate(AIProvider.OPENAI),
                "healthy": self._provider_health[AIProvider.OPENAI],
            },
            "total_tokens": self.metrics.total_tokens,
            "fallbacks_triggered": self.metrics.fallbacks_triggered,
        }

    async def close(self):
        await self._http.aclose()


# ── SINGLETON ─────────────────────────────────────────────
_ai_client: Optional[AriaAIClient] = None


def get_ai_client() -> AriaAIClient:
    global _ai_client
    if _ai_client is None:
        _ai_client = AriaAIClient()
    return _ai_client

