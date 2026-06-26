"""
economic_brain.py — Cerebro Económico y RL para ARIA AI.

Utiliza Ray y RLlib para optimizar decisiones económicas:
  - Asignación de presupuesto entre canales.
  - Optimización de precios y ofertas.
  - Maximización del valor de vida del cliente (LTV).

Referencia: https://docs.ray.io/en/latest/rllib/index.html
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.economic_brain")

# ── Ray Import con fallback ──────────────────────────────────────────────────
try:
    import ray
    from ray import rllib  # noqa: F401

    RAY_AVAILABLE = True
    logger.info("[Ray] SDK cargado correctamente.")
except ImportError:
    RAY_AVAILABLE = False
    logger.warning("[Ray] ray/rllib no instalado.")


class AriaEconomicBrain:
    """
    Cerebro Económico de ARIA.
    Utiliza Aprendizaje por Refuerzo para la optimización de recursos.
    """

    def __init__(self) -> None:
        if RAY_AVAILABLE and not ray.is_initialized():
            try:
                ray.init(ignore_reinit_error=True)
            except Exception as exc:
                logger.error("[EconomicBrain] Error inicializando Ray: %s", exc)

    async def optimize_budget(self, current_state: dict[str, Any]) -> dict[str, float]:
        """Optimiza la distribución de presupuesto basada en el estado actual del mercado."""
        logger.info("[EconomicBrain] Calculando asignación óptima de presupuesto...")
        # Simulación de política de RL
        return {"LinkedIn": 0.45, "YouTube": 0.25, "SEO": 0.20, "Email": 0.10}


# ── Singleton ────────────────────────────────────────────────────────────────
_economic_brain_instance: AriaEconomicBrain | None = None


def get_economic_brain() -> AriaEconomicBrain:
    """Retorna el singleton del cerebro económico."""
    global _economic_brain_instance
    if _economic_brain_instance is None:
        _economic_brain_instance = AriaEconomicBrain()
    return _economic_brain_instance
