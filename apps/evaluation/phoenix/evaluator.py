"""
AIEvaluator — Evaluate AI response quality across multiple dimensions.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


@dataclass
class EvaluationResult:
    eval_id: str
    content: str
    scores: dict  # dimension -> float 0-1
    overall_score: float
    flags: list[str]  # issues detected
    recommendations: list[str]
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "eval_id": self.eval_id,
            "content_preview": self.content[:100],
            "scores": self.scores,
            "overall_score": self.overall_score,
            "flags": self.flags,
            "recommendations": self.recommendations,
            "ts": self.ts,
        }


class AIEvaluator:
    """
    Multi-dimensional AI response evaluator.

    Dimensions:
    - relevance: how well response addresses the prompt
    - coherence: logical flow and consistency
    - specificity: concrete details vs vague generalities
    - toxicity: harmful content detection
    - hallucination_risk: estimated fabrication risk
    - actionability: can the user act on this?
    """

    GENERIC_PATTERNS = [
        r"as an AI",
        r"I cannot",
        r"I don't have access",
        r"as of my knowledge cutoff",
        r"I apologize",
        r"it's important to note",
        r"in conclusion",
        r"great question",
        r"absolutely",
    ]

    TOXIC_PATTERNS = [
        r"\bhate\b",
        r"\bkill\b",
        r"\bharm\b",
        r"\bviolence\b",
    ]

    def evaluate(
        self, content: str, prompt: str = "", expected_type: str = "general"
    ) -> EvaluationResult:
        import uuid

        scores = {
            "relevance": self._score_relevance(content, prompt),
            "coherence": self._score_coherence(content),
            "specificity": self._score_specificity(content),
            "toxicity_safe": self._score_toxicity(content),
            "hallucination_low": self._score_hallucination(content),
            "actionability": self._score_actionability(content),
        }
        overall = sum(scores.values()) / len(scores)
        flags = self._detect_flags(content, scores)
        recommendations = self._generate_recommendations(flags, scores)

        return EvaluationResult(
            eval_id=str(uuid.uuid4())[:8],
            content=content,
            scores=scores,
            overall_score=round(overall, 3),
            flags=flags,
            recommendations=recommendations,
        )

    def _score_relevance(self, content: str, prompt: str) -> float:
        if not prompt:
            return 0.7
        prompt_words = set(prompt.lower().split())
        content_words = set(content.lower().split())
        overlap = len(prompt_words & content_words)
        return min(1.0, 0.4 + (overlap / max(len(prompt_words), 1)) * 0.6)

    def _score_coherence(self, content: str) -> float:
        if not content:
            return 0.0
        sentences = [s.strip() for s in content.split(".") if s.strip()]
        if len(sentences) < 2:
            return 0.6
        # Simple coherence: consistent length distribution
        lengths = [len(s) for s in sentences]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        coherence = 1.0 - min(1.0, variance / (avg**2 + 1))
        return max(0.3, min(1.0, 0.5 + coherence * 0.5))

    def _score_specificity(self, content: str) -> float:
        score = 0.5
        if re.search(r"\d+", content):
            score += 0.15
        if re.search(r"\b(specifically|exactly|precisely|for example|such as)\b", content, re.I):
            score += 0.15
        for pattern in self.GENERIC_PATTERNS:
            if re.search(pattern, content, re.I):
                score -= 0.1
        return max(0.0, min(1.0, score))

    def _score_toxicity(self, content: str) -> float:
        for pattern in self.TOXIC_PATTERNS:
            if re.search(pattern, content, re.I):
                return 0.2
        return 0.95

    def _score_hallucination(self, content: str) -> float:
        risk = 0.1
        overconfident = ["definitely", "certainly", "100%", "guaranteed", "always", "never fails"]
        for w in overconfident:
            if w.lower() in content.lower():
                risk += 0.1
        return max(0.1, 1.0 - min(0.9, risk))

    def _score_actionability(self, content: str) -> float:
        action_words = [
            "do",
            "create",
            "build",
            "implement",
            "start",
            "use",
            "add",
            "run",
            "try",
            "go to",
        ]
        count = sum(1 for w in action_words if w.lower() in content.lower())
        return min(1.0, 0.3 + count * 0.1)

    def _detect_flags(self, content: str, scores: dict) -> list[str]:
        flags = []
        if scores.get("relevance", 1.0) < 0.5:
            flags.append("LOW_RELEVANCE")
        if scores.get("specificity", 1.0) < 0.4:
            flags.append("TOO_GENERIC")
        if scores.get("toxicity_safe", 1.0) < 0.5:
            flags.append("TOXIC_CONTENT")
        if scores.get("hallucination_low", 1.0) < 0.4:
            flags.append("HIGH_HALLUCINATION_RISK")
        if not content.strip():
            flags.append("EMPTY_RESPONSE")
        return flags

    def _generate_recommendations(self, flags: list[str], scores: dict) -> list[str]:
        recs = []
        if "TOO_GENERIC" in flags:
            recs.append("Add specific data points, examples, or numbers")
        if "LOW_RELEVANCE" in flags:
            recs.append("Address the specific question more directly")
        if "HIGH_HALLUCINATION_RISK" in flags:
            recs.append("Replace overconfident claims with qualified statements")
        if scores.get("actionability", 1.0) < 0.4:
            recs.append("Add concrete next steps or action items")
        return recs

    def batch_evaluate(self, items: list[dict]) -> list[EvaluationResult]:
        return [self.evaluate(item.get("content", ""), item.get("prompt", "")) for item in items]

    def summary_report(self, results: list[EvaluationResult]) -> dict:
        if not results:
            return {"total": 0}
        n = len(results)
        avg_score = sum(r.overall_score for r in results) / n
        flag_counts: dict[str, int] = {}
        for r in results:
            for f in r.flags:
                flag_counts[f] = flag_counts.get(f, 0) + 1
        return {
            "total": n,
            "avg_overall_score": round(avg_score, 3),
            "flag_counts": flag_counts,
            "high_quality": sum(1 for r in results if r.overall_score >= 0.7),
            "low_quality": sum(1 for r in results if r.overall_score < 0.4),
        }


_evaluator_instance: AIEvaluator | None = None


def get_ai_evaluator() -> AIEvaluator:
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = AIEvaluator()
    return _evaluator_instance
