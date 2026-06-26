from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from apps.core.tools.ai_client import AIModel, get_ai_client


class GenericityRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class DifferentiationReport:
    content: str
    genericity_score: float
    risk_level: GenericityRisk
    generic_phrases: list[str]
    differentiation_score: float
    unique_elements: list[str]
    alternatives: list[str]
    created_at: float

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "genericity_score": self.genericity_score,
            "risk_level": self.risk_level.value,
            "generic_phrases": self.generic_phrases,
            "differentiation_score": self.differentiation_score,
            "unique_elements": self.unique_elements,
            "alternatives": self.alternatives,
            "created_at": self.created_at,
        }


class DifferentiationEngine:
    _GENERIC_PHRASES: list[str] = [
        "in today's fast-paced world",
        "leverage synergies",
        "game-changer",
        "revolutionary",
        "seamless experience",
        "cutting-edge",
        "innovative solution",
        "at the end of the day",
        "take it to the next level",
        "the bottom line",
        "move the needle",
        "low-hanging fruit",
        "circle back",
        "deep dive",
        "best practices",
        "going forward",
        "value proposition",
    ]

    _PHRASE_ALTERNATIVES: dict[str, str] = {
        "in today's fast-paced world": "right now",
        "leverage synergies": "combine strengths",
        "game-changer": "significant shift",
        "revolutionary": "a new approach to",
        "seamless experience": "smooth and intuitive",
        "cutting-edge": "the latest",
        "innovative solution": "a new way to solve",
        "at the end of the day": "ultimately",
        "take it to the next level": "improve significantly",
        "the bottom line": "in summary",
        "move the needle": "make measurable progress",
        "low-hanging fruit": "quick wins",
        "circle back": "revisit",
        "deep dive": "detailed look",
        "best practices": "proven methods",
        "going forward": "from now on",
        "value proposition": "core benefit",
    }

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._history: list[dict] = []

    async def analyze(self, content: str) -> DifferentiationReport:
        content_lower = content.lower()
        found_phrases = [p for p in self._GENERIC_PHRASES if p in content_lower]
        genericity_score = min(1.0, len(found_phrases) / max(len(self._GENERIC_PHRASES), 1))

        if genericity_score < 0.1:
            risk_level = GenericityRisk.LOW
        elif genericity_score < 0.3:
            risk_level = GenericityRisk.MEDIUM
        elif genericity_score < 0.6:
            risk_level = GenericityRisk.HIGH
        else:
            risk_level = GenericityRisk.CRITICAL

        # Detect unique elements: numbers, capitalised proper nouns, percentages
        import re

        numbers = re.findall(r"\b\d[\d,.]*%?\b", content)
        proper_nouns = re.findall(r"\b[A-Z][a-z]{2,}\b", content)
        unique_elements: list[str] = []
        if numbers:
            unique_elements.append(f"Specific figures: {', '.join(numbers[:5])}")
        if proper_nouns:
            unique_elements.append(f"Named entities: {', '.join(set(proper_nouns[:5]))}")
        if len(content) > 50 and "unlike" in content_lower:
            unique_elements.append("Contrast framing detected")

        alternatives: list[str] = []
        try:
            prompt = (
                f"Rewrite the following text to remove AI clichés and make it more "
                f"specific and original. Return 3 alternative opening lines only:\n\n{content[:500]}"
            )
            result = await self._ai.complete(prompt, model=AIModel.CREATIVE)
            if result and result.success and result.content:
                alternatives = [
                    line.strip("- •1234567890. ").strip()
                    for line in result.content.split("\n")
                    if line.strip() and len(line.strip()) > 10
                ][:3]
        except Exception:
            alternatives = [
                "Start with a specific data point or customer story",
                "Open with a counterintuitive claim backed by evidence",
                "Lead with the concrete outcome, not the process",
            ]

        differentiation_score = round(1.0 - genericity_score, 3)
        report = DifferentiationReport(
            content=content,
            genericity_score=round(genericity_score, 3),
            risk_level=risk_level,
            generic_phrases=found_phrases,
            differentiation_score=differentiation_score,
            unique_elements=unique_elements,
            alternatives=alternatives,
            created_at=time.time(),
        )
        self._history.append(report.to_dict())
        if len(self._history) > 200:
            self._history = self._history[-200:]
        return report

    async def purge_generic(self, content: str) -> str:
        purged = content
        for phrase, replacement in self._PHRASE_ALTERNATIVES.items():
            # Case-insensitive replacement preserving surrounding context
            import re

            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            purged = pattern.sub(replacement, purged)
        try:
            if any(p in content.lower() for p in self._GENERIC_PHRASES):
                prompt = (
                    f"Rewrite this text to remove all generic AI phrases and make it "
                    f"more specific and original. Keep the same meaning:\n\n{purged}"
                )
                result = await self._ai.complete(prompt, model=AIModel.CREATIVE)
                if result and result.success and result.content and len(result.content) > 20:
                    return result.content.strip()
        except Exception:
            pass
        return purged

    async def generate_unique_angle(self, topic: str, niche: str) -> list[str]:
        angles: list[str] = []
        try:
            prompt = (
                f"Generate 5 unique, non-generic content angles for the topic '{topic}' "
                f"in the {niche} niche. Each angle should be specific, surprising, and "
                f"avoid AI clichés. Format as a numbered list."
            )
            result = await self._ai.complete(prompt, model=AIModel.CREATIVE)
            if result and result.success and result.content:
                lines = [
                    line.strip("- •1234567890. ").strip()
                    for line in result.content.split("\n")
                    if line.strip() and len(line.strip()) > 15
                ]
                angles = lines[:5]
        except Exception:
            pass
        if not angles:
            angles = [
                f"The counter-intuitive truth about {topic} that {niche} experts won't admit",
                f"What {topic} looks like 12 months after everyone stops talking about it",
                f"The {niche} professional's honest cost-benefit breakdown of {topic}",
                f"Three things that went wrong when we tried {topic} (and what fixed them)",
                f"Why most {niche} advice on {topic} is optimised for engagement, not results",
            ]
        return angles[:5]

    async def audience_fatigue_risk(self, content_history: list[str]) -> dict:
        if not content_history:
            return {
                "fatigue_risk": 0.0,
                "overused_patterns": [],
                "refresh_recommendations": [],
            }
        combined = " ".join(content_history).lower()
        overused: list[str] = []
        for phrase in self._GENERIC_PHRASES:
            count = combined.count(phrase)
            if count >= 2:
                overused.append(f'"{phrase}" (appears {count}x)')
        # Topic repetition check: find repeated first words across pieces
        first_words = [c.split()[0].lower() if c.split() else "" for c in content_history]
        from collections import Counter

        word_freq = Counter(first_words)
        for word, freq in word_freq.items():
            if freq >= 3 and len(word) > 3:
                overused.append(f'Opens with "{word}" in {freq} pieces')
        fatigue_risk = min(1.0, len(overused) * 0.15)
        recommendations: list[str] = []
        if fatigue_risk > 0.5:
            recommendations.append(
                "Rotate content formats: add case studies, data reports, or Q&As"
            )
            recommendations.append("Introduce guest perspectives or external validation")
        if overused:
            recommendations.append("Audit and replace the identified overused patterns immediately")
        recommendations.append("Build a phrase blacklist and check content before publishing")
        return {
            "fatigue_risk": round(fatigue_risk, 3),
            "overused_patterns": overused,
            "refresh_recommendations": recommendations,
        }


_differentiation_engine_instance: DifferentiationEngine | None = None


def get_differentiation_engine() -> DifferentiationEngine:
    global _differentiation_engine_instance
    if _differentiation_engine_instance is None:
        _differentiation_engine_instance = DifferentiationEngine()
    return _differentiation_engine_instance
