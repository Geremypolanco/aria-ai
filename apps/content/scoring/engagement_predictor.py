"""
Engagement prediction engine.
Predicts views, engagement rate, and viral probability before publishing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.content.scoring")

# ── Platform base engagement rates ────────────────────────────────────────────

_BASE_ENGAGEMENT: dict[str, float] = {
    "twitter": 0.02,
    "instagram": 0.05,
    "tiktok": 0.08,
    "youtube": 0.04,
    "linkedin": 0.03,
    "blog": 0.01,
    "facebook": 0.02,
    "pinterest": 0.03,
}

# ── Optimal posting times per platform ────────────────────────────────────────

_BEST_TIMES: dict[str, str] = {
    "twitter": "Tuesday–Thursday, 9 AM–11 AM EST",
    "instagram": "Monday, Wednesday, Friday, 11 AM–1 PM EST",
    "tiktok": "Tuesday, Thursday, Friday, 7 PM–9 PM EST",
    "youtube": "Thursday–Saturday, 2 PM–4 PM EST",
    "linkedin": "Tuesday–Thursday, 7 AM–8 AM or 12 PM EST",
    "blog": "Tuesday or Thursday, 9 AM–11 AM EST",
    "facebook": "Wednesday, 11 AM–1 PM EST",
    "pinterest": "Saturday, 8 PM–11 PM EST",
}

# ── Emotional / high-engagement words ─────────────────────────────────────────

_EMOTIONAL_WORDS = {
    "amazing", "shocking", "secret", "proven", "guaranteed", "instantly",
    "exclusive", "free", "powerful", "fail", "love", "hate", "fear",
    "dream", "truth", "never", "always", "everybody", "nobody",
}


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class EngagementPrediction:
    content_preview: str
    platform: str
    predicted_views: int
    predicted_engagement_rate: float  # 0-1
    predicted_shares: int
    predicted_comments: int
    viral_probability: float  # 0-1
    best_publish_time: str
    audience_match_score: float  # 0-1
    confidence: float  # 0-1

    def to_dict(self) -> dict:
        return {
            "content_preview": self.content_preview,
            "platform": self.platform,
            "predicted_views": self.predicted_views,
            "predicted_engagement_rate": self.predicted_engagement_rate,
            "predicted_shares": self.predicted_shares,
            "predicted_comments": self.predicted_comments,
            "viral_probability": self.viral_probability,
            "best_publish_time": self.best_publish_time,
            "audience_match_score": self.audience_match_score,
            "confidence": self.confidence,
        }


# ── Main class ─────────────────────────────────────────────────────────────────

class EngagementPredictor:
    """Predicts engagement metrics for content across platforms."""

    def __init__(self) -> None:
        self._ai = get_ai_client()

    async def predict(
        self,
        content: str,
        platform: str,
        audience_size: int = 1000,
    ) -> EngagementPrediction:
        """Predict engagement metrics for content on a given platform."""
        platform_key = platform.lower()
        base_rate = _BASE_ENGAGEMENT.get(platform_key, 0.02)
        content_lower = content.lower()

        # Adjust for content signals
        multiplier = 1.0
        if "?" in content:
            multiplier += 0.20
        emotional_hits = sum(1 for w in _EMOTIONAL_WORDS if w in content_lower)
        multiplier += emotional_hits * 0.05
        import re
        number_count = len(re.findall(r'\b\d+\b', content))
        if number_count > 0:
            multiplier += 0.10
        word_count = len(content.split())
        if platform_key == "blog" and word_count > 300:
            multiplier += 0.05

        engagement_rate = round(min(1.0, base_rate * multiplier), 4)
        viral_probability = round(min(1.0, engagement_rate * 0.15 * multiplier), 4)
        predicted_views = int(audience_size * (0.1 + engagement_rate))
        predicted_shares = int(predicted_views * engagement_rate * 0.3)
        predicted_comments = int(predicted_views * engagement_rate * 0.1)
        audience_match_score = round(min(1.0, 0.5 + emotional_hits * 0.05 + (1 if number_count > 0 else 0) * 0.1), 3)

        return EngagementPrediction(
            content_preview=content[:200],
            platform=platform,
            predicted_views=predicted_views,
            predicted_engagement_rate=engagement_rate,
            predicted_shares=predicted_shares,
            predicted_comments=predicted_comments,
            viral_probability=viral_probability,
            best_publish_time=_BEST_TIMES.get(platform_key, "Tuesday–Thursday, 10 AM EST"),
            audience_match_score=audience_match_score,
            confidence=0.65,  # no historical data
        )

    async def compare_variations(
        self,
        variations: list[str],
        platform: str,
    ) -> list[dict]:
        """Predict and rank content variations by viral_probability."""
        results = []
        for content in variations:
            pred = await self.predict(content, platform)
            results.append({**pred.to_dict(), "content": content})
        results.sort(key=lambda x: x["viral_probability"], reverse=True)
        for i, item in enumerate(results, 1):
            item["rank"] = i
        return results

    async def best_time_to_post(self, platform: str) -> str:
        """Return optimal posting time string for a platform."""
        return _BEST_TIMES.get(platform.lower(), "Tuesday–Thursday, 10 AM EST")


# ── Singleton ──────────────────────────────────────────────────────────────────

_engagement_predictor_instance: Optional[EngagementPredictor] = None


def get_engagement_predictor() -> EngagementPredictor:
    global _engagement_predictor_instance
    if _engagement_predictor_instance is None:
        _engagement_predictor_instance = EngagementPredictor()
    return _engagement_predictor_instance
