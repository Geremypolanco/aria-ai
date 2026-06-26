
import logging
from typing import Any, Dict, List, Callable, Optional
from enum import Enum

logger = logging.getLogger("aria.state_graph")

class AgentState(Enum):
    """Estados posibles de un agente autónomo."""
    IDLE = "idle"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    EXECUTING = "executing"
    LEARNING = "learning"
    ERROR = "error"

class StateGraph:
    """
    Grafo de Estado inspirado en LangGraph.
    
    Define transiciones entre estados y permite ciclos autónomos:
    SCANNING → ANALYZING → DECIDING → EXECUTING → LEARNING → SCANNING
    """

    def __init__(self, name: str = "AriaStateGraph"):
        self.name = name
        self.nodes = {}  # Estado → función
        self.edges = {}  # Estado → [Estados siguientes]
        self.current_state = AgentState.IDLE
        self.state_history = []

    def add_node(self, state: AgentState, handler: Callable) -> None:
        """Añade un nodo (estado) con su manejador."""
        self.nodes[state] = handler
        logger.info(f"[StateGraph] Nodo añadido: {state.value}")

    def add_edge(self, from_state: AgentState, to_state: AgentState) -> None:
        """Añade una transición entre estados."""
        if from_state not in self.edges:
            self.edges[from_state] = []
        self.edges[from_state].append(to_state)
        logger.info(f"[StateGraph] Arista: {from_state.value} → {to_state.value}")

    def add_cycle(self, states: List[AgentState]) -> None:
        """Añade un ciclo de estados (para autonomía)."""
        for i in range(len(states)):
            next_state = states[(i + 1) % len(states)]
            self.add_edge(states[i], next_state)

    async def execute_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta un ciclo completo del grafo."""
        logger.info(f"[StateGraph] Iniciando ciclo desde {self.current_state.value}")
        
        while True:
            # Ejecutar el nodo actual
            if self.current_state in self.nodes:
                handler = self.nodes[self.current_state]
                result = await handler(context)
                
                # Registrar en historial
                self.state_history.append({
                    "state": self.current_state.value,
                    "result": result
                })
                
                # Actualizar contexto
                context.update(result)
            
            # Transicionar al siguiente estado
            next_states = self.edges.get(self.current_state, [])
            if not next_states:
                logger.info(f"[StateGraph] Ciclo completado. Estado final: {self.current_state.value}")
                break
            
            self.current_state = next_states[0]
        
        return context

    def get_state_history(self) -> List[Dict[str, Any]]:
        """Retorna el historial de estados ejecutados."""
        return self.state_history
