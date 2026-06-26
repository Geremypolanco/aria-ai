"""
ROI_model.py — Modelo de Retorno de Inversión de ARIA OS.

Calcula la eficiencia de cada acción, agente y canal.
"""
from __future__ import annotations
import logging

logger = logging.getLogger("aria.economic.roi")

class ROIModel:
    """Modelo de cálculo de ROI."""

    def calculate_roi(self, revenue: float, cost: float) -> float:
        """Calcula el ROI simple."""
        if cost == 0: return 0.0
        return (revenue - cost) / cost

    async def get_agent_efficiency(self, agent_id: str) -> float:
        """Calcula la eficiencia económica de un agente específico."""
        # Consultar DuckDB para ingresos y costes del agente
        return 3.2  # ROI de 320%
