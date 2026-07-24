import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger("aria.state_graph")


class AgentState(Enum):
    """Possible states of an autonomous agent."""

    IDLE = "idle"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    EXECUTING = "executing"
    LEARNING = "learning"
    ERROR = "error"


class StateGraph:
    """
    State Graph inspired by LangGraph.

    Defines transitions between states and enables autonomous cycles:
    SCANNING → ANALYZING → DECIDING → EXECUTING → LEARNING → SCANNING
    """

    def __init__(self, name: str = "AriaStateGraph"):
        self.name = name
        self.nodes = {}  # State → function
        self.edges = {}  # State → [Next states]
        self.current_state = AgentState.IDLE
        self.state_history = []

    def add_node(self, state: AgentState, handler: Callable) -> None:
        """Adds a node (state) with its handler."""
        self.nodes[state] = handler
        logger.info(f"[StateGraph] Node added: {state.value}")

    def add_edge(self, from_state: AgentState, to_state: AgentState) -> None:
        """Adds a transition between states."""
        if from_state not in self.edges:
            self.edges[from_state] = []
        self.edges[from_state].append(to_state)
        logger.info(f"[StateGraph] Edge: {from_state.value} → {to_state.value}")

    def add_cycle(self, states: list[AgentState]) -> None:
        """Adds a cycle of states (for autonomy)."""
        for i in range(len(states)):
            next_state = states[(i + 1) % len(states)]
            self.add_edge(states[i], next_state)

    async def execute_cycle(self, context: dict[str, Any]) -> dict[str, Any]:
        """Executes a full cycle of the graph."""
        logger.info(f"[StateGraph] Starting cycle from {self.current_state.value}")

        while True:
            # Execute the current node
            if self.current_state in self.nodes:
                handler = self.nodes[self.current_state]
                result = await handler(context)

                # Log to history
                self.state_history.append({"state": self.current_state.value, "result": result})

                # Update context
                context.update(result)

            # Transition to the next state
            next_states = self.edges.get(self.current_state, [])
            if not next_states:
                logger.info(
                    f"[StateGraph] Cycle completed. Final state: {self.current_state.value}"
                )
                break

            self.current_state = next_states[0]

        return context

    def get_state_history(self) -> list[dict[str, Any]]:
        """Returns the history of executed states."""
        return self.state_history
