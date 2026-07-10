"""
analytics_engine.py — Análisis de Datos Económicos para ARIA AI.

Integra DuckDB para procesamiento analítico ultra-rápido:
  - Métricas de ingresos y ROI en tiempo real
  - Análisis de cohortes y atribución
  - Reporting ejecutivo instantáneo

ARIA utiliza DuckDB para transformar datos crudos en inteligencia de negocio.

Referencia: https://duckdb.org/docs/api/python/overview
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("aria.analytics")

# ── DuckDB Import con fallback ───────────────────────────────────────────────
try:
    import duckdb

    DUCKDB_AVAILABLE = True
    logger.info("[DuckDB] Librería cargada correctamente.")
except ImportError:
    DUCKDB_AVAILABLE = False
    logger.warning("[DuckDB] duckdb no instalado.")


class AriaAnalyticsEngine:
    """
    Motor analítico de ARIA.
    Utiliza DuckDB para consultas OLAP rápidas sobre los datos de la organización.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = None

        if DUCKDB_AVAILABLE:
            try:
                self._conn = duckdb.connect(self.db_path)
                logger.info("[Analytics] Conexión DuckDB establecida (%s)", db_path)
            except Exception as exc:
                logger.error("[Analytics] Error conectando a DuckDB: %s", exc)

    async def run_analysis(self, query: str) -> pd.DataFrame:
        """Ejecuta una consulta analítica y retorna un DataFrame de Pandas."""
        if not self._conn:
            logger.warning("[Analytics] DuckDB no disponible.")
            return pd.DataFrame()

        try:
            return self._conn.execute(query).df()
        except Exception as exc:
            logger.error("[Analytics] Error en query analítica: %s", exc)
            return pd.DataFrame()

    async def summarize_revenue(self):
        """Genera un resumen de ingresos ultra-rápido."""
        query = (
            "SELECT product, SUM(amount) as total FROM sales GROUP BY product ORDER BY total DESC"
        )
        return await self.run_analysis(query)


# ── Singleton ────────────────────────────────────────────────────────────────
_analytics_instance: AriaAnalyticsEngine | None = None


def get_analytics_engine() -> AriaAnalyticsEngine:
    """Retorna el singleton del motor analítico."""
    global _analytics_instance
    if _analytics_instance is None:
        _analytics_instance = AriaAnalyticsEngine()
    return _analytics_instance
