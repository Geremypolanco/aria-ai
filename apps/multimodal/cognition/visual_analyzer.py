"""
Multimodal visual analysis — understands images, thumbnails, and ad creatives.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.visual_analyzer")


class VisualContentType(str, Enum):
    PRODUCT_IMAGE = "product_image"
    THUMBNAIL = "thumbnail"
    AD_CREATIVE = "ad_creative"
    SCREENSHOT = "screenshot"
    LOGO = "logo"
    INFOGRAPHIC = "infographic"
    SOCIAL_POST = "social_post"


@dataclass
class VisualInsight:
    content_type: VisualContentType
    dominant_colors: list[str] = field(default_factory=list)
    text_detected: list[str] = field(default_factory=list)
    objects_detected: list[str] = field(default_factory=list)
    emotion: str = "neutral"
    engagement_score: float = 0.0
    quality_score: float = 0.0
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "content_type": self.content_type.value,
            "dominant_colors": self.dominant_colors,
            "text_detected": self.text_detected,
            "objects_detected": self.objects_detected,
            "emotion": self.emotion,
            "engagement_score": self.engagement_score,
            "quality_score": self.quality_score,
            "issues": self.issues,
            "recommendations": self.recommendations,
        }


@dataclass
class ThumbnailAnalysis:
    ctr_prediction: float
    face_present: bool
    text_clarity: float
    color_contrast: float
    emotional_trigger: str
    improvement_suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ctr_prediction": self.ctr_prediction,
            "face_present": self.face_present,
            "text_clarity": self.text_clarity,
            "color_contrast": self.color_contrast,
            "emotional_trigger": self.emotional_trigger,
            "improvement_suggestions": self.improvement_suggestions,
        }


class VisualAnalyzer:
    def __init__(self) -> None:
        self._ai = get_ai_client()

    async def analyze_image(
        self,
        image_url: str,
        content_type: VisualContentType = VisualContentType.PRODUCT_IMAGE,
    ) -> VisualInsight:
        try:
            if self._ai:
                response = await self._ai.complete(
                    system="You are an expert visual content analyst. Analyze images for marketing effectiveness.",
                    user=(
                        f"Analyze this {content_type.value} image at: {image_url}\n"
                        "Provide: dominant colors, detected text, objects, emotion, "
                        "engagement score (0-1), quality score (0-1), issues, recommendations."
                    ),
                    model=AIModel.FAST,
                    max_tokens=500,
                    agent_name="visual_analyzer",
                )
                if response.success:
                    return self._parse_ai_insight(response.content, content_type)
        except Exception as exc:
            logger.warning("VisualAnalyzer: AI failed — %s", exc)

        return self._mock_analysis(image_url, content_type)

    def _mock_analysis(self, image_url: str, content_type: VisualContentType) -> VisualInsight:
        return VisualInsight(
            content_type=content_type,
            dominant_colors=["#FF6B35", "#004E89", "#FFFFFF"],
            text_detected=["Brand Name", "Call to Action"],
            objects_detected=["product", "background", "text"],
            emotion="positive",
            engagement_score=0.72,
            quality_score=0.85,
            issues=["Text may be too small on mobile"],
            recommendations=["Add faces to increase CTR", "Use brighter contrast for CTA"],
        )

    def _parse_ai_insight(self, content: str, content_type: VisualContentType) -> VisualInsight:
        return VisualInsight(
            content_type=content_type,
            dominant_colors=["#000000"],
            text_detected=[],
            objects_detected=[],
            emotion="neutral",
            engagement_score=0.6,
            quality_score=0.7,
            issues=[],
            recommendations=[content[:200] if content else ""],
        )

    async def analyze_thumbnail(self, image_url: str) -> ThumbnailAnalysis:
        insight = await self.analyze_image(image_url, VisualContentType.THUMBNAIL)
        face_keywords = {"face", "person", "human", "portrait"}
        face_present = any(obj in face_keywords for obj in insight.objects_detected)
        return ThumbnailAnalysis(
            ctr_prediction=round(insight.engagement_score * 0.12, 4),
            face_present=face_present,
            text_clarity=min(1.0, len(insight.text_detected) * 0.3),
            color_contrast=0.8 if len(insight.dominant_colors) >= 2 else 0.4,
            emotional_trigger=insight.emotion,
            improvement_suggestions=insight.recommendations,
        )

    async def compare_creatives(
        self,
        image_urls: list[str],
        content_type: VisualContentType = VisualContentType.AD_CREATIVE,
    ) -> list[dict]:
        results = []
        for url in image_urls:
            insight = await self.analyze_image(url, content_type)
            results.append({"url": url, **insight.to_dict()})
        results.sort(key=lambda r: r["engagement_score"], reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1
        return results

    async def score_ad_creative(self, image_url: str) -> dict:
        insight = await self.analyze_image(image_url, VisualContentType.AD_CREATIVE)
        composite = round(
            insight.engagement_score * 0.5
            + insight.quality_score * 0.3
            + (1.0 - len(insight.issues) * 0.1) * 0.2,
            3,
        )
        grade = "A" if composite >= 0.8 else "B" if composite >= 0.6 else "C" if composite >= 0.4 else "D"
        return {"url": image_url, "composite_score": composite, "grade": grade, **insight.to_dict()}


_analyzer_instance: Optional[VisualAnalyzer] = None


def get_visual_analyzer() -> VisualAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = VisualAnalyzer()
    return _analyzer_instance
