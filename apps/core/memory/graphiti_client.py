"""
graphiti_client.py — Memoria Temporal en Grafo para ARIA AI con Graphiti.

Graphiti construye grafos de conocimiento temporales que permiten a ARIA:
  - Rastrear relaciones entre entidades a lo largo del tiempo
  - Atribuir ingresos a través de cadenas causales completas:
      video → lead → email → venta → renovación
  - Consultar qué era verdad en cualquier punto del tiempo
  - Detectar cambios en relaciones y estrategias

Integración con Aria:
  - Extiende EvolutionaryMemory con capacidades de grafo temporal
  - Se conecta a FalkorDB (vía Docker) o Neo4j
  - Complementa la memoria Supabase/Redis existente

Referencia: https://github.com/getzep/graphiti
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.graphiti_client")

# ── Graphiti Import con fallback ─────────────────────────────────────────────
try:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType  # noqa: F401
    from graphiti_core.search.search_config_recipes import (
        EDGE_HYBRID_SEARCH_RRF,  # noqa: F401
        NODE_HYBRID_SEARCH_RRF,  # noqa: F401
    )

    GRAPHITI_AVAILABLE = True
    logger.info("[Graphiti] Librería cargada correctamente.")
except ImportError:
    GRAPHITI_AVAILABLE = False
    logger.warning(
        "[Graphiti] graphiti-core no instalado. "
        "Usando implementación de grafo en memoria. "
        "Instala con: pip install graphiti-core[falkordb]"
    )
    Graphiti = None  # type: ignore[assignment,misc]


# ── Implementación Fallback de Grafo en Memoria ──────────────────────────────


class InMemoryGraph:
    """
    Grafo de conocimiento en memoria como fallback de Graphiti.
    Mantiene la misma interfaz para compatibilidad.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, dict] = {}
        self._edges: list[dict] = []
        self._episodes: list[dict] = []

    async def add_episode(
        self,
        name: str,
        episode_body: str,
        source_description: str = "",
        reference_time: datetime | None = None,
        source: str = "text",
    ) -> None:
        episode = {
            "name": name,
            "body": episode_body,
            "source": source,
            "source_description": source_description,
            "timestamp": (reference_time or datetime.now(UTC)).isoformat(),
        }
        self._episodes.append(episode)
        logger.debug("[InMemoryGraph] Episodio añadido: %s", name)

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        query_lower = query.lower()
        results = []
        for ep in self._episodes:
            if query_lower in ep["body"].lower() or query_lower in ep["name"].lower():
                results.append(ep)
            if len(results) >= num_results:
                break
        return results

    async def close(self) -> None:
        pass


# ── Entidades de Negocio para ARIA AI ────────────────────────────────────────

# Tipos de entidades en el grafo de conocimiento de ARIA
ARIA_ENTITY_TYPES = {
    "Lead": "Prospecto o cliente potencial identificado",
    "Sale": "Venta completada con monto y fecha",
    "Product": "Producto digital o servicio ofrecido",
    "Campaign": "Campaña de marketing ejecutada",
    "Content": "Contenido creado (video, post, ebook, etc.)",
    "Revenue": "Ingreso generado con atribución",
    "Competitor": "Competidor analizado en el mercado",
    "Niche": "Nicho de mercado identificado",
    "Strategy": "Estrategia ejecutada con resultados",
    "Agent": "Agente de ARIA que ejecutó una acción",
}

# Tipos de relaciones temporales
ARIA_RELATION_TYPES = {
    "GENERATED": "Una entidad generó otra (content → lead)",
    "CONVERTED": "Una entidad se convirtió en otra (lead → sale)",
    "ATTRIBUTED_TO": "Un ingreso se atribuye a una fuente",
    "EXECUTED_BY": "Una acción fue ejecutada por un agente",
    "PART_OF": "Pertenece a una campaña o estrategia",
    "FOLLOWED_BY": "Secuencia temporal de eventos",
    "RENEWED": "Renovación de una venta anterior",
}


# ── Cliente Principal de Graphiti para ARIA ──────────────────────────────────


