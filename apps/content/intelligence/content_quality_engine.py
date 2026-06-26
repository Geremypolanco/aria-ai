"""
Deep content quality evaluation engine.
Scores content across 8 dimensions and produces actionable improvement roadmaps.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

logger = logging.getLogger("aria.content.intelligence")

_CACHE_KEY = "content:quality:v1"
_CACHE_TTL = 86400 * 30  # 30 days


# ── Enums ──────────────────────────────────────────────────────────────────────


class QualityDimension(StrEnum):
    HOOK_STRENGTH = "hook_strength"
    EMOTIONAL_RESONANCE = "emotional_resonance"
    CLARITY = "clarity"
    SPECIFICITY = "specificity"
    CTA_EFFECTIVENESS = "cta_effectiveness"
    STORYTELLING = "storytelling"
    RETENTION_POWER = "retention_power"
    VALUE_DELIVERY = "value_delivery"


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class QualityScore:
    dimension: QualityDimension
    score: float  # 0-10
    feedback: str
    improvement: str

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension.value,
            "score": self.score,
            "feedback": self.feedback,
            "improvement": self.improvement,
        }


@dataclass
class ContentQualityReport:
    content_id: str
    content_preview: str
    platform: str
    dimensions: list[QualityScore]
    overall_score: float  # 0-10 (avg of dimensions)
    grade: str  # A/B/C/D/F
    top_issues: list[str]
    top_strengths: list[str]
    rewrite_suggestions: list[str]
    analyzed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "content_id": self.content_id,
            "content_preview": self.content_preview,
            "platform": self.platform,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "overall_score": self.overall_score,
            "grade": self.grade,
            "top_issues": self.top_issues,
            "top_strengths": self.top_strengths,
            "rewrite_suggestions": self.rewrite_suggestions,
            "analyzed_at": self.analyzed_at,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _grade(score: float) -> str:
    if score >= 8:
        return "A"
    if score >= 6:
        return "B"
    if score >= 4:
        return "C"
    if score >= 2:
        return "D"
    return "F"


def _heuristic_scores(content: str, platform: str) -> dict[QualityDimension, float]:
    """Score content heuristically across all 8 dimensions."""
    words = content.split()
    word_count = len(words)
    len(content)

    # HOOK_STRENGTH: questions at start, exclamation, short punchy opening
    first_50 = content[:50]
    hook = 5.0
    if "?" in first_50:
        hook += 2.0
    if "!" in first_50:
        hook += 1.0
    if word_count > 0 and len(words[0]) <= 6:
        hook += 1.0

    # EMOTIONAL_RESONANCE: exclamation marks, emotional words
    emotion_words = {
        "amazing",
        "shocking",
        "heartbreaking",
        "inspiring",
        "incredible",
        "powerful",
        "life-changing",
        "devastating",
        "beautiful",
        "terrifying",
    }
    emotion = 4.0 + min(4.0, content.lower().count("!") * 0.5)
    emotion_hits = sum(1 for w in emotion_words if w in content.lower())
    emotion += min(2.0, emotion_hits * 0.7)

    # CLARITY: word count 100-500 = good; too long or too short penalizes
    if 100 <= word_count <= 500:
        clarity = 8.0
    elif word_count < 50:
        clarity = 4.0
    elif word_count > 1000:
        clarity = 6.0
    else:
        clarity = 7.0
    if platform == "twitter" and word_count > 50:
        clarity -= 2.0

    # SPECIFICITY: numbers, percentages, named examples
    import re

    number_count = len(re.findall(r"\b\d+\b", content))
    specificity = min(10.0, 4.0 + number_count * 0.8)

    # CTA_EFFECTIVENESS: call-to-action words
    cta_words = {
        "click",
        "subscribe",
        "follow",
        "buy",
        "sign up",
        "download",
        "learn more",
        "comment",
        "share",
        "like",
        "join",
        "try",
        "get started",
    }
    cta_hits = sum(1 for w in cta_words if w in content.lower())
    cta = min(10.0, 3.0 + cta_hits * 1.5)

    # STORYTELLING: narrative markers
    story_words = {
        "once",
        "then",
        "finally",
        "first",
        "next",
        "last",
        "i was",
        "we were",
        "imagine",
        "story",
        "journey",
        "discovered",
        "realized",
    }
    story_hits = sum(1 for w in story_words if w in content.lower())
    storytelling = min(10.0, 4.0 + story_hits * 1.0)

    # RETENTION_POWER: cliffhangers, suspense words, paragraph breaks
    retention_words = {
        "but",
        "however",
        "wait",
        "plot twist",
        "here's the thing",
        "the truth is",
        "you won't believe",
        "little did",
        "that's when",
    }
    retention_hits = sum(1 for w in retention_words if w in content.lower())
    retention = min(10.0, 4.0 + retention_hits * 0.8 + content.count("\n") * 0.2)

    # VALUE_DELIVERY: tips, steps, lists, "how to", actionable content
    value_words = {
        "tip",
        "step",
        "strategy",
        "technique",
        "method",
        "hack",
        "trick",
        "guide",
        "secret",
        "formula",
        "blueprint",
        "framework",
    }
    value_hits = sum(1 for w in value_words if w in content.lower())
    value = min(10.0, 4.0 + value_hits * 0.8 + (content.count("•") + content.count("-")) * 0.3)

    return {
        QualityDimension.HOOK_STRENGTH: round(min(10.0, hook), 2),
        QualityDimension.EMOTIONAL_RESONANCE: round(min(10.0, emotion), 2),
        QualityDimension.CLARITY: round(min(10.0, clarity), 2),
        QualityDimension.SPECIFICITY: round(min(10.0, specificity), 2),
        QualityDimension.CTA_EFFECTIVENESS: round(min(10.0, cta), 2),
        QualityDimension.STORYTELLING: round(min(10.0, storytelling), 2),
        QualityDimension.RETENTION_POWER: round(min(10.0, retention), 2),
        QualityDimension.VALUE_DELIVERY: round(min(10.0, value), 2),
    }


_DIMENSION_FEEDBACK = {
    QualityDimension.HOOK_STRENGTH: (
        "The opening grabs attention quickly.",
        "The hook lacks punch. Start with a question, bold statement, or surprising fact.",
    ),
    QualityDimension.EMOTIONAL_RESONANCE: (
        "Content evokes strong emotional response.",
        "Add emotional triggers: personal stories, relatable struggles, or aspirational outcomes.",
    ),
    QualityDimension.CLARITY: (
        "Content is clear and easy to follow.",
        "Shorten sentences and use simple language. Aim for Flesch Reading Ease > 60.",
    ),
    QualityDimension.SPECIFICITY: (
        "Good use of numbers and concrete examples.",
        "Add specific numbers, data points, or named examples to increase credibility.",
    ),
    QualityDimension.CTA_EFFECTIVENESS: (
        "Clear call-to-action drives audience action.",
        "Add a single, clear CTA at the end (comment, subscribe, click link).",
    ),
    QualityDimension.STORYTELLING: (
        "Strong narrative structure keeps readers engaged.",
        "Weave in a mini-story: setup, conflict, resolution.",
    ),
    QualityDimension.RETENTION_POWER: (
        "Content uses pattern interrupts and cliffhangers.",
        "Add 'but here's the thing' or 'you won't believe what happened' to maintain interest.",
    ),
    QualityDimension.VALUE_DELIVERY: (
        "Content delivers clear, actionable value.",
        "Include a numbered list of tips or a step-by-step process.",
    ),
}


def _build_quality_scores(
    scores_dict: dict[QualityDimension, float],
) -> list[QualityScore]:
    result = []
    for dim, score in scores_dict.items():
        good_feedback, improvement = _DIMENSION_FEEDBACK[dim]
        feedback = good_feedback if score >= 6 else f"Score {score}/10 — needs improvement."
        result.append(
            QualityScore(
                dimension=dim,
                score=score,
                feedback=feedback,
                improvement=improvement,
            )
        )
    return result


# ── Main class ─────────────────────────────────────────────────────────────────


class ContentQualityEngine:
    """Evaluates content quality across 8 dimensions with AI or heuristic fallback."""

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._reports: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._reports = data
        except Exception as exc:
            logger.warning("ContentQualityEngine._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._reports, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("ContentQualityEngine._save failed: %s", exc)

    async def analyze(
        self,
        content: str,
        platform: str = "general",
        content_id: str | None = None,
    ) -> ContentQualityReport:
        """Analyze content across all 8 quality dimensions."""
        await self._load()
        content_id = content_id or str(uuid.uuid4())
        preview = content[:200] + ("..." if len(content) > 200 else "")
        scores_dict = _heuristic_scores(content, platform)

        # Try AI for holistic assessment
        try:
            if self._ai:
                prompt = (
                    f"Evaluate this {platform} content across 8 dimensions (score 0-10 each):\n"
                    f"Content: {content[:800]}\n\n"
                    "Return JSON with keys: hook_strength, emotional_resonance, clarity, "
                    "specificity, cta_effectiveness, storytelling, retention_power, value_delivery. "
                    "Each key maps to a float score 0-10."
                )
                result = await self._ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    dim_map = {
                        "hook_strength": QualityDimension.HOOK_STRENGTH,
                        "emotional_resonance": QualityDimension.EMOTIONAL_RESONANCE,
                        "clarity": QualityDimension.CLARITY,
                        "specificity": QualityDimension.SPECIFICITY,
                        "cta_effectiveness": QualityDimension.CTA_EFFECTIVENESS,
                        "storytelling": QualityDimension.STORYTELLING,
                        "retention_power": QualityDimension.RETENTION_POWER,
                        "value_delivery": QualityDimension.VALUE_DELIVERY,
                    }
                    for key, dim in dim_map.items():
                        if key in result:
                            scores_dict[dim] = round(min(10.0, max(0.0, float(result[key]))), 2)
        except Exception as exc:
            logger.debug("ContentQualityEngine AI call failed: %s", exc)

        dim_scores = _build_quality_scores(scores_dict)
        overall = round(sum(scores_dict.values()) / len(scores_dict), 2)
        grade = _grade(overall)

        # Top issues: dimensions with lowest scores
        sorted_dims = sorted(dim_scores, key=lambda d: d.score)
        top_issues = [d.improvement for d in sorted_dims[:3]]
        top_strengths = [d.feedback for d in sorted_dims[-2:] if d.score >= 6]

        rewrite_suggestions = [
            "Open with a bold hook in the first 5 words",
            "Add one specific data point or statistic",
            "End with a clear single CTA",
            f"Optimize length for {platform}: aim for {'280 chars' if platform == 'twitter' else '150-300 words' if platform in ('instagram', 'tiktok') else '300-800 words'}",
        ]

        report = ContentQualityReport(
            content_id=content_id,
            content_preview=preview,
            platform=platform,
            dimensions=dim_scores,
            overall_score=overall,
            grade=grade,
            top_issues=top_issues,
            top_strengths=top_strengths,
            rewrite_suggestions=rewrite_suggestions,
        )
        self._reports.append(report.to_dict())
        await self._save()
        return report

    async def score_hook(self, hook_text: str) -> dict:
        """Evaluate a hook/headline and suggest improvements."""
        hook_lower = hook_text.lower()
        score = 5.0

        # Detect hook type
        if hook_lower.startswith(("how", "why", "what", "when", "which")):
            hook_type = "question"
            score += 2.0
        elif any(w in hook_lower for w in ("shocking", "secret", "truth", "exposed", "never")):
            hook_type = "shock"
            score += 2.5
        elif any(w in hook_lower for w in ("you can", "how to", "will help", "guaranteed")):
            hook_type = "promise"
            score += 1.5
        elif any(w in hook_lower for w in ("once", "i was", "when i", "story of")):
            hook_type = "story"
            score += 1.5
        else:
            hook_type = "statement"

        if "?" in hook_text:
            score += 1.0
        if any(str(i) in hook_text for i in range(1, 20)):
            score += 0.5

        score = round(min(10.0, score), 2)
        improvement = (
            "Add a number (e.g., '5 ways to...')"
            if score < 6
            else "Hook is solid — consider A/B testing a question variant"
        )

        return {
            "hook": hook_text,
            "score": score,
            "type": hook_type,
            "improvement": improvement,
        }

    async def analyze_batch(
        self,
        contents: list[str],
        platform: str = "general",
    ) -> list[ContentQualityReport]:
        """Analyze multiple pieces of content, sorted by overall_score descending."""
        reports = []
        for content in contents:
            report = await self.analyze(content, platform)
            reports.append(report)
        reports.sort(key=lambda r: r.overall_score, reverse=True)
        return reports

    async def improvement_roadmap(self, content: str, platform: str) -> list[str]:
        """Return ordered, specific improvement steps for the content."""
        report = await self.analyze(content, platform)
        # Sort dimensions by score ascending — fix worst first
        sorted_dims = sorted(report.dimensions, key=lambda d: d.score)
        roadmap = []
        for i, dim in enumerate(sorted_dims, 1):
            roadmap.append(f"{i}. [{dim.dimension.value.upper()}] {dim.improvement}")
        return roadmap

    def summary(self) -> dict:
        total = len(self._reports)
        avg_score = sum(r.get("overall_score", 0) for r in self._reports) / total if total else 0.0
        grades = [r.get("grade", "F") for r in self._reports]
        grade_dist = {g: grades.count(g) for g in ("A", "B", "C", "D", "F")}
        return {
            "total_analyzed": total,
            "avg_quality_score": round(avg_score, 2),
            "grade_distribution": grade_dist,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_content_quality_engine_instance: ContentQualityEngine | None = None


def get_content_quality_engine() -> ContentQualityEngine:
    global _content_quality_engine_instance
    if _content_quality_engine_instance is None:
        _content_quality_engine_instance = ContentQualityEngine()
    return _content_quality_engine_instance
