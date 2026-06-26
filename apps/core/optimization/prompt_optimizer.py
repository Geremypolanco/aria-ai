import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.optimizer")


class PromptOptimizer:
    """
    Motor de Optimización de Prompts (inspirado en DSPy).

    Mejora automáticamente los prompts y estrategias basándose en resultados.
    """

    def __init__(self):
        self.ai = get_ai_client()
        self.prompt_history = {}
        self.performance_metrics = {}

    async def optimize_prompt(
        self, original_prompt: str, task_type: str, performance_data: dict[str, Any]
    ) -> str:
        """Optimiza un prompt basándose en su desempeño."""

        prompt_key = hash(original_prompt)

        # Registrar desempeño anterior
        if prompt_key in self.performance_metrics:
            self.performance_metrics[prompt_key].get("score", 0)
        else:
            pass

        # Usar IA para mejorar el prompt
        optimization_prompt = f"""
        PROMPT ORIGINAL:
        {original_prompt}

        TIPO DE TAREA: {task_type}
        DESEMPEÑO ACTUAL:
        - Score: {performance_data.get('score', 0)}/100
        - Tasa de éxito: {performance_data.get('success_rate', 0)}%
        - Tiempo promedio: {performance_data.get('avg_time', 0)}s

        MEJORA:
        Reescribe el prompt para mejorar su efectividad.
        Enfócate en:
        1. Claridad de instrucciones
        2. Especificidad del contexto
        3. Formato de salida esperada

        Responde SOLO con el prompt mejorado, sin explicaciones.
        """

        improved = await self.ai.complete(
            system="Eres un experto en ingeniería de prompts. Mejora prompts para máxima efectividad.",
            user=optimization_prompt,
            model=AIModel.STRATEGY,
        )

        optimized_prompt = improved.content if improved.success else original_prompt

        # Guardar versión optimizada
        self.prompt_history[prompt_key] = {
            "original": original_prompt,
            "optimized": optimized_prompt,
            "performance": performance_data,
        }

        logger.info(f"[PromptOptimizer] Prompt optimizado para {task_type}")
        return optimized_prompt

    async def optimize_strategy(
        self, strategy: dict[str, Any], results: dict[str, Any]
    ) -> dict[str, Any]:
        """Optimiza una estrategia completa basándose en resultados."""

        prompt = f"""
        ESTRATEGIA ACTUAL:
        {strategy}

        RESULTADOS:
        - ROI: {results.get('roi', 0)}
        - Conversión: {results.get('conversion_rate', 0)}%
        - Engagement: {results.get('engagement', 0)}%

        MEJORA:
        ¿Cómo podemos mejorar esta estrategia para aumentar ROI?

        Responde en JSON con: improved_strategy, expected_roi_increase, key_changes
        """

        optimized = await self.ai.complete_json(
            system="Eres un estratega de crecimiento. Optimiza estrategias para máximo ROI.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return optimized if optimized else strategy

    def get_optimization_history(self) -> dict[str, Any]:
        """Retorna el historial de optimizaciones."""
        return {
            "total_prompts_optimized": len(self.prompt_history),
            "history": list(self.prompt_history.values())[-10:],  # Últimas 10
        }
