import asyncio
import logging
import time
from typing import Optional

from src.core.events.event_bus import EventBus, Event, EventType, EventPriority

logger = logging.getLogger("megan.core.runtime")

class RuntimeLoop:
    """Bucle de ejecución persistente (Persistent Runtime Loop) de MEGAN."""
    
    def __init__(self, event_bus: EventBus, tick_interval: float = 1.0):
        self.event_bus = event_bus
        self.tick_interval = tick_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._start_time: Optional[float] = None
        self._tick_count = 0

    async def _loop(self):
        """Bucle principal que genera eventos de 'tick'."""
        logger.info(f"Runtime Loop started with interval {self.tick_interval}s")
        self._start_time = time.time()
        
        while self._running:
            try:
                self._tick_count += 1
                
                # Publicar evento de tick para que otros sistemas reaccionen
                await self.event_bus.publish(Event(
                    type=EventType.RUNTIME_TICK,
                    payload={
                        "tick_count": self._tick_count,
                        "uptime": time.time() - self._start_time
                    },
                    priority=EventPriority.LOW,
                    source="runtime_loop"
                ))
                
                await asyncio.sleep(self.tick_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Runtime Loop: {e}")
                await asyncio.sleep(self.tick_interval)

    async def start(self):
        """Inicia el bucle de ejecución."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())
            
            await self.event_bus.publish(Event(
                type=EventType.SYSTEM_STARTUP,
                payload={"timestamp": time.time()},
                priority=EventPriority.CRITICAL,
                source="runtime_loop"
            ))

    async def stop(self):
        """Detiene el bucle de ejecución."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.event_bus.publish(Event(
            type=EventType.SYSTEM_SHUTDOWN,
            payload={"timestamp": time.time(), "ticks": self._tick_count},
            priority=EventPriority.CRITICAL,
            source="runtime_loop"
        ))
        logger.info("Runtime Loop stopped")

    @property
    def uptime(self) -> float:
        if self._start_time:
            return time.time() - self._start_time
        return 0.0
