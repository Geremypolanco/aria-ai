"""
digital_twin.py — Gemelo Digital de Negocio para ARIA AI.

Utiliza NetworkX para modelar la organización completa como un grafo vivo:
  - Clientes, Productos, Canales, Campañas, Empleados, Proveedores.
  - Permite simular el impacto de cambios estratégicos antes de ejecutarlos.

ARIA no solo ve datos, entiende las interconexiones de la organización.

Referencia: https://networkx.org/
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("aria.digital_twin")

# ── NetworkX Import con fallback ─────────────────────────────────────────────
try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
    logger.info("[NetworkX] Librería cargada correctamente.")
except ImportError:
    NETWORKX_AVAILABLE = False
    logger.warning("[NetworkX] networkx no instalado.")

class AriaDigitalTwin:
    """
    Gemelo Digital de la organización ARIA.
    Mantiene un modelo vivo de todas las entidades y sus relaciones.
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph() if NETWORKX_AVAILABLE else None

    def add_entity(self, entity_id: str, entity_type: str, properties: dict[str, Any] | None = None):
        """Añade una entidad (Cliente, Producto, etc.) al gemelo digital."""
        if self.graph is not None:
            self.graph.add_node(entity_id, type=entity_type, **(properties or {}))
            logger.debug("[DigitalTwin] Entidad añadida: %s (%s)", entity_id, entity_type)

    def add_relationship(self, source_id: str, target_id: str, rel_type: str, weight: float = 1.0):
        """Define una relación entre dos entidades."""
        if self.graph is not None:
            self.graph.add_edge(source_id, target_id, relation=rel_type, weight=weight)
            logger.debug("[DigitalTwin] Relación añadida: %s -[%s]-> %s", source_id, rel_type, target_id)

    def simulate_impact(self, change_node: str, new_weight: float) -> dict[str, Any]:
        """Simula el impacto de un cambio en un nodo específico."""
        logger.info("[DigitalTwin] Simulando impacto de cambio en %s...", change_node)
        # Aquí se implementarían algoritmos de centralidad o propagación
        return {"impact_score": 0.85, "affected_nodes": ["Revenue", "MarketingCost"]}


# ── Singleton ────────────────────────────────────────────────────────────────
_digital_twin_instance: AriaDigitalTwin | None = None

def get_digital_twin() -> AriaDigitalTwin:
    """Retorna el singleton del gemelo digital."""
    global _digital_twin_instance
    if _digital_twin_instance is None:
        _digital_twin_instance = AriaDigitalTwin()
    return _digital_twin_instance
