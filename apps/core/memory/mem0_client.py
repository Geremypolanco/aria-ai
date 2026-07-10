"""
mem0_client.py — Memoria Inteligente y Adaptativa para ARIA AI.

Integra Mem0 para que ARIA pueda:
  - Recordar preferencias de usuario de forma persistente
  - Aprender de cada interacción pasada
  - Personalizar respuestas basadas en el historial histórico
  - Gestionar una memoria a largo plazo que evoluciona con el usuario

Referencia: https://github.com/mem0ai/mem0
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.mem0")

# ── Mem0 Import con fallback ─────────────────────────────────────────────────
try:
    from mem0 import Memory

    MEM0_AVAILABLE = True
    logger.info("[Mem0] Librería cargada correctamente.")
except ImportError:
    MEM0_AVAILABLE = False
    logger.warning("[Mem0] mem0 no instalado. Usando fallback.")


class AriaMem0Client:
    """
    Cliente de Memoria Mem0 para ARIA.
    Permite el aprendizaje continuo sobre el usuario.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {
            "vector_store": {"provider": "qdrant", "config": {"host": "localhost", "port": 6333}},
        }
        self._memory = None

        if MEM0_AVAILABLE:
            try:
                self._memory = Memory.from_config(self.config)
                logger.info("[Mem0] Inicializado con éxito.")
            except Exception as exc:
                logger.error("[Mem0] Error inicializando: %s", exc)

    async def add_memory(self, user_id: str, content: str, metadata: dict[str, Any] | None = None):
        """Añade un hecho o interacción a la memoria del usuario."""
        if not self._memory:
            logger.debug("[Mem0] Memoria no disponible. Saltando guardado.")
            return

        try:
            self._memory.add(content, user_id=user_id, metadata=metadata or {})
            logger.info("[Mem0] Memoria añadida para usuario %s", user_id)
        except Exception as exc:
            logger.error("[Mem0] Error añadiendo memoria: %s", exc)

    async def search_memories(self, user_id: str, query: str) -> list[dict[str, Any]]:
        """Busca en la memoria del usuario basada en una consulta."""
        if not self._memory:
            return []

        try:
            return self._memory.search(query, user_id=user_id)
        except Exception as exc:
            logger.error("[Mem0] Error buscando en memoria: %s", exc)
            return []

    async def get_all_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Retorna todos los hechos recordados para un usuario."""
        if not self._memory:
            return []

        try:
            return self._memory.get_all(user_id=user_id)
        except Exception as exc:
            logger.error("[Mem0] Error obteniendo memorias: %s", exc)
            return []


# ── Singleton ────────────────────────────────────────────────────────────────
_mem0_instance: AriaMem0Client | None = None


def get_mem0_client() -> AriaMem0Client:
    """Retorna el singleton del cliente Mem0."""
    global _mem0_instance
    if _mem0_instance is None:
        _mem0_instance = AriaMem0Client()
    return _mem0_instance
