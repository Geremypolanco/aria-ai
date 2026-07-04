"""
ARIA Agent System — VerificationAgent.
Valida resultados de pasos contra expectativas definidas en el plan.
Decide si un paso pasó, falló, o necesita revisión humana.
Aplica reglas de validación configurables por tipo de tarea.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from agents.base import AgentBase
from core.messaging.types import (
    AgentMessage,
    AgentType,
    MessageType,
)

logger = logging.getLogger("aria.agent.verification")


class VerificationAgent(AgentBase):
    """
    Agente de Verificación: valida resultados de ejecución.

    Flujo:
      1. Recibe step.executed o task.completed
      2. Compara resultado contra expected_output del plan
      3. Decide: pass → continuar, fail → reintentar o escalar
      4. Publica verification.passed o verification.failed

    Reglas de validación:
    - Browser: verificar que la URL cargó, que hay contenido
    - Terminal: verificar exit_code = 0, stderr vacío
    - Extract: verificar que hay datos, formato correcto
    """

    def __init__(self, bus=None):
        super().__init__(AgentType.VERIFICATION, bus=bus)
        self._verification_thresholds = {
            "browser_navigate": {"min_response_time_ms": 0, "require_status": "loaded"},
            "browser_click": {"require_status": "success"},
            "browser_extract": {"min_count": 1},
            "terminal_run": {"exit_code": 0},
        }

    def get_subscriptions(self) -> list[MessageType]:
        return [
            MessageType.STEP_EXECUTED,
            MessageType.TASK_COMPLETED,
        ]

    async def handle_message(self, message: AgentMessage) -> None:
        if message.type == MessageType.STEP_EXECUTED:
            await self._verify_step(message)
        elif message.type == MessageType.TASK_COMPLETED:
            await self._verify_completion(message)

    async def _verify_step(self, message: AgentMessage) -> None:
        """Verifica un paso individual de ejecución."""
        task_id = message.task_id
        if not task_id:
            return

        step_result = message.payload.get("result", {})
        step_config = message.payload.get("step_config", {})
        step_index = message.payload.get("step", 0)

        tool = step_config.get("tool", "unknown")
        expected = step_config.get("expected_output", "")
        actual_output = step_result.get("output", {})

        logger.debug(
            "Verification [%s]: verificando paso %d (%s)",
            task_id[:8],
            step_index,
            tool,
        )

        # Ejecutar validaciones
        errors = self._validate_step(tool, actual_output, expected, step_config)

        if not errors:
            # Paso verificado exitosamente
            logger.info(
                "Verification [%s]: paso %d OK",
                task_id[:8],
                step_index,
            )
            await self.publish(AgentMessage(
                type=MessageType.VERIFICATION_PASSED,
                source=AgentType.VERIFICATION,
                target=AgentType.EXECUTION,
                task_id=task_id,
                payload={
                    "step": step_index,
                    "tool": tool,
                    "result": actual_output,
                },
            ))
        else:
            # Paso falló verificación
            error_msg = "; ".join(errors)
            logger.warning(
                "Verification [%s]: paso %d falló: %s",
                task_id[:8],
                step_index,
                error_msg,
            )

            await self.publish(AgentMessage(
                type=MessageType.VERIFICATION_FAILED,
                source=AgentType.VERIFICATION,
                target=AgentType.ORCHESTRATOR,
                task_id=task_id,
                payload={
                    "step": step_index,
                    "tool": tool,
                    "errors": errors,
                    "partial_result": actual_output,
                    "expected": expected,
                },
            ))

    async def _verify_completion(self, message: AgentMessage) -> None:
        """Verifica la tarea completa (todos los pasos)."""
        task_id = message.task_id
        if not task_id:
            return

        results = message.payload.get("results", [])
        total_steps = message.payload.get("total_steps", 0)

        # Verificar que todos los pasos se completaron
        if len(results) < total_steps:
            logger.warning(
                "Verification [%s]: sólo %d/%d pasos completados",
                task_id[:8],
                len(results),
                total_steps,
            )
            await self.publish(AgentMessage(
                type=MessageType.VERIFICATION_FAILED,
                source=AgentType.VERIFICATION,
                target=AgentType.ORCHESTRATOR,
                task_id=task_id,
                payload={
                    "errors": [f"Sólo {len(results)}/{total_steps} pasos completados"],
                    "partial_result": results,
                },
            ))
            return

        # Verificar que todos los pasos tengan estado success
        failed_steps = [
            r for r in results if isinstance(r, dict) and r.get("status") == "failed"
        ]
        if failed_steps:
            logger.warning(
                "Verification [%s]: %d pasos fallaron",
                task_id[:8],
                len(failed_steps),
            )
            await self.publish(AgentMessage(
                type=MessageType.VERIFICATION_FAILED,
                source=AgentType.VERIFICATION,
                target=AgentType.ORCHESTRATOR,
                task_id=task_id,
                payload={
                    "errors": [f"{len(failed_steps)} paso(s) fallaron"],
                    "failed_steps": [f.get("step") for f in failed_steps],
                    "partial_result": results,
                },
            ))
            return

        # Tarea completa verificada exitosamente
        logger.info(
            "Verification [%s]: tarea completa verificada (%d pasos)",
            task_id[:8],
            total_steps,
        )

        await self.publish(AgentMessage(
            type=MessageType.VERIFICATION_PASSED,
            source=AgentType.VERIFICATION,
            target=AgentType.ORCHESTRATOR,
            task_id=task_id,
            payload={
                "status": "completed",
                "total_steps": total_steps,
                "results": results,
                "duration": message.payload.get("duration_seconds", 0),
            },
        ))

    def _validate_step(
        self,
        tool: str,
        output: dict[str, Any] | None,
        expected: str,
        step_config: dict[str, Any],
    ) -> list[str]:
        """
        Valida el resultado de un paso contra las expectativas.

        Retorna lista de errores (vacía = todo OK).
        """
        errors: list[str] = []
        thresholds = self._verification_thresholds.get(tool, {})

        if output is None:
            errors.append("No output produced")
            return errors

        # Validaciones por tipo de herramienta
        if tool == "browser_navigate":
            if output.get("status") != thresholds.get("require_status", "loaded"):
                errors.append(f"Browser navigation failed: status={output.get('status')}")
            if not output.get("title"):
                errors.append("No page title found")

        elif tool == "browser_click":
            if output.get("status") != "success":
                errors.append(f"Click failed: status={output.get('status')}")

        elif tool == "browser_extract":
            extracted = output.get("extracted", {})
            if not extracted:
                errors.append("No data extracted from page")
            else:
                min_count = thresholds.get("min_count", 1)
                count = output.get("count", len(extracted))
                if count < min_count:
                    errors.append(f"Expected at least {min_count} items, got {count}")

        elif tool == "terminal_run":
            if output.get("exit_code") != 0:
                stderr = output.get("stderr", "")
                errors.append(f"Command failed (exit={output.get('exit_code')}): {stderr[:200]}")
            if output.get("stderr"):
                logger.debug("Terminal stderr (non-fatal): %s", output["stderr"][:200])

        # Validación genérica: ¿el output contiene lo esperado?
        if expected and not expected.startswith("[SIMULATED"):
            # Si el expected es una descripción textual, verificar que no esté vacío
            output_text = self._output_to_text(output)
            if not output_text or len(output_text.strip()) == 0:
                errors.append(f"Output vacío cuando se esperaba: {expected}")

        return errors

    def _output_to_text(self, output: dict[str, Any]) -> str:
        """Convierte un output de tool a texto para validación."""
        if isinstance(output, dict):
            # Intentar varios campos comunes
            return str(
                output.get("output_text")
                or output.get("stdout")
                or output.get("body_preview")
                or output.get("extracted")
                or output.get("title")
                or ""
            )
        return str(output)