class AriaGraphitiClient:
    """
    Cliente de Graphiti para ARIA AI.

    Construye y consulta el grafo de conocimiento temporal de ARIA,
    permitiendo revenue attribution completa y análisis de relaciones
    causales entre acciones y resultados.

    Uso:
        client = AriaGraphitiClient()
        await client.initialize()

        # Registrar un evento de negocio
        await client.record_business_event(
            event_type="sale",
            entity_name="Ebook Fitness Pro",
            description="Venta de $27 USD generada por campaña de TikTok",
            metadata={"amount": 27.0, "source": "tiktok_campaign_001"}
        )

        # Consultar atribución de ingresos
        results = await client.query_revenue_attribution("TikTok")
    """

    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password",
        use_falkordb: bool = True,
        falkordb_host: str = "localhost",
        falkordb_port: int = 6379,
    ) -> None:
        self._graphiti: Any = None
        self._fallback: InMemoryGraph | None = None
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._use_falkordb = use_falkordb
        self._falkordb_host = falkordb_host
        self._falkordb_port = falkordb_port
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Inicializa la conexión con Graphiti (FalkorDB o Neo4j).
        Retorna True si se conectó correctamente, False si usa fallback.
        """
        if not GRAPHITI_AVAILABLE:
            logger.warning("[Graphiti] Usando grafo en memoria como fallback")
            self._fallback = InMemoryGraph()
            self._initialized = True
            return False

        try:
            if self._use_falkordb:
                # FalkorDB es más ligero y fácil de desplegar con Docker
                from graphiti_core.driver.falkordb_driver import FalkorDBDriver

                driver = FalkorDBDriver(
                    host=self._falkordb_host,
                    port=self._falkordb_port,
                )
                self._graphiti = Graphiti.from_driver(driver)
            else:
                # Neo4j para producción enterprise
                self._graphiti = Graphiti(
                    uri=self._neo4j_uri,
                    user=self._neo4j_user,
                    password=self._neo4j_password,
                )

            await self._graphiti.build_indices_and_constraints()
            self._initialized = True
            logger.info("[Graphiti] Conexión establecida correctamente")
            return True

        except Exception as exc:
            logger.warning("[Graphiti] Error conectando: %s — usando fallback", exc)
            self._fallback = InMemoryGraph()
            self._initialized = True
            return False

    async def record_business_event(
        self,
        event_type: str,
        entity_name: str,
        description: str,
        metadata: dict[str, Any] | None = None,
        reference_time: datetime | None = None,
    ) -> bool:
        """
        Registra un evento de negocio en el grafo temporal.

        Ejemplos:
            event_type="content_created", entity_name="Video TikTok Fitness"
            event_type="lead_generated", entity_name="Lead #1234"
            event_type="sale_completed", entity_name="Ebook Fitness Pro"
            event_type="revenue_attributed", entity_name="$27 USD"

        Args:
            event_type: Tipo de evento (content_created, lead_generated, sale_completed, etc.)
            entity_name: Nombre de la entidad involucrada
            description: Descripción detallada del evento
            metadata: Datos adicionales (amount, source, agent, etc.)
            reference_time: Timestamp del evento (default: ahora)

        Returns:
            True si se registró correctamente
        """
        if not self._initialized:
            await self.initialize()

        meta_str = ""
        if metadata:
            meta_str = " | ".join(f"{k}={v}" for k, v in metadata.items())

        episode_body = f"[{event_type.upper()}] {entity_name}: {description}"
        if meta_str:
            episode_body += f" | Metadata: {meta_str}"

        try:
            if self._graphiti:
                await self._graphiti.add_episode(
                    name=f"{event_type}_{entity_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    episode_body=episode_body,
                    source_description=f"ARIA AI - {event_type}",
                    reference_time=reference_time or datetime.now(UTC),
                    source="text",
                )
            elif self._fallback:
                await self._fallback.add_episode(
                    name=f"{event_type}_{entity_name}",
                    episode_body=episode_body,
                    source_description=f"ARIA AI - {event_type}",
                    reference_time=reference_time,
                )
            logger.info("[Graphiti] Evento registrado: %s | %s", event_type, entity_name)
            return True

        except Exception as exc:
            logger.error("[Graphiti] Error registrando evento: %s", exc)
            return False

    async def record_revenue_chain(
        self,
        chain: list[dict[str, Any]],
        total_revenue_usd: float,
    ) -> bool:
        """
        Registra una cadena completa de atribución de ingresos.

        Ejemplo de cadena:
            [
                {"type": "content", "name": "Video TikTok #42", "timestamp": "..."},
                {"type": "lead", "name": "Lead Juan García", "timestamp": "..."},
                {"type": "email", "name": "Email Secuencia #3", "timestamp": "..."},
                {"type": "sale", "name": "Ebook $27", "timestamp": "..."},
                {"type": "renewal", "name": "Renovación Mensual", "timestamp": "..."},
            ]

        Args:
            chain: Lista de eventos en orden cronológico
            total_revenue_usd: Total de ingresos atribuidos a esta cadena
        """
        if not chain:
            return False

        chain_description = " → ".join(
            f"{step.get('type', '?')}:{step.get('name', '?')}" for step in chain
        )

        return await self.record_business_event(
            event_type="revenue_chain",
            entity_name=f"Chain ${total_revenue_usd:.2f}",
            description=f"Cadena de atribución: {chain_description}",
            metadata={
                "total_revenue_usd": total_revenue_usd,
                "chain_length": len(chain),
                "first_touch": chain[0].get("name", ""),
                "last_touch": chain[-1].get("name", ""),
            },
        )

    async def query_revenue_attribution(
        self,
        source: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Consulta la atribución de ingresos para una fuente específica.

        Args:
            source: Fuente a consultar (ej: "TikTok", "email", "ebook")
            limit: Número máximo de resultados

        Returns:
            Lista de eventos relacionados con la fuente
        """
        if not self._initialized:
            await self.initialize()

        query = f"revenue attribution {source} sales conversion"

        try:
            if self._graphiti:
                results = await self._graphiti.search(query, num_results=limit)
                return [
                    {
                        "fact": r.fact if hasattr(r, "fact") else str(r),
                        "valid_at": (
                            r.valid_at.isoformat()
                            if hasattr(r, "valid_at") and r.valid_at
                            else None
                        ),
                        "source": source,
                    }
                    for r in results
                ]
            if self._fallback:
                return await self._fallback.search(query, num_results=limit)

        except Exception as exc:
            logger.error("[Graphiti] Error en query: %s", exc)

        return []

    async def query_competitor_landscape(
        self,
        niche: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Consulta el panorama de competidores para un nicho.

        Args:
            niche: Nicho a analizar
            limit: Número máximo de resultados
        """
        return await self.query_revenue_attribution(
            source=f"competitor {niche}",
            limit=limit,
        )

    async def get_knowledge_summary(self) -> dict[str, Any]:
        """Retorna un resumen del estado del grafo de conocimiento."""
        if not self._initialized:
            await self.initialize()

        if self._fallback:
            return {
                "backend": "in_memory_fallback",
                "total_episodes": len(self._fallback._episodes),
                "graphiti_available": GRAPHITI_AVAILABLE,
            }

        return {
            "backend": "falkordb" if self._use_falkordb else "neo4j",
            "graphiti_available": GRAPHITI_AVAILABLE,
            "initialized": self._initialized,
        }

    async def close(self) -> None:
        """Cierra la conexión con el grafo."""
        if self._graphiti:
            await self._graphiti.close()
        elif self._fallback:
            await self._fallback.close()


# ── Singleton ────────────────────────────────────────────────────────────────
_graphiti_instance: AriaGraphitiClient | None = None


def get_graphiti_client() -> AriaGraphitiClient:
    """Retorna el singleton del cliente Graphiti de ARIA."""
    global _graphiti_instance
    if _graphiti_instance is None:
        import os

        _graphiti_instance = AriaGraphitiClient(
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
            use_falkordb=os.getenv("USE_FALKORDB", "true").lower() == "true",
            falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
            falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
        )
    return _graphiti_instance
