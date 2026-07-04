"""
ARIA Agent System — ExecutionAgent.
Ejecuta planes paso a paso, gestionando tools y reportando resultados.
Procesa cada paso del plan, llama a las herramientas correspondientes,
y reporta resultados parciales para verificación.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agents.base import AgentBase
from core.messaging.types import (
    AgentMessage,
    AgentType,
    MessageType,
    StepResult,
)

logger = logging.getLogger("aria.agent.execution")


class ExecutionAgent(AgentBase):
    """
    Agente de Ejecución: toma un plan y lo ejecuta paso a paso.

    Flujo:
      1. Recibe plan.generated
      2. Para cada paso del plan:
         a. Ejecuta la tool correspondiente
         b. Publica step.executed con el resultado
         c. Espera verificación (si está configurada)
         d. Si falla, aplica estrategia de reintento
      3. Cuando todos los pasos se completan, publica task.completed
      4. Si un paso crítico falla, publica task.failed

    Soporta:
    - Ejecución secuencial de pasos
    - Reintentos automáticos por paso
    - Timeout por paso
    - Reporte de progreso en tiempo real
    """

    def __init__(self, bus=None):
        super().__init__(AgentType.EXECUTION, bus=bus)
        self._active_tasks: dict[str, dict[str, Any]] = {}  # task_id -> {plan, current_step, results}

    def get_subscriptions(self) -> list[MessageType]:
        return [
            MessageType.PLAN_GENERATED,
            MessageType.TASK_STARTED,
            MessageType.TASK_NEEDS_REVIEW,
        ]

    async def handle_message(self, message: AgentMessage) -> None:
        if message.type == MessageType.PLAN_GENERATED:
            await self._handle_plan(message)
        elif message.type == MessageType.TASK_STARTED:
            await self._handle_start(message)
        elif message.type == MessageType.TASK_NEEDS_REVIEW:
            await self._handle_re_execute(message)

    async def _handle_plan(self, message: AgentMessage) -> None:
        """Recibe un plan y comienza a ejecutarlo."""
        task_id = message.task_id
        if not task_id:
            return

        plan_data = message.payload.get("plan", {})
        steps = plan_data.get("steps", [])

        if not steps:
            logger.warning("Execution [%s]: plan sin pasos", task_id[:8])
            await self.send_error(task_id, "Plan vacío sin pasos")
            return

        self._active_tasks[task_id] = {
            "plan": plan_data,
            "steps": steps,
            "current_step": 0,
            "results": [],
            "started_at": time.time(),
        }

        logger.info(
            "Execution [%s]: ejecutando plan de %d pasos",
            task_id[:8],
            len(steps),
        )

        # Notificar inicio
        await self.publish(AgentMessage(
            type=MessageType.TASK_STARTED,
            source=AgentType.EXECUTION,
            target=AgentType.ORCHESTRATOR,
            task_id=task_id,
            payload={
                "total_steps": len(steps),
                "estimated_duration": plan_data.get("estimated_duration_seconds", 60),
            },
        ))

        # Ejecutar pasos secuencialmente
        await self._execute_steps(task_id)

    async def _handle_start(self, message: AgentMessage) -> None:
        """Si recibimos task.started directamente, verificamos si hay plan pendiente."""
        task_id = message.task_id
        if not task_id:
            return
        # Si ya estábamos ejecutando esta tarea, continuamos
        if task_id in self._active_tasks:
            await self._execute_steps(task_id)

    async def _handle_re_execute(self, message: AgentMessage) -> None:
        """Re-ejecuta pasos que fallaron verificación."""
        task_id = message.task_id
        if not task_id:
            return

        failed_step = message.payload.get("failed_step")
        previous_plan = message.payload.get("plan", {})

        if task_id not in self._active_tasks and previous_plan:
            steps = previous_plan.get("steps", [])
            self._active_tasks[task_id] = {
                "plan": previous_plan,
                "steps": steps,
                "current_step": failed_step or 0,
                "results": message.payload.get("partial_results", []),
                "started_at": time.time(),
            }

        logger.info(
            "Execution [%s]: re-ejecutando desde paso %d",
            task_id[:8],
            failed_step or 0,
        )
        await self._execute_steps(task_id)

    async def _execute_steps(self, task_id: str) -> None:
        """Ejecuta los pasos del plan secuencialmente."""
        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning("Execution [%s]: tarea no activa", task_id[:8])
            return

        steps = task["steps"]
        start_index = task["current_step"]

        for i in range(start_index, len(steps)):
            if not self._running:
                logger.info("Execution [%s]: detenido durante ejecución", task_id[:8])
                return

            step = steps[i]
            task["current_step"] = i

            # Ejecutar paso con reintentos
            success = await self._execute_step_with_retry(task_id, i, step)

            if not success:
                # Paso crítico falló → abortar tarea
                logger.error(
                    "Execution [%s]: paso %d falló, abortando tarea",
                    task_id[:8],
                    i,
                )
                await self.publish(AgentMessage(
                    type=MessageType.TASK_FAILED,
                    source=AgentType.EXECUTION,
                    target=AgentType.ORCHESTRATOR,
                    task_id=task_id,
                    payload={
                        "failed_step": i,
                        "error": f"Paso {i+1} falló: {step.get('tool', 'unknown')}",
                        "partial_results": task["results"],
                        "plan": task["plan"],
                    },
                ))
                self._active_tasks.pop(task_id, None)
                return

        # Todos los pasos completados exitosamente
        elapsed = time.time() - task["started_at"]
        logger.info(
            "Execution [%s]: plan completado en %.1fs",
            task_id[:8],
            elapsed,
        )

        await self.publish(AgentMessage(
            type=MessageType.TASK_COMPLETED,
            source=AgentType.EXECUTION,
            target=AgentType.VERIFICATION,
            task_id=task_id,
            payload={
                "results": task["results"],
                "total_steps": len(steps),
                "duration_seconds": round(elapsed, 1),
                "plan": task["plan"],
            },
        ))

        self._active_tasks.pop(task_id, None)

    async def _execute_step_with_retry(
        self,
        task_id: str,
        step_index: int,
        step: dict[str, Any],
    ) -> bool:
        """
        Ejecuta un paso con lógica de reintentos.

        Retorna True si el paso se ejecutó exitosamente,
        False si todos los reintentos fallaron.
        """
        tool = step.get("tool", "unknown")
        params = step.get("params", {})
        timeout = step.get("timeout_seconds", 30)
        max_retries = step.get("retry_on_fail", True) and 2 or 0

        for attempt in range(max_retries + 1):
            try:
                start = time.time()

                result = await self._execute_tool(tool, params, timeout)

                duration_ms = int((time.time() - start) * 1000)

                step_result = StepResult(
                    step=step_index,
                    action=tool,
                    status="success",
                    input=params,
                    output=result,
                    duration_ms=duration_ms,
                )

                # Guardar resultado
                task = self._active_tasks.get(task_id)
                if task:
                    task["results"].append(step_result.model_dump())

                # Publicar resultado para verificación
                await self.publish(AgentMessage(
                    type=MessageType.STEP_EXECUTED,
                    source=AgentType.EXECUTION,
                    target=AgentType.VERIFICATION,
                    task_id=task_id,
                    payload={
                        "step": step_index,
                        "result": step_result.model_dump(),
                        "step_config": step,
                    },
                ))

                logger.info(
                    "Execution [%s]: paso %d/%d '%s' OK (%dms)",
                    task_id[:8],
                    step_index + 1,
                    len(self._active_tasks.get(task_id, {}).get("steps", [])),
                    tool,
                    duration_ms,
                )
                return True

            except asyncio.TimeoutError:
                logger.warning(
                    "Execution [%s]: paso %d timeout (intento %d/%d)",
                    task_id[:8],
                    step_index,
                    attempt + 1,
                    max_retries + 1,
                )
                if attempt < max_retries:
                    await asyncio.sleep(1 * (attempt + 1))  # Backoff

            except Exception as e:
                logger.warning(
                    "Execution [%s]: paso %d error: %s (intento %d/%d)",
                    task_id[:8],
                    step_index,
                    str(e)[:100],
                    attempt + 1,
                    max_retries + 1,
                )
                if attempt < max_retries:
                    await asyncio.sleep(1 * (attempt + 1))

        # Todos los reintentos fallaron
        task = self._active_tasks.get(task_id)
        if task:
            task["results"].append(StepResult(
                step=step_index,
                action=tool,
                status="failed",
                input=params,
                error=f"Falló después de {max_retries + 1} intentos",
                duration_ms=0,
            ).model_dump())

        await self.publish(AgentMessage(
            type=MessageType.STEP_FAILED,
            source=AgentType.EXECUTION,
            target=AgentType.ORCHESTRATOR,
            task_id=task_id,
            payload={
                "step": step_index,
                "tool": tool,
                "error": f"Falló después de {max_retries + 1} intentos",
                "step_config": step,
            },
        ))

        return False

    async def _execute_tool(
        self,
        tool: str,
        params: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        """
        Ejecuta una herramienta específica.

        Fase 2: stub que simula ejecución de herramientas.
        Fase 3-4: implementación real con Sandbox/Browser managers.
        """
        # ── Simulación de herramientas (Fase 2) ──
        # En Fase 3-4 esto se reemplaza con llamadas reales
        await asyncio.sleep(0.1)  # Simular latencia

        if tool == "terminal_run":
            command = params.get("command", "")
            return {
                "stdout": f"[SIMULATED] {command}",
                "stderr": "",
                "exit_code": 0,
                "output_text": f"Ejecutado: {command[:100]}",
            }
        elif tool == "browser_navigate":
            url = params.get("url", "")
            return {
                "url": url,
                "title": f"[SIMULATED] {url}",
                "status": "loaded",
                "body_preview": f"<html>... página cargada desde {url} ...</html>",
            }
        elif tool == "browser_click":
            selector = params.get("selector", "")
            return {
                "clicked": selector,
                "status": "success",
                "new_url": params.get("url", ""),
            }
        elif tool == "browser_extract":
            selectors = params.get("selectors", [])
            return {
                "extracted": {s: f"[DATA:{s}]" for s in selectors},
                "format": params.get("format", "text"),
                "count": len(selectors),
            }
        else:
            return {
                "tool": tool,
                "status": "executed",
                "params": params,
                "note": "Simulated in Phase 2",
            }