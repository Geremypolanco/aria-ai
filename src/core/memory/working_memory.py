import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from src.core.memory.base import MemoryStore

logger = logging.getLogger("megan.core.memory.working")

class WorkingMemory(MemoryStore):
    """Memoria de trabajo (Working Memory) de MEGAN, volátil y rápida."""
    
    def __init__(self, capacity: int = 100):
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._capacity = capacity
        self._access_history: List[str] = []

    async def store(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None):
        """Almacena datos en la memoria de trabajo."""
        if len(self._storage) >= self._capacity:
            # Eliminar el elemento menos recientemente usado (LRU)
            if self._access_history:
                lru_key = self._access_history.pop(0)
                self._storage.pop(lru_key, None)
                logger.debug(f"Working Memory capacity reached. Evicted: {lru_key}")

        self._storage[key] = {
            "value": value,
            "metadata": metadata or {},
            "timestamp": datetime.now()
        }
        if key in self._access_history:
            self._access_history.remove(key)
        self._access_history.append(key)
        logger.debug(f"Stored in Working Memory: {key}")

    async def retrieve(self, key: str) -> Optional[Any]:
        """Recupera datos de la memoria de trabajo."""
        if key in self._storage:
            if key in self._access_history:
                self._access_history.remove(key)
            self._access_history.append(key)
            return self._storage[key]["value"]
        return None

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Búsqueda simple por coincidencia de texto en claves y metadatos."""
        results = []
        query_lower = query.lower()
        
        for key, data in self._storage.items():
            if query_lower in key.lower() or any(query_lower in str(v).lower() for v in data["metadata"].values()):
                results.append({
                    "key": key,
                    "value": data["value"],
                    "metadata": data["metadata"],
                    "timestamp": data["timestamp"]
                })
                if len(results) >= limit:
                    break
        return results

    async def clear(self):
        """Limpia la memoria de trabajo."""
        self._storage.clear()
        self._access_history.clear()
        logger.info("Working Memory cleared")
