import logging
import traceback
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.healer")


class SystemSelfHealer:
    """
    Motor de Auto-Sanación de ARIA.
    Detecta fallos en herramientas y agentes, analiza el código y propone/aplica correcciones.
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def diagnose_and_fix(self, error: Exception, context: dict[str, Any]) -> dict[str, Any]:
        """Analiza un error y genera una estrategia de reparación."""
        error_trace = traceback.format_exc()
        tool_name = context.get("tool", "unknown")

        logger.error(f"[SelfHealer] Detectado fallo en {tool_name}: {error}")

        prompt = f"""
        ERROR DETECTADO EN EL SISTEMA ARIA:
        Herramienta/Agente: {tool_name}
        Error: {str(error)}
        Traceback: {error_trace}
        Contexto de ejecución: {context}

        TAREA:
        1. Explica la causa raíz del fallo.
        2. Proporciona un parche de código (Python) para solucionar el problema.
        3. Si es una falta de API Key o dependencia, indícalo claramente.

        Responde en JSON con: root_cause, fix_code, required_actions.
        """

        try:
            fix_suggestion = await self.ai.complete_json(
                system="Eres el Ingeniero de Confiabilidad de Sistemas de ARIA. Tu misión es la auto-sanación del código.",
                user=prompt,
                model=AIModel.STRATEGY,
            )

            # Aquí podríamos implementar la aplicación automática del parche usando github_self
            return {
                "success": True,
                "diagnosis": fix_suggestion,
                "message": "Fallo analizado. Sugerencia de reparación lista para aplicación.",
            }
        except Exception as e:
            return {"success": False, "error": f"El sanador también falló: {e}"}
