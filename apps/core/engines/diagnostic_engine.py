import logging
from typing import Any

from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.diagnostic")


class DiagnosticEngine:
    """
    Diagnostic Engine.
    Analyzes why something isn't working (sales, conversion, traffic).
    """

    def __init__(self):
        self.ai = get_ai_client()

    async def diagnose_sales_failure(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Diagnoses why a sales campaign is failing.

        Receives: product, traffic, conversion, price, platform
        Returns: most likely root cause + alternative hypotheses
        """
        prompt = f"""
        SALES CONTEXT:
        {context}

        QUESTION: Why isn't it selling?

        ANALYZE:
        1. Price (is it out of line with the market?)
        2. Description (is it unconvincing?)
        3. Images (are they low quality?)
        4. Audience (is it the right audience?)
        5. Timing (is it the right moment?)
        6. Competition (are there stronger competitors?)

        Respond in JSON with:
        - root_cause: most likely cause
        - hypothesis_a, hypothesis_b, hypothesis_c: alternative hypotheses
        - confidence_score: 0-100
        - recommended_tests: list of experiments to validate
        """

        diagnosis = await self.ai.complete_json(
            system="You are an expert in diagnosing e-commerce failures.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return diagnosis if diagnosis else {"error": "Diagnosis failed"}

    async def diagnose_low_engagement(self, content_data: dict[str, Any]) -> dict[str, Any]:
        """Diagnoses why content has low engagement."""
        prompt = f"""
        CONTENT DATA:
        {content_data}

        Why does this content have low engagement?

        Analyze:
        1. Format (is it the right format for the platform?)
        2. Timing (was it published at the right time?)
        3. Copywriting (is the message weak?)
        4. Visual (is the image/video appealing?)
        5. Audience (is it the right audience?)

        Respond in JSON with: root_cause, hypotheses, confidence, next_tests
        """

        diagnosis = await self.ai.complete_json(
            system="You are an expert in Social Media Analytics.",
            user=prompt,
            model=AIModel.STRATEGY,
        )

        return diagnosis if diagnosis else {"error": "Diagnosis failed"}
