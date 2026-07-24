import logging
from datetime import datetime
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.memory")


class EvolutionaryMemory:
    """
    Evolutionary Persistent Memory System (inspired by Mem0).

    It's not just storage. It's a system that:
    1. Learns from every interaction
    2. Evolves its strategies
    3. Remembers what worked and what didn't
    4. Continuously improves
    """

    def __init__(self):
        self.ai = get_ai_client()
        self.memory_store = {}  # In production: Qdrant vector DB
        self.learning_log = []

    async def record_interaction(
        self,
        interaction_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        success: bool,
        roi: float = 0.0,
    ) -> dict[str, Any]:
        """Records an interaction and extracts learnings."""

        record = {
            "timestamp": datetime.now().isoformat(),
            "type": interaction_type,
            "input": input_data,
            "output": output_data,
            "success": success,
            "roi": roi,
        }

        # Extract insights with AI
        if not success or roi > 0:
            insight = await self._extract_insight(record)
            record["insight"] = insight
            self.learning_log.append(insight)

        # Save to memory
        key = f"{interaction_type}_{len(self.memory_store)}"
        self.memory_store[key] = record

        logger.info(f"[Memory] Recorded interaction: {interaction_type} (ROI: ${roi})")
        return record

    async def _extract_insight(self, record: dict[str, Any]) -> dict[str, Any]:
        """Extracts learnings from an interaction."""
        prompt = f"""
        RECORDED INTERACTION:
        Type: {record['type']}
        Success: {record['success']}
        ROI: ${record['roi']}
        Input: {record['input']}
        Output: {record['output']}

        What did we learn?
        1. What worked?
        2. What didn't work?
        3. How can we improve next time?

        Respond in JSON with: what_worked, what_failed, improvement_strategy
        """

        insight = await self.ai.complete_json(
            system="You are a continuous learning system. Extract insights from every interaction.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return insight if insight else {}

    async def retrieve_similar_memories(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieves similar memories (in production: vector search with Qdrant)."""
        # Simplified implementation: search by type
        results = []
        for key, record in list(self.memory_store.items())[:top_k]:
            if record.get("success"):
                results.append(record)
        return results

    async def get_learned_strategies(self) -> dict[str, Any]:
        """Returns the strategies learned so far."""
        return {
            "total_interactions": len(self.memory_store),
            "successful_interactions": sum(
                1 for r in self.memory_store.values() if r.get("success")
            ),
            "total_roi_generated": sum(r.get("roi", 0) for r in self.memory_store.values()),
            "learnings": self.learning_log[-10:],  # Last 10 learnings
        }
