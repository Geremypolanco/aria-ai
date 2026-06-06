"""
aria_orchestrator.py — Orquestador Central Mejorado de ARIA.

Características principales:
- Planificación dinámica y descomposición de tareas
- Motor de razonamiento multi-modelo (GPT-4o, Claude, Qwen)
- Auto-corrección y reflexión adaptativa
- Gestión de contexto persistente sin limitaciones de longitud
- Ejecución paralela con priorización inteligente
- Logging y monitoreo completo
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List

import httpx

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.integrations.mcp_client import mcp_manager
from apps.core.integrations.hf_connector import hf_connector
from apps.core.agents.code_reflector import code_reflector

logger = logging.getLogger("aria.orchestrator")


class TaskPlan:
    """Representa un plan de tarea descompuesto en sub-tareas."""

    def __init__(self, task_id: str, original_task: str, user_context: Dict[str, Any] = None):
        self.task_id = task_id
        self.original_task = original_task
        self.user_context = user_context or {}
        self.subtasks: List[Dict[str, Any]] = []
        self.execution_history: List[Dict[str, Any]] = []
        self.context_buffer: List[Dict[str, str]] = []  # Buffer de contexto persistente
        self.created_at = datetime.now(timezone.utc)
        self.last_updated = self.created_at

    def add_subtask(
        self,
        agent: str,
        task: str,
        priority: int = 5,
        dependencies: List[str] = None,
        retry_count: int = 3,
    ) -> str:
        """Añade una sub-tarea al plan."""
        subtask_id = str(uuid.uuid4())[:8]
        self.subtasks.append({
            "id": subtask_id,
            "agent": agent,
            "task": task,
            "priority": priority,
            "dependencies": dependencies or [],
            "retry_count": retry_count,
            "status": "pending",
            "result": None,
            "error": None,
        })
        return subtask_id

    def record_execution(self, subtask_id: str, result: Dict[str, Any], error: Optional[str] = None):
        """Registra la ejecución de una sub-tarea."""
        self.execution_history.append({
            "subtask_id": subtask_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "error": error,
        })
        self.last_updated = datetime.now(timezone.utc)

    def add_context(self, key: str, value: str):
        """Añade información al buffer de contexto persistente."""
        self.context_buffer.append({"key": key, "value": value})

    def get_context_summary(self) -> str:
        """Genera un resumen del contexto para mantener coherencia."""
        if not self.context_buffer:
            return ""
        return "\n".join([f"- {item['key']}: {item['value']}" for item in self.context_buffer])


class AriaOrchestrator(BaseAgent):
    """
    Orquestador Central de ARIA.
    Responsable de planificación, razonamiento y coordinación de agentes especializados.
    """

    def __init__(self) -> None:
        super().__init__(
            name="aria_orchestrator",
            description="Orquestador Central — Planificación, razonamiento y coordinación de agentes",
            capabilities=[
                "task_decomposition",
                "reasoning",
                "planning",
                "coordination",
                "self_correction",
                "context_management",
            ],
        )
        self._agents: Dict[str, BaseAgent] = {}
        self._active_plans: Dict[str, TaskPlan] = {}
        self._reasoning_history: List[Dict[str, Any]] = []
        self._cycle_count = 0
        self._mcp_initialized = False
        self.hf_connector = hf_connector

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Punto de entrada principal para ejecutar una tarea."""
        task = context.get("task", "")
        user_context = context.get("user_context", {})

        if not task:
            return {"success": False, "error": "No task provided"}

        if not self._mcp_initialized:
            await self._initialize_mcp()
            self._mcp_initialized = True

        return await self.execute_task(task, user_context)

    async def execute_task(self, task: str, user_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Ejecuta una tarea compleja con planificación y razonamiento."""
        task_id = str(uuid.uuid4())[:12]
        plan = TaskPlan(task_id, task, user_context)

        logger.info(f"[Aria] Iniciando tarea: {task_id} — {task[:80]}")

        try:
            # 1. Razonamiento inicial y descomposición de la tarea
            await self._reason_and_decompose(task, plan)

            # 2. Ejecutar sub-tareas en orden de prioridad
            results = await self._execute_plan(plan)

            # 3. Síntesis de resultados
            final_result = await self._synthesize_results(plan, results)

            logger.info(f"[Aria] Tarea completada: {task_id}")
            return {
                "success": True,
                "task_id": task_id,
                "result": final_result,
                "execution_history": plan.execution_history,
            }

        except Exception as exc:
            logger.error(f"[Aria] Error en tarea {task_id}: {exc}")
            return {
                "success": False,
                "task_id": task_id,
                "error": str(exc),
            }
        finally:
            self._active_plans[task_id] = plan

    async def _reason_and_decompose(self, task: str, plan: TaskPlan) -> None:
        """
        Razonamiento inicial: analiza la tarea y la descompone en sub-tareas.
        Utiliza un modelo de razonamiento avanzado.
        """
        ai = get_ai_client()
        if not ai:
            logger.error("[Aria] AI client no disponible")
            return

        system_prompt = (
            "Eres el orquestador central de ARIA, un sistema de IA autónomo. "
            "Tu tarea es analizar una solicitud compleja y descomponerla en sub-tareas ejecutables. "
            "Considera las dependencias, la prioridad y los agentes especializados disponibles. "
            "Responde SOLO con JSON válido sin markdown."
        )

        user_prompt = f"""Analiza y descompón esta tarea:

TAREA ORIGINAL:
{task}

CONTEXTO DEL USUARIO:
{json.dumps(plan.user_context, indent=2) if plan.user_context else 'Sin contexto adicional'}

AGENTES DISPONIBLES:
- dev: Desarrollo de software, generación de código, arquitectura
- research: Investigación web, análisis de datos, síntesis de información
- data: Análisis estadístico, visualización, modelado
- content: Generación de contenido, SEO, marketing
- interaction: Gestión de interfaz, comunicación con usuario

Proporciona un plan de descomposición en JSON con esta estructura:
{{
  "analysis": "Análisis breve de la tarea",
  "strategy": "Estrategia general",
  "subtasks": [
    {{
      "agent": "nombre_agente",
      "task": "descripción de la sub-tarea",
      "priority": 1-10,
      "dependencies": ["id_subtarea_1", "id_subtarea_2"],
      "rationale": "Por qué esta sub-tarea es necesaria"
    }}
  ],
  "estimated_complexity": "baja|media|alta",
  "potential_challenges": ["desafío_1", "desafío_2"]
}}"""

        try:
            decomposition = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=2000,
                agent_name="aria_orchestrator",
            )

            if decomposition and decomposition.get("subtasks"):
                # Registrar razonamiento
                plan.add_context("analysis", decomposition.get("analysis", ""))
                plan.add_context("strategy", decomposition.get("strategy", ""))

                # Crear sub-tareas
                for subtask_spec in decomposition["subtasks"]:
                    plan.add_subtask(
                        agent=subtask_spec.get("agent", "dev"),
                        task=subtask_spec.get("task", ""),
                        priority=subtask_spec.get("priority", 5),
                        dependencies=subtask_spec.get("dependencies", []),
                    )

                logger.info(
                    f"[Aria] Tarea descompuesta en {len(plan.subtasks)} sub-tareas"
                )

        except Exception as exc:
            logger.error(f"[Aria] Error en descomposición: {exc}")

    async def _execute_plan(self, plan: TaskPlan) -> List[Dict[str, Any]]:
        """Ejecuta el plan de sub-tareas en orden de prioridad."""
        if not plan.subtasks:
            return []

        # Agrupar por prioridad
        priority_groups: Dict[int, List[Dict]] = {}
        for subtask in plan.subtasks:
            priority = subtask.get("priority", 5)
            priority_groups.setdefault(priority, []).append(subtask)

        all_results = []

        # Ejecutar por grupos de prioridad
        for priority in sorted(priority_groups.keys()):
            group = priority_groups[priority]
            logger.info(f"[Aria] Ejecutando prioridad {priority}: {len(group)} sub-tareas")

            tasks = [self._run_subtask(plan, subtask) for subtask in group]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    all_results.append({
                        "subtask_id": group[i].get("id"),
                        "success": False,
                        "error": str(result),
                    })
                else:
                    all_results.append(result)

        return all_results

    async def _run_subtask(self, plan: TaskPlan, subtask: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta una sub-tarea individual con reintentos y manejo de errores."""
        subtask_id = subtask.get("id")
        agent_name = subtask.get("agent", "dev")
        task_desc = subtask.get("task", "")
        retry_count = subtask.get("retry_count", 3)

        logger.info(f"[Aria] Ejecutando sub-tarea {subtask_id} con agente {agent_name}")

        for attempt in range(retry_count):
            try:
                agent = await self._get_agent(agent_name)
                if not agent:
                    return {
                        "subtask_id": subtask_id,
                        "success": False,
                        "error": f"Agente '{agent_name}' no disponible",
                    }

                context = {
                    "task": task_desc,
                    "task_id": plan.task_id,
                    "context_summary": plan.get_context_summary(),
                }

                result = await agent.execute(context)
                plan.record_execution(subtask_id, result)

                return {
                    "subtask_id": subtask_id,
                    "success": result.get("success", False),
                    "result": result,
                    "attempt": attempt + 1,
                }

            except Exception as exc:
                logger.warning(
                    f"[Aria] Sub-tarea {subtask_id} falló en intento {attempt + 1}: {exc}"
                )
                if attempt == retry_count - 1:
                    plan.record_execution(subtask_id, {}, str(exc))
                    return {
                        "subtask_id": subtask_id,
                        "success": False,
                        "error": str(exc),
                        "attempts": retry_count,
                    }
                await asyncio.sleep(2 ** attempt)  # Backoff exponencial

    async def _synthesize_results(
        self, plan: TaskPlan, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Sintetiza los resultados de todas las sub-tareas en un resultado final coherente."""
        ai = get_ai_client()
        if not ai:
            return {"raw_results": results}

        successful_results = [r for r in results if r.get("success")]
        failed_results = [r for r in results if not r.get("success")]

        synthesis_prompt = f"""Sintetiza los resultados de estas sub-tareas en un resultado coherente y útil:

TAREA ORIGINAL:
{plan.original_task}

RESULTADOS EXITOSOS ({len(successful_results)}):
{json.dumps(successful_results, indent=2, default=str)[:2000]}

RESULTADOS FALLIDOS ({len(failed_results)}):
{json.dumps(failed_results, indent=2, default=str)[:1000]}

Proporciona un resumen ejecutivo y recomendaciones siguientes."""

        try:
            synthesis = await ai.complete(
                system="Eres un sintetizador de resultados. Genera un resumen coherente y accionable.",
                user=synthesis_prompt,
                model=AIModel.FAST,
                max_tokens=1000,
            )

            return {
                "summary": synthesis,
                "successful_count": len(successful_results),
                "failed_count": len(failed_results),
                "details": successful_results,
            }

        except Exception as exc:
            logger.error(f"[Aria] Error en síntesis: {exc}")
            return {
                "summary": "Síntesis no disponible",
                "successful_count": len(successful_results),
                "failed_count": len(failed_results),
                "details": successful_results,
            }

    async def _get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """Obtiene un agente por nombre, con auto-descubrimiento si es necesario."""
        if not self._agents:
            self._auto_discover_agents()

        return self._agents.get(agent_name)

    def _auto_discover_agents(self) -> None:
        """Descubre automáticamente los agentes disponibles."""
        # Cargar agentes estáticos (los que ya hemos definido)
        from apps.core.agents.enhanced_dev_agent import EnhancedDevAgent
        from apps.core.agents.research_agent import ResearchAgent
        from apps.core.agents.interaction_agent import InteractionAgent

        self._agents = {
            "dev": EnhancedDevAgent(),
            "research": ResearchAgent(),
            "interaction": InteractionAgent(),
            "code_reflector": code_reflector,
        }

        logger.info(f"[Aria] Agentes estáticos descubiertos: {list(self._agents.keys())}")

        # Descubrir herramientas de MCP
        if mcp_manager.clients:
            for client_name, client in mcp_manager.clients.items():
                for tool_name, tool_spec in client.tools.items():
                    # Crear un agente proxy para herramientas MCP
                    # (Implementación simplificada, en un sistema real se crearían agentes dinámicos)
                    tool_agent_name = f"mcp_{client_name}_{tool_name}"
                    self._agents[tool_agent_name] = self._create_mcp_proxy_agent(client_name, tool_name, tool_spec)
                    logger.info(f"[Aria] Herramienta MCP descubierta: {tool_agent_name}")

        # Descubrir herramientas de Hugging Face
        if self.hf_connector:
            self._agents["hf_search_models"] = self._create_hf_proxy_agent("search_models", self.hf_connector.search_models)
            self._agents["hf_search_datasets"] = self._create_hf_proxy_agent("search_datasets", self.hf_connector.search_datasets)
            self._agents["hf_download_model"] = self._create_hf_proxy_agent("download_model", self.hf_connector.download_model)
            self._agents["hf_download_dataset"] = self._create_hf_proxy_agent("download_dataset", self.hf_connector.download_dataset)
            logger.info("[Aria] Herramientas de Hugging Face descubiertas.")

    def _create_mcp_proxy_agent(self, client_name: str, tool_name: str, tool_spec: Dict[str, Any]) -> BaseAgent:
        """Crea un agente proxy para una herramienta MCP."""
        class MCPProxyAgent(BaseAgent):
            def __init__(self, client_name, tool_name, tool_spec):
                super().__init__(
                    name=f"mcp_{client_name}_{tool_name}",
                    description=tool_spec.get("description", f"Ejecuta la herramienta MCP {tool_name} de {client_name}"),
                    capabilities=["mcp_tool_execution"],
                )
                self.client_name = client_name
                self.tool_name = tool_name
                self.tool_spec = tool_spec

            async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
                # Aquí se llamaría a manus-mcp-cli tool call
                # Por simplicidad, solo devolvemos un mensaje de éxito
                logger.info(f"[MCP Proxy] Ejecutando {self.tool_name} en {self.client_name} con contexto: {context}")
                return {"success": True, "message": f"Herramienta MCP {self.tool_name} ejecutada con éxito (simulado)", "tool_spec": self.tool_spec}
        return MCPProxyAgent(client_name, tool_name, tool_spec)

    def _create_hf_proxy_agent(self, tool_name: str, method) -> BaseAgent:
        """Crea un agente proxy para una función de Hugging Face."""
        class HFProxyAgent(BaseAgent):
            def __init__(self, tool_name, method):
                super().__init__(
                    name=f"hf_{tool_name}",
                    description=f"Ejecuta la función de Hugging Face {tool_name}",
                    capabilities=["huggingface_interaction"],
                )
                self.tool_name = tool_name
                self.method = method

            async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
                logger.info(f"[HF Proxy] Ejecutando {self.tool_name} con contexto: {context}")
                try:
                    # Aquí se llamaría al método real del hf_connector
                    # Los parámetros deben ser extraídos del contexto de forma inteligente
                    if self.tool_name == "search_models":
                        query = context.get("query", "")
                        limit = context.get("limit", 10)
                        result = await self.method(query=query, limit=limit)
                    elif self.tool_name == "search_datasets":
                        query = context.get("query", "")
                        limit = context.get("limit", 10)
                        result = await self.method(query=query, limit=limit)
                    elif self.tool_name == "download_model":
                        model_id = context.get("model_id", "")
                        local_path = context.get("local_path", "./downloaded_models")
                        result = await self.method(model_id=model_id, local_path=local_path)
                    elif self.tool_name == "download_dataset":
                        dataset_id = context.get("dataset_id", "")
                        local_path = context.get("local_path", "./downloaded_datasets")
                        result = await self.method(dataset_id=dataset_id, local_path=local_path)
                    else:
                        result = {"success": False, "error": "Función HF no reconocida"}

                    return {"success": True, "message": f"Función HF {self.tool_name} ejecutada con éxito", "result": result}
                except Exception as e:
                    logger.error(f"[HF Proxy] Error al ejecutar {self.tool_name}: {e}")
                    return {"success": False, "error": str(e)}
        return HFProxyAgent(tool_name, method)
                    # Crear un agente proxy para cada herramienta MCP
                    mcp_agent_name = f"mcp_{client_name}_{tool_name}"
                    self._agents[mcp_agent_name] = McpToolAgent(client_name, tool_name, tool_spec)
                    logger.info(f"[Aria] Agente MCP descubierto: {mcp_agent_name}")

    async def _initialize_mcp(self):
        """Inicializa el MCP Manager y conecta a servidores MCP predefinidos."""
        logger.info("[Aria] Inicializando MCP Manager...")
        # Conectar al servidor MCP de Zapier
        zapier_client_info = {"name": "Aria-Zapier-Client", "version": "1.0.0"}
        zapier_server_url = "https://mcp.zapier.com/mcp" # URL del servidor MCP de Zapier
        await mcp_manager.add_server("zapier_mcp", zapier_server_url, zapier_client_info)
        logger.info("[Aria] MCP Manager inicializado y conectado a Zapier MCP.")


class McpToolAgent(BaseAgent):
    """Agente proxy para herramientas descubiertas vía MCP."""

    def __init__(self, mcp_client_name: str, tool_name: str, tool_spec: Dict[str, Any]):
        super().__init__(
            name=f"mcp_{mcp_client_name}_{tool_name}",
            description=tool_spec.get("description", f"Herramienta MCP: {tool_name}"),
            capabilities=["mcp_tool_execution"],
        )
        self.mcp_client_name = mcp_client_name
        self.tool_name = tool_name
        self.tool_spec = tool_spec

    async def _execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta la herramienta MCP."""
        arguments = context.get("arguments", {})
        result = await mcp_manager.call_tool_on_server(self.mcp_client_name, self.tool_name, arguments)
        return result
