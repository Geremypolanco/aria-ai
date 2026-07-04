"""
ARIA Agent System — PlannerAgent.
Genera planes JSON estructurados a partir de tareas entrantes.
Toma una tarea con input libre y produce un plan con pasos secuenciales,
herramientas asignadas y resultados esperados.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agents.base import AgentBase
from core.messaging.types import (
    AgentMessage,
    AgentType,
    MessageType,
    Plan,
    StepResult,
)

logger = logging.getLogger("aria.agent.planner")


class PlannerAgent(AgentBase):
    """
    Agente Planificador: traduce tareas humanas en planes ejecutables.

    Flujo:
      1. Recibe task.created
      2. Analiza el input de la tarea
      3. Genera un plan JSON con pasos, herramientas y expectativas
      4. Publica plan.generated

    Tipos de plan soportados:
    - browser: navegación web, extracción de datos, clicks
    - terminal: ejecución de comandos en sandbox
    - research: búsqueda y síntesis de información
    - extract: extracción estructurada de datos
    - monitor: vigilancia periódica de recursos
    """

    def __init__(self, bus=None):
        super().__init__(AgentType.PLANNER, bus=bus)

    def get_subscriptions(self) -> list[MessageType]:
        return [
            MessageType.TASK_CREATED,
            MessageType.TASK_NEEDS_REVIEW,
        ]

    async def handle_message(self, message: AgentMessage) -> None:
        if message.type == MessageType.TASK_CREATED:
            await self._handle_task_created(message)
        elif message.type == MessageType.TASK_NEEDS_REVIEW:
            await self._handle_replan_request(message)

    async def _handle_task_created(self, message: AgentMessage) -> None:
        """Procesa una nueva tarea y genera un plan."""
        task_id = message.task_id
        if not task_id:
            logger.warning("Planner: mensaje task.created sin task_id")
            return

        task_input = message.payload.get("input", {})
        task_type = message.payload.get("task_type", "custom")
        title = message.payload.get("title", "")

        logger.info(
            "Planner [%s]: planificando tarea '%s' (type=%s)",
            task_id[:8],
            title,
            task_type,
        )

        # Generar plan según el tipo de tarea
        try:
            plan = await self._generate_plan(task_id, task_type, task_input)
            await self._publish_plan(task_id, plan)
        except Exception as e:
            logger.exception("Planner: error generando plan para %s", task_id[:8])
            await self.send_error(task_id, f"Error generando plan: {e}", correlation_id=message.id)

    async def _handle_replan_request(self, message: AgentMessage) -> None:
        """
        Re-planifica una tarea que falló verificación.
        Usa el resultado parcial para ajustar el plan.
        """
        task_id = message.task_id
        if not task_id:
            return

        partial_result = message.payload.get("partial_result", {})
        error = message.payload.get("error", "")
        previous_plan = message.payload.get("previous_plan", {})

        logger.info(
            "Planner [%s]: re-planificando tras error: %s",
            task_id[:8],
            error[:100],
        )

        # Si hay plan previo, lo usamos como base y ajustamos
        if previous_plan:
            plan = self._adapt_plan(previous_plan, error, partial_result)
        else:
            plan = await self._generate_plan(
                task_id,
                message.payload.get("task_type", "custom"),
                message.payload.get("input", {}),
            )

        plan.fallback_strategy = f"Reintento después de: {error[:200]}"
        await self._publish_plan(task_id, plan)

    async def _generate_plan(
        self,
        task_id: str,
        task_type: str,
        task_input: dict[str, Any],
    ) -> Plan:
        """
        Genera un plan estructurado según el tipo de tarea.
        Cada plan tiene pasos con: tool, params, expected_output.
        """
        steps = self._generate_steps(task_type, task_input)
        estimated_seconds = sum(self._estimate_step_duration(step) for step in steps)

        return Plan(
            task_id=task_id,
            steps=steps,
            estimated_duration_seconds=estimated_seconds,
            fallback_strategy="Retry con timeout +50%",
        )

    def _generate_steps(
        self,
        task_type: str,
        task_input: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Genera los pasos según el tipo de tarea.

        Cada paso tiene la estructura:
        {
            "tool": "browser_navigate | browser_click | terminal_run | ...",
            "params": { ... parámetros de la herramienta ... },
            "expected_output": "descripción del resultado esperado",
            "timeout_seconds": 30,
            "retry_on_fail": true
        }
        """
        if task_type == "browser":
            return self._browser_plan(task_input)
        elif task_type == "terminal":
            return self._terminal_plan(task_input)
        elif task_type == "research":
            return self._research_plan(task_input)
        elif task_type == "extract":
            return self._extract_plan(task_input)
        elif task_type == "monitor":
            return self._monitor_plan(task_input)
        else:
            return self._custom_plan(task_input)

    def _browser_plan(self, task_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan para tareas de navegación web."""
        steps = []
        url = task_input.get("url", "")
        actions = task_input.get("actions", [])

        if url:
            steps.append({
                "tool": "browser_navigate",
                "params": {"url": url},
                "expected_output": "Página cargada exitosamente",
                "timeout_seconds": 30,
                "retry_on_fail": True,
            })

        for i, action in enumerate(actions):
            action_type = action.get("type", "click")
            tool_map = {
                "click": "browser_click",
                "type": "browser_type",
                "extract": "browser_extract",
                "screenshot": "browser_screenshot",
                "wait": "browser_wait",
            }
            tool = tool_map.get(action_type, "browser_click")
            steps.append({
                "tool": tool,
                "params": action.get("params", {}),
                "expected_output": action.get("expected", f"Acción {i+1} completada"),
                "timeout_seconds": action.get("timeout", 15),
                "retry_on_fail": True,
            })

        if task_input.get("extract_data", False):
            steps.append({
                "tool": "browser_extract",
                "params": {
                    "selectors": task_input.get("selectors", ["body"]),
                    "format": task_input.get("format", "text"),
                },
                "expected_output": "Datos extraídos exitosamente",
                "timeout_seconds": 20,
                "retry_on_fail": True,
            })

        return steps

    def _terminal_plan(self, task_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan para ejecución de comandos."""
        commands = task_input.get("commands", [])
        if isinstance(commands, str):
            commands = [commands]

        return [
            {
                "tool": "terminal_run",
                "params": {"command": cmd},
                "expected_output": f"Comando ejecutado: {cmd[:50]}...",
                "timeout_seconds": task_input.get("timeout", 30),
                "retry_on_fail": True,
            }
            for cmd in commands
        ]

    def _research_plan(self, task_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan para tareas de investigación/búsqueda."""
        query = task_input.get("query", "")
        sources = task_input.get("sources", ["web"])

        steps = []
        for source in sources:
            if source == "web":
                steps.append({
                    "tool": "browser_navigate",
                    "params": {"url": f"https://www.google.com/search?q={query}"},
                    "expected_output": "Resultados de búsqueda cargados",
                    "timeout_seconds": 20,
                    "retry_on_fail": True,
                })
                steps.append({
                    "tool": "browser_extract",
                    "params": {"selectors": ["h3", ".LC20lb"], "format": "text"},
                    "expected_output": "Títulos y enlaces extraídos",
                    "timeout_seconds": 15,
                    "retry_on_fail": False,
                })
        return steps

    def _extract_plan(self, task_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan para extracción estructurada de datos."""
        return [
            {
                "tool": "browser_navigate",
                "params": {"url": task_input.get("url", "")},
                "expected_output": "Página cargada",
                "timeout_seconds": 30,
                "retry_on_fail": True,
            },
            {
                "tool": "browser_extract",
                "params": {
                    "selectors": task_input.get("selectors", []),
                    "format": task_input.get("format", "json"),
                    "schema": task_input.get("schema", {}),
                },
                "expected_output": "Datos extraídos según schema",
                "timeout_seconds": 30,
                "retry_on_fail": False,
            },
        ]

    def _monitor_plan(self, task_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan para tareas de monitoreo periódico."""
        return [
            {
                "tool": "browser_navigate",
                "params": {"url": task_input.get("url", "")},
                "expected_output": "Dashboard cargado",
                "timeout_seconds": 30,
                "retry_on_fail": True,
            },
            {
                "tool": "browser_extract",
                "params": {
                    "selectors": task_input.get("metrics_selectors", []),
                    "format": "json",
                },
                "expected_output": f"Métricas extraídas: {task_input.get('metrics', [])}",
                "timeout_seconds": 20,
                "retry_on_fail": True,
            },
        ]

    def _custom_plan(self, task_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Plan genérico para tareas sin tipo específico."""
        return [
            {
                "tool": "terminal_run",
                "params": {"command": f"echo 'Plan genérico: {json.dumps(task_input)[:200]}'"},
                "expected_output": "Tarea ejecutada",
                "timeout_seconds": 15,
                "retry_on_fail": False,
            },
        ]

    def _estimate_step_duration(self, step: dict[str, Any]) -> int:
        """Estima duración de un paso para el cálculo de tiempo total."""
        return step.get("timeout_seconds", 30)

    def _adapt_plan(
        self,
        previous_plan: dict | Plan,
        error: str,
        partial_result: dict[str, Any],
    ) -> Plan:
        """Ajusta un plan existente basado en errores."""
        if isinstance(previous_plan, dict):
            steps = previous_plan.get("steps", [])
            task_id = previous_plan.get("task_id", "")
        else:
            steps = [s.model_dump() if hasattr(s, 'model_dump') else s for s in previous_plan.steps]
            task_id = previous_plan.task_id

        # Incrementar timeouts en los pasos que fallaron
        for step in steps:
            if "timeout_seconds" in step:
                step["timeout_seconds"] = int(step["timeout_seconds"] * 1.5)

        return Plan(
            task_id=task_id,
            steps=steps,
            estimated_duration_seconds=sum(
                self._estimate_step_duration(s) for s in steps
            ),
            fallback_strategy=f"Adaptado tras error: {error[:200]}",
        )

    async def _publish_plan(self, task_id: str, plan: Plan) -> None:
        """Publica el plan generado en el bus."""
        plan_dict = plan.model_dump()
        # Los pasos se serializan como dicts
        plan_dict["steps"] = [
            s.model_dump() if hasattr(s, 'model_dump') else s
            for s in plan.steps
        ]

        await self.publish(AgentMessage(
            type=MessageType.PLAN_GENERATED,
            source=AgentType.PLANNER,
            target=AgentType.EXECUTION,
            task_id=task_id,
            payload={
                "plan": plan_dict,
                "task_type": plan_dict.get("task_type", "custom"),
            },
        ))

        logger.info(
            "Planner [%s]: plan generado con %d pasos (~%ds)",
            task_id[:8],
            len(plan.steps),
            plan.estimated_duration_seconds,
        )