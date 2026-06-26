"""
ARIA DSPy — Signature definitions for prompt optimization.

Defines typed DSPy Signatures for marketing-focused tasks.
All classes are only created when dspy is importable; the module
exports safe sentinel names (None) when the package is absent.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aria.cognition.dspy.signatures")

try:
    import dspy

    _DSPY_AVAILABLE = True
except ImportError:
    _DSPY_AVAILABLE = False
    dspy = None  # type: ignore[assignment]

# ── Signature definitions ─────────────────────────────────────────────────────

if _DSPY_AVAILABLE:

    class ContentQuality(dspy.Signature):  # type: ignore[misc]
        """Assess the quality and engagement potential of marketing content."""

        content: str = dspy.InputField(desc="Marketing content to evaluate")
        platform: str = dspy.InputField(desc="Target platform (twitter, instagram, linkedin, etc)")
        quality_score: str = dspy.OutputField(desc="Quality score from 0 to 10 as a string")
        improvement: str = dspy.OutputField(desc="Key improvement suggestion in one sentence")

    class CampaignStrategy(dspy.Signature):  # type: ignore[misc]
        """Generate a strategic marketing campaign plan."""

        product: str = dspy.InputField(desc="Product or service name")
        audience: str = dspy.InputField(desc="Target audience description")
        budget: str = dspy.InputField(desc="Campaign budget in USD")
        campaign_plan: str = dspy.OutputField(desc="Step-by-step campaign plan")
        expected_roi: str = dspy.OutputField(desc="Expected ROI percentage as a string")

    class AdCopywriter(dspy.Signature):  # type: ignore[misc]
        """Write high-converting ad copy using persuasion principles."""

        product: str = dspy.InputField(desc="Product being advertised")
        audience: str = dspy.InputField(desc="Target audience")
        platform: str = dspy.InputField(desc="Ad platform (facebook, google, instagram, etc)")
        headline: str = dspy.OutputField(desc="Attention-grabbing headline under 60 characters")
        body: str = dspy.OutputField(desc="Persuasive body copy in 2-3 sentences")
        cta: str = dspy.OutputField(desc="Call-to-action button text (max 5 words)")

else:
    # Stubs so import always succeeds
    ContentQuality = None  # type: ignore[assignment,misc]
    CampaignStrategy = None  # type: ignore[assignment,misc]
    AdCopywriter = None  # type: ignore[assignment,misc]

    logger.debug("[dspy.signatures] dspy not installed — signatures unavailable")


__all__ = [
    "_DSPY_AVAILABLE",
    "ContentQuality",
    "CampaignStrategy",
    "AdCopywriter",
]
