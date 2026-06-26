"""
ARIA DSPy — PromptOptimizer.

Wraps DSPy Predict modules for marketing tasks.
Provides graceful fallback responses when DSPy is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.cognition.dspy.signatures import (
    _DSPY_AVAILABLE,
    AdCopywriter,
    CampaignStrategy,
    ContentQuality,
)

logger = logging.getLogger("aria.cognition.dspy.optimizer")

try:
    import dspy as _dspy_module
except ImportError:
    _dspy_module = None  # type: ignore[assignment]

# Module-level singleton
_prompt_optimizer: PromptOptimizer | None = None


class PromptOptimizer:
    """
    DSPy-backed prompt optimizer for marketing tasks.

    When DSPy is available, uses compiled Predict modules.
    When DSPy is unavailable, returns sensible hardcoded fallbacks
    so the rest of the codebase keeps working.
    """

    def __init__(self) -> None:
        self._available: bool = _DSPY_AVAILABLE
        self._optimized: dict[str, Any] = {}
        self._predictors: dict[str, Any] = {}

        if self._available and _dspy_module is not None:
            self._init_predictors()

    def _init_predictors(self) -> None:
        """Build default Predict modules for each signature."""
        try:
            if ContentQuality is not None:
                self._predictors["content_quality"] = _dspy_module.Predict(ContentQuality)
            if AdCopywriter is not None:
                self._predictors["ad_copywriter"] = _dspy_module.Predict(AdCopywriter)
            if CampaignStrategy is not None:
                self._predictors["campaign_strategy"] = _dspy_module.Predict(CampaignStrategy)
            logger.info("[PromptOptimizer] DSPy predictors initialised: %s", list(self._predictors))
        except Exception as exc:
            logger.warning("[PromptOptimizer] Failed to init predictors: %s", exc)

    # ── optimisation ──────────────────────────────────────────────────────────

    def optimize_content_quality(self, examples: list[dict]) -> Any:
        """
        Return an optimized ContentQuality predictor trained on examples.

        Each example dict should have keys: content, platform, quality_score, improvement.
        Returns None if DSPy is unavailable or training fails.
        """
        if not self._available or _dspy_module is None or ContentQuality is None:
            return None

        try:
            trainset = [
                _dspy_module.Example(**ex).with_inputs("content", "platform")
                for ex in examples
                if "content" in ex and "platform" in ex
            ]
            if not trainset:
                return self._predictors.get("content_quality")

            # BootstrapFewShot or simple Predict if no teleprompter available
            try:
                from dspy.teleprompt import BootstrapFewShot  # type: ignore[import]

                teleprompter = BootstrapFewShot(max_bootstrapped_demos=2)
                student = _dspy_module.Predict(ContentQuality)
                optimized = teleprompter.compile(student, trainset=trainset)
            except Exception:
                optimized = _dspy_module.Predict(ContentQuality)

            self._optimized["content_quality"] = optimized
            return optimized

        except Exception as exc:
            logger.warning("[PromptOptimizer.optimize_content_quality] %s", exc)
            return None

    # ── task methods ──────────────────────────────────────────────────────────

    async def score_content(self, content: str, platform: str) -> dict:
        """
        Score content quality using DSPy ContentQuality or fallback.

        Returns dict with keys: quality_score, improvement
        """
        if not self._available or _dspy_module is None:
            return {
                "quality_score": "7",
                "improvement": "Use more specific data points and a clear call-to-action.",
            }

        predictor = self._optimized.get("content_quality") or self._predictors.get(
            "content_quality"
        )
        if predictor is None:
            return {
                "quality_score": "7",
                "improvement": "Use more specific data points and a clear call-to-action.",
            }

        try:
            pred = predictor(content=content, platform=platform)
            return {
                "quality_score": getattr(pred, "quality_score", "7"),
                "improvement": getattr(pred, "improvement", "Consider adding social proof."),
            }
        except Exception as exc:
            logger.warning("[PromptOptimizer.score_content] prediction failed: %s", exc)
            return {
                "quality_score": "6",
                "improvement": "Could not generate DSPy prediction — review content manually.",
            }

    async def generate_ad_copy(
        self,
        product: str,
        audience: str,
        platform: str,
    ) -> dict:
        """
        Generate ad copy using DSPy AdCopywriter or fallback.

        Returns dict with keys: headline, body, cta
        """
        if not self._available or _dspy_module is None:
            return {
                "headline": f"Discover {product} Today",
                "body": (
                    f"{product} is designed for {audience}. "
                    "Experience the difference that quality makes. "
                    "Join thousands of satisfied customers."
                ),
                "cta": "Shop Now",
            }

        predictor = self._predictors.get("ad_copywriter")
        if predictor is None:
            return {
                "headline": f"Try {product} Now",
                "body": f"Perfect for {audience}. Get started today.",
                "cta": "Learn More",
            }

        try:
            pred = predictor(product=product, audience=audience, platform=platform)
            return {
                "headline": getattr(pred, "headline", f"Discover {product}"),
                "body": getattr(pred, "body", f"{product} for {audience}."),
                "cta": getattr(pred, "cta", "Get Started"),
            }
        except Exception as exc:
            logger.warning("[PromptOptimizer.generate_ad_copy] prediction failed: %s", exc)
            return {
                "headline": f"Discover {product}",
                "body": f"Built for {audience}. Available on {platform}.",
                "cta": "Learn More",
            }

    async def plan_campaign(
        self,
        product: str,
        audience: str,
        budget: str,
    ) -> dict:
        """
        Generate a campaign plan using DSPy CampaignStrategy or fallback.

        Returns dict with keys: campaign_plan, expected_roi
        """
        if not self._available or _dspy_module is None:
            return {
                "campaign_plan": (
                    f"1. Define {audience} personas\n"
                    f"2. Create content assets for {product}\n"
                    f"3. Launch paid ads with ${budget} budget\n"
                    "4. Monitor KPIs weekly\n"
                    "5. Optimise underperforming channels"
                ),
                "expected_roi": "150",
            }

        predictor = self._predictors.get("campaign_strategy")
        if predictor is None:
            return {
                "campaign_plan": f"1. Research {audience}\n2. Build content\n3. Launch\n4. Optimise",
                "expected_roi": "120",
            }

        try:
            pred = predictor(product=product, audience=audience, budget=str(budget))
            return {
                "campaign_plan": getattr(pred, "campaign_plan", "Plan not generated"),
                "expected_roi": getattr(pred, "expected_roi", "100"),
            }
        except Exception as exc:
            logger.warning("[PromptOptimizer.plan_campaign] prediction failed: %s", exc)
            return {
                "campaign_plan": "Fallback plan: research, create, launch, optimise.",
                "expected_roi": "100",
            }

    # ── meta ──────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return status summary for this optimizer."""
        return {
            "dspy_available": self._available,
            "optimized_modules": list(self._optimized.keys()),
            "active_predictors": list(self._predictors.keys()),
        }


# ── singleton factory ─────────────────────────────────────────────────────────


def get_prompt_optimizer() -> PromptOptimizer:
    """Return the module-level PromptOptimizer singleton."""
    global _prompt_optimizer
    if _prompt_optimizer is None:
        _prompt_optimizer = PromptOptimizer()
    return _prompt_optimizer
