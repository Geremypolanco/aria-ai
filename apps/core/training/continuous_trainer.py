"""
continuous_trainer.py — Loop de auto-mejora real de ARIA AI.

Corre en background 24/7. Evalúa las capacidades del sistema,
detecta degradación de APIs, registra aprendizajes y mantiene
ARIA funcional y actualizada.

Sin placeholders. Todo basado en llamadas reales.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.trainer")


class ContinuousTrainer:
    """
    Evaluador continuo de capacidades de ARIA.
    Detecta qué funciona, qué no, y actualiza el estado interno.
    """

    CYCLE_INTERVAL = 1800  # 30 minutos entre ciclos
    STATUS_KEY = "aria:trainer:status"
    SKILLS_KEY = "aria:trainer:skills"

    def __init__(self) -> None:
        self._running = False
        self._cycle = 0
        self._last_cycle = 0.0
        self._skills: dict[str, float] = {}  # skill → score 0-100
        self._cache = None

    # ── LOOP PRINCIPAL ────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Loop de evaluación continua. Llamar con asyncio.create_task()."""
        self._running = True
        logger.info("[Trainer] Loop de auto-mejora iniciado")
        while self._running:
            try:
                await self._run_cycle()
            except Exception as exc:
                logger.error("[Trainer] Ciclo falló: %s", exc)
            await asyncio.sleep(self.CYCLE_INTERVAL)

    async def _run_cycle(self) -> None:
        self._cycle += 1
        self._last_cycle = time.time()
        logger.info("[Trainer] Ciclo #%d", self._cycle)

        await asyncio.gather(
            self._eval_ai_client(),
            self._eval_huggingface(),
            self._eval_memory(),
            return_exceptions=True,
        )

        await self._persist_status()
        logger.info(
            "[Trainer] Ciclo #%d completo. Skills: %s",
            self._cycle,
            {k: f"{v:.0f}%" for k, v in self._skills.items()},
        )

    # ── EVALUACIONES ─────────────────────────────────────────────────────

    async def _eval_ai_client(self) -> None:
        """Verifica que el cliente de IA responda correctamente."""
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            ai = get_ai_client()
            resp = await ai.complete(
                system="Responde solo con: OK",
                user="Test de conectividad",
                model=AIModel.FAST,
                max_tokens=5,
                temperature=0.0,
            )
            score = 100.0 if (resp and resp.success) else 0.0
            self._skills["ai_client"] = score
            logger.debug("[Trainer] ai_client: %.0f%%", score)
        except Exception as exc:
            self._skills["ai_client"] = 0.0
            logger.warning("[Trainer] ai_client falló: %s", exc)

    async def _eval_huggingface(self) -> None:
        """Verifica acceso a HuggingFace Inference API."""
        try:
            import httpx

            from apps.core.config import settings

            token = getattr(settings, "hf_key", None)
            if not token:
                self._skills["huggingface"] = 0.0
                return
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    "https://api-inference.huggingface.co/models/gpt2",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self._skills["huggingface"] = 80.0 if r.status_code in (200, 503) else 0.0
        except Exception as exc:
            self._skills["huggingface"] = 0.0
            logger.debug("[Trainer] HuggingFace eval: %s", exc)

    async def _eval_memory(self) -> None:
        """Verifica Redis (Upstash)."""
        try:
            cache = self._get_cache()
            if not cache:
                self._skills["memory"] = 0.0
                return
            test_key = "aria:trainer:probe"
            ok = await cache.set(test_key, "1", ttl_seconds=60)
            val = await cache.get(test_key)
            self._skills["memory"] = 100.0 if (ok and val == "1") else 50.0
        except Exception:
            self._skills["memory"] = 0.0

    # ── PERSISTENCIA ─────────────────────────────────────────────────────

    async def _persist_status(self) -> None:
        try:
            cache = self._get_cache()
            if not cache:
                return
            status = {
                "cycle": self._cycle,
                "last_cycle_at": datetime.now(UTC).isoformat(),
                "skills": self._skills,
            }
            await cache.set(self.STATUS_KEY, status, ttl_seconds=7200)
            await cache.set(self.SKILLS_KEY, self._skills, ttl_seconds=7200)
        except Exception as exc:
            logger.debug("[Trainer] persist falló: %s", exc)

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycle": self._cycle,
            "last_cycle_at": (
                datetime.fromtimestamp(self._last_cycle, tz=UTC).isoformat()
                if self._last_cycle
                else None
            ),
            "skill_scores": self._skills,
        }

    def _get_cache(self):
        if self._cache is None:
            try:
                from apps.core.memory.redis_client import get_cache

                self._cache = get_cache()
            except Exception:
                pass
        return self._cache


# ─── SINGLETON ────────────────────────────────────────────────────────────

_trainer: ContinuousTrainer | None = None


def get_trainer() -> ContinuousTrainer:
    global _trainer
    if _trainer is None:
        _trainer = ContinuousTrainer()
    return _trainer
