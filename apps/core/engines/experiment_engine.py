import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.experiment")


class ExperimentEngine:
    """
    Experimentation Engine.
    Designs and runs A/B tests to validate sales hypotheses.
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def design_ab_test(self, hypothesis: str, context: dict[str, Any]) -> dict[str, Any]:
        """
        Designs an A/B test to validate a hypothesis.

        Example:
        Hypothesis: "If I change the price from $99 to $79, conversion will rise 30%"
        """
        prompt = f"""
        HYPOTHESIS: {hypothesis}
        CONTEXT: {context}

        Design a rigorous A/B test:

        1. VARIANT A (Control): Describe the current state
        2. VARIANT B (Test): Describe the proposed change
        3. PRIMARY METRIC: What will we measure?
        4. DURATION: How long should it run?
        5. SAMPLE SIZE: How many people do we need?
        6. SUCCESS CRITERIA: When do we consider it a win?

        Respond in JSON with: variant_a, variant_b, metric, duration_days, sample_size, success_criteria
        """

        test_design = await self.ai.complete_json(
            system="You are an expert in Experimentation and Statistics.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return test_design if test_design else {"error": "Design failed"}

    async def run_experiment(self, test_id: str, results: dict[str, Any]) -> dict[str, Any]:
        """Analyzes the results of an experiment."""
        prompt = f"""
        RESULTS OF TEST {test_id}:
        {results}

        Analyze:
        1. Did A or B win?
        2. Is it statistically significant?
        3. What is the expected impact if we scale it?
        4. What did we learn?

        Respond in JSON with: winner, significance, impact_if_scaled, learnings
        """

        analysis = await self.ai.complete_json(
            system="You are an expert in experimental data analysis.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return analysis if analysis else {"error": "Analysis failed"}
