import logging
from typing import Dict, Any

from src.agents.base_agent import BaseAgent
from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("megan.agents.orchestration")

class OrchestrationAgent(BaseAgent):
    """Agente central de orquestación de MEGAN."""
    
    def __init__(self, event_bus: EventBus):
        super().__init__(name="orchestrator", event_bus=event_bus)
        self._active_tasks = {}

    async def _subscribe_to_events(self):
        self.event_bus.subscribe(EventType.EXTERNAL_INPUT, self.process_event)
        self.event_bus.subscribe(EventType.TASK_COMPLETED, self.process_event)
        self.event_bus.subscribe(EventType.AGENT_MESSAGE, self.process_event)

    async def process_event(self, event: Event):
        """Maneja la lógica de orquestación basada en eventos."""
        if event.type == EventType.EXTERNAL_INPUT:
            await self._handle_external_input(event.payload)
        elif event.type == EventType.TASK_COMPLETED:
            await self._handle_task_completion(event.payload)
        elif event.type == EventType.AGENT_MESSAGE:
            if event.payload.get("target") == self.name:
                await self._handle_direct_message(event)

    async def _handle_external_input(self, payload: Dict[str, Any]):
        """Decide qué hacer con la entrada externa (ej. mensaje de usuario)."""
        content = payload.get("content", "")
        logger.info(f"Orchestrator handling input: {content}")
        
        # Simulación de delegación a un Planner Agent (que implementaremos luego)
        await self.event_bus.publish(Event(
            type=EventType.GOAL_CREATED,
            payload={"goal": content, "status": "pending"},
            source=self.name
        ))

    async def _handle_task_completion(self, payload: Dict[str, Any]):
        task_id = payload.get("task_id")
        logger.info(f"Task {task_id} completed. Updating world state...")

    async def _handle_direct_message(self, event: Event):
        logger.info(f"Orchestrator received direct message from {event.source}")
