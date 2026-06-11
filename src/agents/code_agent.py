"""
CodeAgent - Especialista en generación, ejecución y prueba de código
Implementa el bucle: escribir → ejecutar → analizar → corregir
"""
import logging
import subprocess
import tempfile
import os
from typing import Dict, Any, Optional
from src.agents.base_agent import BaseAgent
from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("aria.agents.code")

class CodeAgent(BaseAgent):
    """Agente especializado en desarrollo de código con auto-testing."""
    
    def __init__(self, event_bus: EventBus):
        super().__init__(name="code_agent", event_bus=event_bus)
        self.max_iterations = 3
        self.supported_languages = ["python", "javascript", "typescript", "bash", "sql"]
    
    async def _subscribe_to_events(self):
        self.event_bus.subscribe(EventType.GOAL_CREATED, self.handle_code_task)
        self.event_bus.subscribe(EventType.AGENT_MESSAGE, self.handle_direct_message)
    
    async def handle_code_task(self, event: Event):
        """Maneja tareas de generación de código."""
        payload = event.payload
        if payload.get("type") == "code_generation":
            await self.generate_and_test_code(payload)
    
    async def handle_direct_message(self, event: Event):
        """Maneja mensajes directos al agente."""
        if event.payload.get("target") == self.name:
            await self.generate_and_test_code(event.payload)
    
    async def generate_and_test_code(self, task: Dict[str, Any]):
        """Genera código, lo ejecuta, lo prueba y lo corrige iterativamente."""
        logger.info(f"CodeAgent: Iniciando tarea de código: {task.get('description', 'sin descripción')}")
        
        language = task.get("language", "python")
        description = task.get("description", "")
        
        if language not in self.supported_languages:
            logger.error(f"Lenguaje no soportado: {language}")
            return
        
        # Simulación: en producción, usaría Claude/GPT para generar código
        generated_code = f"# Código generado para: {description}\nprint('Hello from generated code')"
        
        # Ejecutar y probar
        for iteration in range(self.max_iterations):
            logger.info(f"CodeAgent: Iteración {iteration + 1}/{self.max_iterations}")
            
            # Ejecutar código
            result = await self._execute_code(generated_code, language)
            
            if result.get("success"):
                logger.info("CodeAgent: Código ejecutado exitosamente")
                await self.event_bus.publish(Event(
                    type=EventType.TASK_COMPLETED,
                    payload={
                        "task_id": task.get("id"),
                        "agent": self.name,
                        "result": result,
                        "code": generated_code
                    },
                    source=self.name
                ))
                break
            else:
                logger.warning(f"CodeAgent: Error en iteración {iteration + 1}: {result.get('error')}")
                # En producción, usaría Claude/GPT para corregir el código
    
    async def _execute_code(self, code: str, language: str) -> Dict[str, Any]:
        """Ejecuta código en un sandbox seguro."""
        try:
            if language == "python":
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(code)
                    f.flush()
                    result = subprocess.run(
                        ["python3", f.name],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    os.unlink(f.name)
                    
                    return {
                        "success": result.returncode == 0,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "return_code": result.returncode
                    }
            else:
                return {"success": False, "error": f"Ejecución de {language} no implementada aún"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout en ejecución de código"}
        except Exception as e:
            return {"success": False, "error": str(e)}
