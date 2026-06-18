"""
perception_layer/engine.py — Los Sentidos de Aria OS.

Responsable de observar el mundo exterior:
  - Monitoreo de eventos globales (GDELT)
  - Extracción de contenido estructurado (Firecrawl/Crawl4AI)
  - Detección de tendencias y cambios en la competencia
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("aria.os.perception")

class PerceptionLayer:
    """Capa de percepción de Aria OS."""

    async def observe_market(self, keywords: list[str]) -> dict[str, Any]:
        """Observa el mercado en busca de señales relevantes."""
        logger.info("[Perception] Observando mercado para: %s", keywords)
        
        # 1. Consultar GDELT para eventos mundiales
        # 2. Scrapear sitios de competencia con Firecrawl
        # 3. Analizar sentimiento en redes sociales
        
        return {
            "signals": ["Crecimiento en demanda de X", "Nuevo competidor Y detectado"],
            "timestamp": "2026-06-17T12:00:00Z"
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_perception_instance: PerceptionLayer | None = None

def get_perception_layer() -> PerceptionLayer:
    """Retorna el singleton de la capa de percepción."""
    global _perception_instance
    if _perception_instance is None:
        _perception_instance = PerceptionLayer()
    return _perception_instance
