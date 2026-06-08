import asyncio
import logging
import sys
import os

# Añadir el directorio raíz al path para importaciones
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.events.event_bus import EventBus, Event, EventType
from src.core.runtime.loop import RuntimeLoop
from src.core.memory.working_memory import WorkingMemory
from src.core.memory.persistent_memory import PersistentMemory
from src.agents.orchestration_agent import OrchestrationAgent
from src.agents.planner_agent import PlannerAgent
from src.cognition.reflection_engine import ReflectionEngine

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("megan.main")

async def main():
    logger.info("🚀 Starting MEGAN Integrated Cognitive Architecture...")
    
    # 1. Capa de Eventos
    event_bus = EventBus()
    await event_bus.start()
    
    # 2. Capa de Memoria
    working_memory = WorkingMemory(capacity=100)
    persistent_memory = PersistentMemory(db_path="megan_production.db")
    await persistent_memory.initialize()
    
    # 3. Capa Cognitiva
    reflection = ReflectionEngine(event_bus)
    await reflection.start()
    
    # 4. Capa de Agentes
    orchestrator = OrchestrationAgent(event_bus)
    planner = PlannerAgent(event_bus)
    
    await orchestrator.start()
    await planner.start()
    
    # 5. Capa de Ejecución
    runtime = RuntimeLoop(event_bus, tick_interval=5.0)
    await runtime.start()
    
    logger.info("✅ MEGAN is online and autonomous.")
    
    # Simular una entrada compleja
    await event_bus.publish(Event(
        type=EventType.EXTERNAL_INPUT,
        payload={"content": "Lanzar una colección de arte digital inspirada en Marte en Shopify"},
        source="user_interface"
    ))
    
    try:
        # Dejar que el sistema procese e interactúe
        await asyncio.sleep(10)
        
        # Simular finalización de una tarea para ver la reflexión
        await event_bus.publish(Event(
            type=EventType.TASK_COMPLETED,
            payload={"task_id": "t1", "status": "success", "agent": "researcher"},
            source="researcher_agent"
        ))
        
        await asyncio.sleep(2)
    except KeyboardInterrupt:
        logger.info("Shutting down MEGAN...")
    finally:
        await runtime.stop()
        await planner.stop()
        await orchestrator.stop()
        reflection.event_bus.unsubscribe(EventType.TASK_COMPLETED, reflection.on_task_completed)
        reflection.event_bus.unsubscribe(EventType.ERROR, reflection.on_error)
        await event_bus.stop()
        logger.info("MEGAN offline.")

if __name__ == "__main__":
    asyncio.run(main())
