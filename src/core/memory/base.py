import abc
from typing import Any, Dict, List, Optional

class MemoryStore(abc.ABC):
    """Interfaz base para todos los sistemas de almacenamiento de memoria en MEGAN."""
    
    @abc.abstractmethod
    async def store(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None):
        """Almacena un dato en la memoria."""
        pass

    @abc.abstractmethod
    async def retrieve(self, key: str) -> Optional[Any]:
        """Recupera un dato por su clave."""
        pass

    @abc.abstractmethod
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Busca datos relevantes basados en una consulta (semántica o textual)."""
        pass

    @abc.abstractmethod
    async def clear(self):
        """Limpia el almacenamiento de memoria."""
        pass
