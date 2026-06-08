import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("megan.agents.base")

class BaseAgent(ABC):
    """Clase base para todos los agentes especializados de MEGAN."""
    
    def __init__(self, name: str, event_bus: EventBus):
        self.name = name
        self.event_bus = event_bus
        self._is_active = False

    async def start(self):
        """Inicia el agente y sus suscripciones."""
        if not self._is_active:
            self._is_active = True
            await self._subscribe_to_events()
            logger.info(f"Agent {self.name} started")

    async def stop(self):
        """Detiene el agente."""
        self._is_active = False
        logger.info(f"Agent {self.name} stopped")

    @abstractmethod
    async def _subscribe_to_events(self):
        """Define las suscripciones a eventos específicas del agente."""
        pass

    async def send_message(self, target: str, content: Any, metadata: Optional[Dict[str, Any]] = None):
        """Envía un mensaje a otro agente o componente vía Event Bus."""
        await self.event_bus.publish(Event(
            type=EventType.AGENT_MESSAGE,
            payload={
                "target": target,
                "content": content,
                "metadata": metadata or {}
            },
            source=self.name
        ))

    @abstractmethod
    async def process_event(self, event: Event):
        """Procesa un evento recibido del bus."""
        pass
