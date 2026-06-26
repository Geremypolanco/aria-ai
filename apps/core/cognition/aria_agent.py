
import asyncio
import logging
import json
import re
from typing import Any, Dict, List, Optional
from apps.core.tools.ai_client import get_ai_client, AIModel
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.agent")

class AriaAgent:
    """
    Agente de Propósito General inspirado en Claude Code.
    Implementa un bucle ReAct (Reasoning + Acting) para ejecución autónoma.
    """

    def __init__(self, name: str = "Aria", identity: str = ""):
        self.name = name
        self.identity = identity or "Eres un Agente Autónomo de Ejecución Pura. Tu misión es resolver tareas complejas usando herramientas."
        self.ai = get_ai_client()
        self.max_steps = 15
        self.history = []

    async def run(self, task: str) -> Dict[str, Any]:
        """Ejecuta una tarea de forma autónoma hasta completarla o fallar."""
        logger.info(f"[AriaAgent] Iniciando tarea: {task}")
        self.history = [{"role": "user", "content": task}]
        
        for step in range(self.max_steps):
            # 1. RAZONAR Y DECIDIR ACCIÓN
            response = await self._think()
            if not response:
                return {"success": False, "error": "Fallo en el razonamiento de la IA"}

            thought = response.get("thought", "")
            tool_name = response.get("tool")
            tool_args = response.get("tool_args", {})
            reply = response.get("reply", "")

            logger.info(f"[Step {step+1}] Pensamiento: {thought}")

            # 2. SI HAY RESPUESTA FINAL, TERMINAR
            if not tool_name and reply:
                logger.info(f"[AriaAgent] Tarea completada: {reply}")
                return {"success": True, "output": reply, "steps": step + 1}

            # 3. EJECUTAR HERRAMIENTA
            if tool_name:
                logger.info(f"[Step {step+1}] Ejecutando: {tool_name}({tool_args})")
                observation = await self._execute_tool(tool_name, tool_args)
                
                # 4. AÑADIR OBSERVACIÓN AL HISTORIAL
                self.history.append({
                    "role": "assistant", 
                    "content": json.dumps({"thought": thought, "tool": tool_name, "tool_args": tool_args})
                })
                self.history.append({
                    "role": "user", 
                    "content": f"OBSERVACIÓN de {tool_name}: {json.dumps(observation)}"
                })
            else:
                # Si no hay herramienta ni respuesta, algo salió mal
                return {"success": False, "error": "Bucle de razonamiento roto", "last_thought": thought}

        return {"success": False, "error": "Límite de pasos alcanzado"}

    async def _think(self) -> Optional[Dict[str, Any]]:
        """Llama al LLM para obtener el siguiente paso."""
        system_prompt = f"""{self.identity}
        
        HERRAMIENTAS DISPONIBLES:
        {self._get_tools_desc()}
        
        REGLAS:
        1. Responde SIEMPRE en JSON válido.
        2. Formato: {{"thought": "...", "tool": "nombre|null", "tool_args": {{...}}|null, "reply": "..."}}
        3. Si la tarea está terminada, pon "tool": null y escribe la respuesta final en "reply".
        4. Si necesitas información, usa una herramienta. No adivines.
        5. Si una herramienta falla, analiza el error en 'thought' y prueba un enfoque diferente.
        """
        
        try:
            return await self.ai.complete_json(
                system=system_prompt,
                user=self.history[-1]["content"],
                model=AIModel.STRATEGY,
                agent_name=self.name
            )
        except Exception as e:
            logger.error(f"Error en _think: {e}")
            return None

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """Busca y ejecuta la herramienta en el registro global."""
        # 1. Buscar en tool_registry
        tool_obj = tool_registry.get_tool(name)
        if tool_obj:
            # Intentar llamar al método dinámicamente
            # Asumimos que la herramienta tiene un método principal o mapeamos
            try:
                # Implementación simplificada: buscar método que coincida o usar un dispatcher
                if hasattr(tool_obj, "run"):
                    return await tool_obj.run(**args)
                elif name == "web_search":
                    from apps.core.tools.web_tools import WebTools
                    return await WebTools().search_web(**args)
                # ... más mapeos manuales si es necesario ...
                return {"error": f"Herramienta {name} encontrada pero no ejecutable directamente"}
            except Exception as e:
                return {"error": str(e)}
        
        return {"error": f"Herramienta '{name}' no encontrada"}

    def _get_tools_desc(self) -> str:
        """Genera descripción de herramientas para el prompt."""
        tools = tool_registry.list_tools()
        # Añadir herramientas core e infraestructura
        tools.extend([
            "web_search", "execute_code", "github_view", "shopify_create",
            "manage_files", "execute_system_command", "monitor_api_health", "analyze_viral_content"
        ])
        return ", ".join(tools)
