from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class BaseTool(ABC):
    """Interfaz base para todas las herramientas de MEGAN."""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Ejecuta la lógica de la herramienta."""
        pass

class ToolRegistry:
    """Registro centralizado de herramientas disponibles."""
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, str]]:
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]
