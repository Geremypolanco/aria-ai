import logging
from typing import Dict, Any

from src.agents.base_agent import BaseAgent
from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("megan.agents.planner")

class PlannerAgent(BaseAgent):
    """Agente encargado de la planificación y descomposición de objetivos."""
    
    def __init__(self, event_bus: EventBus):
        super().__init__(name="planner", event_bus=event_bus)

    async def _subscribe_to_events(self):
        self.event_bus.subscribe(EventType.GOAL_CREATED, self.process_event)

    async def process_event(self, event: Event):
        if event.type == EventType.GOAL_CREATED:
            await self._decompose_goal(event.payload)

    async def _decompose_goal(self, payload: Dict[str, Any]):
        goal = payload.get("goal")
        logger.info(f"Planner decomposing goal: {goal}")
        
        # Simulación de descomposición en tareas
        tasks = [
            {"id": "t1", "description": "Investigar el tema", "agent": "researcher"},
            {"id": "t2", "description": "Generar contenido", "agent": "coder"}
        ]
        
        for task in tasks:
            await self.event_bus.publish(Event(
                type=EventType.TASK_STARTED,
                payload=task,
                source=self.name
            ))
