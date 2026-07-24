"""
analytics_engine.py — Economic data analysis for ARIA AI.

Integrates DuckDB for ultra-fast analytical processing:
  - Real-time revenue and ROI metrics
  - Cohort and attribution analysis
  - Instant executive reporting

ARIA uses DuckDB to turn raw data into business intelligence.

Reference: https://duckdb.org/docs/api/python/overview
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("aria.analytics")

# ── DuckDB import with fallback ────────────────────────────────────────────
try:
    import duckdb

    DUCKDB_AVAILABLE = True
    logger.info("[DuckDB] Library loaded successfully.")
except ImportError:
    DUCKDB_AVAILABLE = False
    logger.warning("[DuckDB] duckdb not installed.")


class AriaAnalyticsEngine:
    """
    ARIA's analytics engine.
    Uses DuckDB for fast OLAP queries over the organization's data.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = None

        if DUCKDB_AVAILABLE:
            try:
                self._conn = duckdb.connect(self.db_path)
                logger.info("[Analytics] DuckDB connection established (%s)", db_path)
            except Exception as exc:
                logger.error("[Analytics] Error connecting to DuckDB: %s", exc)

    async def run_analysis(self, query: str) -> pd.DataFrame:
        """Runs an analytical query and returns a Pandas DataFrame."""
        if not self._conn:
            logger.warning("[Analytics] DuckDB not available.")
            return pd.DataFrame()

        try:
            return self._conn.execute(query).df()
        except Exception as exc:
            logger.error("[Analytics] Error in analytical query: %s", exc)
            return pd.DataFrame()

    async def summarize_revenue(self):
        """Generates an ultra-fast revenue summary."""
        query = (
            "SELECT product, SUM(amount) as total FROM sales GROUP BY product ORDER BY total DESC"
        )
        return await self.run_analysis(query)


# ── Singleton ───────────────────────────────────────────────────────────────
_analytics_instance: AriaAnalyticsEngine | None = None


def get_analytics_engine() -> AriaAnalyticsEngine:
    """Returns the analytics engine singleton."""
    global _analytics_instance
    if _analytics_instance is None:
        _analytics_instance = AriaAnalyticsEngine()
    return _analytics_instance
