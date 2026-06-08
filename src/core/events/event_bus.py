import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("megan.core.events")

class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class EventType(Enum):
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    RUNTIME_TICK = "runtime.tick"
    GOAL_CREATED = "goal.created"
    GOAL_COMPLETED = "goal.completed"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    AGENT_MESSAGE = "agent.message"
    MEMORY_UPDATE = "memory.update"
    EXTERNAL_INPUT = "external.input"
    ERROR = "system.error"

@dataclass
class Event:
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)
    source: Optional[str] = None
    event_id: Optional[str] = None

class EventBus:
    """Bus de eventos asíncrono para la comunicación entre componentes de MEGAN."""
    
    def __init__(self):
        self._subscribers: Dict[EventType, Set[Callable]] = {t: set() for t in EventType}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running: bool = False
        self._loop_task: Optional[asyncio.Task] = None

    def subscribe(self, event_type: EventType, callback: Callable):
        """Suscribe un callback a un tipo de evento."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = set()
        self._subscribers[event_type].add(callback)
        logger.debug(f"Subscribed {callback.__name__} to {event_type.value}")

    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Elimina una suscripción."""
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Unsubscribed {callback.__name__} from {event_type.value}")

    async def publish(self, event: Event):
        """Publica un evento en el bus."""
        await self._queue.put(event)
        logger.debug(f"Published event: {event.type.value} from {event.source}")

    async def _process_events(self):
        """Bucle principal de procesamiento de eventos."""
        while self._running:
            try:
                event = await self._queue.get()
                subscribers = self._subscribers.get(event.type, set())
                
                if subscribers:
                    tasks = [asyncio.create_task(callback(event)) for callback in subscribers]
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing event: {e}")

    async def start(self):
        """Inicia el bus de eventos."""
        if not self._running:
            self._running = True
            self._loop_task = asyncio.create_task(self._process_events())
            logger.info("Event Bus started")

    async def stop(self):
        """Detiene el bus de eventos."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("Event Bus stopped")
