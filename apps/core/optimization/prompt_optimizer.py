import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.optimizer")


class PromptOptimizer:
    """
    Prompt Optimization Engine (inspired by DSPy).

    Automatically improves prompts and strategies based on results.
    """

    def __init__(self):
        self.ai = get_ai_client()
        self.prompt_history = {}
        self.performance_metrics = {}

    async def optimize_prompt(
        self, original_prompt: str, task_type: str, performance_data: dict[str, Any]
    ) -> str:
        """Optimizes a prompt based on its performance."""

        prompt_key = hash(original_prompt)

        # Record previous performance
        if prompt_key in self.performance_metrics:
            self.performance_metrics[prompt_key].get("score", 0)
        else:
            pass

        # Use AI to improve the prompt
        optimization_prompt = f"""
        ORIGINAL PROMPT:
        {original_prompt}

        TASK TYPE: {task_type}
        CURRENT PERFORMANCE:
        - Score: {performance_data.get('score', 0)}/100
        - Success rate: {performance_data.get('success_rate', 0)}%
        - Average time: {performance_data.get('avg_time', 0)}s

        IMPROVEMENT:
        Rewrite the prompt to improve its effectiveness.
        Focus on:
        1. Clarity of instructions
        2. Specificity of context
        3. Expected output format

        Respond ONLY with the improved prompt, no explanations.
        """

        improved = await self.ai.complete(
            system="You are an expert in prompt engineering. Improve prompts for maximum effectiveness.",
            user=optimization_prompt,
            model=AIModel.STRATEGY,
        )

        optimized_prompt = improved.content if improved.success else original_prompt

        # Save optimized version
        self.prompt_history[prompt_key] = {
            "original": original_prompt,
            "optimized": optimized_prompt,
            "performance": performance_data,
        }

        logger.info(f"[PromptOptimizer] Optimized prompt for {task_type}")
        return optimized_prompt

    async def optimize_strategy(
        self, strategy: dict[str, Any], results: dict[str, Any]
    ) -> dict[str, Any]:
        """Optimizes a complete strategy based on results."""

        prompt = f"""
        CURRENT STRATEGY:
        {strategy}

        RESULTS:
        - ROI: {results.get('roi', 0)}
        - Conversion: {results.get('conversion_rate', 0)}%
        - Engagement: {results.get('engagement', 0)}%

        IMPROVEMENT:
        How can we improve this strategy to increase ROI?

        Respond in JSON with: improved_strategy, expected_roi_increase, key_changes
        """

        optimized = await self.ai.complete_json(
            system="You are a growth strategist. Optimize strategies for maximum ROI.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return optimized if optimized else strategy

    def get_optimization_history(self) -> dict[str, Any]:
        """Returns the optimization history."""
        return {
            "total_prompts_optimized": len(self.prompt_history),
            "history": list(self.prompt_history.values())[-10:],  # Last 10
        }
