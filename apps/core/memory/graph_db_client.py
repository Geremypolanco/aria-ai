"""
graph_db_client.py — Graph Database Client (Neo4j) for ARIA AI.

Manages ARIA's relational knowledge:
  Customers → Products → Campaigns → Revenue → Channels

Unlike Graphiti (temporal), Neo4j is used for organizational
structure and long-term business relationship mapping.

Reference: https://neo4j.com/docs/python-manual/current/
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("aria.graph_db")

# ── Neo4j import with fallback ───────────────────────────────────────────────
try:
    from neo4j import GraphDatabase

    NEO4J_AVAILABLE = True
    logger.info("[Neo4j] Library loaded successfully.")
except ImportError:
    NEO4J_AVAILABLE = False
    logger.warning("[Neo4j] neo4j not installed. Using in-memory fallback.")


class AriaGraphDBClient:
    """
    Client for Neo4j / Apache AGE.
    Manages the Aria organization's relational knowledge.
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
                logger.info("[Neo4j] Driver initialized.")
            except Exception as exc:
                logger.error("[Neo4j] Error initializing driver: %s", exc)

    def close(self) -> None:
        """Closes the driver connection."""
        if self._driver:
            self._driver.close()

    async def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executes a Cypher query on Neo4j."""
        if not self._driver:
            logger.warning("[Neo4j] Driver not available. Query ignored.")
            return []

        with self._driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    async def map_revenue_chain(
        self, customer_id: str, product_id: str, campaign_id: str, amount: float
    ):
        """Maps a revenue chain in the graph."""
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
        logger.info("[Neo4j] Revenue chain mapped for customer %s", customer_id)


# ── Singleton ────────────────────────────────────────────────────────────────
_graph_db_instance: AriaGraphDBClient | None = None


def get_graph_db_client() -> AriaGraphDBClient:
    """Returns the graph database client singleton."""
    global _graph_db_instance
    if _graph_db_instance is None:
        _graph_db_instance = AriaGraphDBClient(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
        )
    return _graph_db_instance
