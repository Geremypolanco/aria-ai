import logging
from datetime import datetime
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.memory")


class EvolutionaryMemory:
    """
    Sistema de Memoria Persistente Evolutiva (inspirado en Mem0).

    No es solo almacenamiento. Es un sistema que:
    1. Aprende de cada interacción
    2. Evoluciona sus estrategias
    3. Recuerda qué funcionó y qué no
    4. Mejora continuamente
    """

    def __init__(self):
        self.ai = get_ai_client()
        self.memory_store = {}  # En producción: Qdrant vector DB
        self.learning_log = []

    async def record_interaction(
        self,
        interaction_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        success: bool,
        roi: float = 0.0,
    ) -> dict[str, Any]:
        """Registra una interacción y extrae aprendizajes."""

        record = {
            "timestamp": datetime.now().isoformat(),
            "type": interaction_type,
            "input": input_data,
            "output": output_data,
            "success": success,
            "roi": roi,
        }

        # Extraer insights con IA
        if not success or roi > 0:
            insight = await self._extract_insight(record)
            record["insight"] = insight
            self.learning_log.append(insight)

        # Guardar en memoria
        key = f"{interaction_type}_{len(self.memory_store)}"
        self.memory_store[key] = record

        logger.info(f"[Memory] Registrada interacción: {interaction_type} (ROI: ${roi})")
        return record

    async def _extract_insight(self, record: dict[str, Any]) -> dict[str, Any]:
        """Extrae aprendizajes de una interacción."""
        prompt = f"""
        INTERACCIÓN REGISTRADA:
        Tipo: {record['type']}
        Éxito: {record['success']}
        ROI: ${record['roi']}
        Entrada: {record['input']}
        Salida: {record['output']}

        ¿Qué aprendimos?
        1. ¿Qué funcionó?
        2. ¿Qué no funcionó?
        3. ¿Cómo mejorar la próxima vez?

        Responde en JSON con: what_worked, what_failed, improvement_strategy
        """

        insight = await self.ai.complete_json(
            system="Eres un sistema de aprendizaje continuo. Extrae insights de cada interacción.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return insight if insight else {}

    async def retrieve_similar_memories(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Recupera memorias similares (en producción: búsqueda vectorial con Qdrant)."""
        # Implementación simplificada: búsqueda por tipo
        results = []
        for key, record in list(self.memory_store.items())[:top_k]:
            if record.get("success"):
                results.append(record)
        return results

    async def get_learned_strategies(self) -> dict[str, Any]:
        """Retorna las estrategias aprendidas hasta ahora."""
        return {
            "total_interactions": len(self.memory_store),
            "successful_interactions": sum(
                1 for r in self.memory_store.values() if r.get("success")
            ),
            "total_roi_generated": sum(r.get("roi", 0) for r in self.memory_store.values()),
            "learnings": self.learning_log[-10:],  # Últimos 10 aprendizajes
        }
