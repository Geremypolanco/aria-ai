"""
graph_db_client.py — Cliente de Base de Datos de Grafos (Neo4j) para ARIA AI.

Permite gestionar el conocimiento relacional de ARIA:
  Clientes → Productos → Campañas → Ingresos → Canales

A diferencia de Graphiti (temporal), Neo4j se usa para la estructura
organizacional y el mapeo de relaciones de negocio de largo plazo.

Referencia: https://neo4j.com/docs/python-manual/current/
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("aria.graph_db")

# ── Neo4j Import con fallback ────────────────────────────────────────────────
try:
    from neo4j import GraphDatabase

    NEO4J_AVAILABLE = True
    logger.info("[Neo4j] Librería cargada correctamente.")
except ImportError:
    NEO4J_AVAILABLE = False
    logger.warning("[Neo4j] neo4j no instalado. Usando fallback en memoria.")


class AriaGraphDBClient:
    """
    Cliente para Neo4j / Apache AGE.
    Maneja el conocimiento relacional de la organización Aria.
    """

    def __init__(
        self, uri: str = "bolt://localhost:7687", user: str = "neo4j", password: str = "password"
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

        if NEO4J_AVAILABLE:
            try:
                self._driver = GraphDatabase.driver(uri, auth=(user, password))
                logger.info("[Neo4j] Driver inicializado.")
            except Exception as exc:
                logger.error("[Neo4j] Error inicializando driver: %s", exc)

    def close(self) -> None:
        """Cierra la conexión con el driver."""
        if self._driver:
            self._driver.close()

    async def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Ejecuta una consulta Cypher en Neo4j."""
        if not self._driver:
            logger.warning("[Neo4j] Driver no disponible. Query ignorada.")
            return []

        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    async def map_revenue_chain(
        self, customer_id: str, product_id: str, campaign_id: str, amount: float
    ):
        """Mapea una cadena de ingresos en el grafo."""
        query = (
            "MERGE (c:Customer {id: $customer_id}) "
            "MERGE (p:Product {id: $product_id}) "
            "MERGE (cam:Campaign {id: $campaign_id}) "
            "CREATE (c)-[:PURCHASED {amount: $amount, date: datetime()}]->(p) "
            "CREATE (p)-[:PART_OF]->(cam)"
        )
        await self.execute_query(
            query,
            {
                "customer_id": customer_id,
                "product_id": product_id,
                "campaign_id": campaign_id,
                "amount": amount,
            },
        )
        logger.info("[Neo4j] Cadena de ingresos mapeada para cliente %s", customer_id)


# ── Singleton ────────────────────────────────────────────────────────────────
_graph_db_instance: AriaGraphDBClient | None = None


def get_graph_db_client() -> AriaGraphDBClient:
    """Retorna el singleton del cliente de base de datos de grafos."""
    global _graph_db_instance
    if _graph_db_instance is None:
        _graph_db_instance = AriaGraphDBClient(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
        )
    return _graph_db_instance
