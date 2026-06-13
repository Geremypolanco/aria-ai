"""
Copy and CTA optimization — scoring, variant generation, and power word analysis.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.marketing.copy")

# ── Power word dictionaries ────────────────────────────────────────────────────

_POWER_WORDS: dict[str, list[str]] = {
    "urgency": ["now", "today", "instantly", "immediately", "hurry", "limited", "deadline", "expire"],
    "value": ["free", "save", "bonus", "discount", "exclusive", "premium", "best", "top"],
    "trust": ["proven", "guaranteed", "certified", "trusted", "secure", "official", "verified"],
    "curiosity": ["secret", "discover", "hidden", "revealed", "surprising", "unknown", "insider"],
    "fear_of_missing_out": ["limited", "last chance", "only", "sold out", "rare", "don't miss", "before it's gone"],
}

_ALL_POWER_WORDS: set[str] = {w for words in _POWER_WORDS.values() for w in words}

_SPAM_WORDS = {"free", "click", "winner", "congratulations", "guarantee", "cash", "prize"}

_ACTION_VERBS = {
    "get", "start", "try", "join", "discover", "learn", "grab", "claim",
    "download", "sign", "buy", "shop", "save", "unlock", "access",
    "watch", "read", "explore", "boost", "transform", "build", "create",
}

_URGENCY_WORDS = {"now", "today", "instantly", "immediately", "limited", "fast", "quick"}

_CURIOSITY_PATTERNS = [
    r"\bwhy\b",
    r"\bsecret\b",
    r"\bhidden\b",
    r"\bmost people\b",
    r"\.\.\.(?!\s*$)",    # trailing ellipsis
    r"you didn't know",
    r"nobody tells",
]


# ── Enums ──────────────────────────────────────────────────────────────────────


class CopyElement(str, Enum):
    HEADLINE = "headline"
    SUBHEADLINE = "subheadline"
    BODY = "body"
    CTA = "cta"
    SUBJECT_LINE = "subject_line"
    META_DESCRIPTION = "meta_description"
    AD_HEADLINE = "ad_headline"
    AD_DESCRIPTION = "ad_description"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class CopyScore:
    element: CopyElement
    original: str
    score: float
    issues: list[str]
    suggestions: list[str]
    improved_version: str = ""


# ── CopyOptimizer ──────────────────────────────────────────────────────────────


class CopyOptimizer:
    """Copy and CTA scoring, variant generation, and optimization."""

    def __init__(self) -> None:
        self._ai = get_ai_client()

    # ── Scoring methods ────────────────────────────────────────────────────────

    def score_headline(self, headline: str) -> CopyScore:
        """Score a headline 0–100 based on conversion best practices."""
        score = 0.0
        issues: list[str] = []
        suggestions: list[str] = []

        words = headline.split()
        word_count = len(words)
        h_lower = headline.lower()

        # Word count: optimal 6–12
        if 6 <= word_count <= 12:
            score += 30
        elif 4 <= word_count < 6 or 12 < word_count <= 15:
            score += 18
            issues.append(f"Headline is {word_count} words — aim for 6–12")
            suggestions.append("Adjust headline length to 6–12 words for optimal impact")
        else:
            score += 8
            issues.append(f"Headline length ({word_count} words) is outside optimal range")
            suggestions.append("Rewrite to 6–12 words — shorter headlines get 40% more clicks")

        # Has a number
        if any(ch.isdigit() for ch in headline):
            score += 15
        else:
            suggestions.append("Add a number (e.g., '7 Ways to...' or '3X Your Results')")

        # Power word present
        if any(pw in h_lower for pw in _ALL_POWER_WORDS):
            score += 20
        else:
            issues.append("No power words detected")
            suggestions.append(f"Add a power word: {', '.join(list(_ALL_POWER_WORDS)[:5])}")

        # Curiosity gap pattern
        has_curiosity = any(re.search(p, h_lower) for p in _CURIOSITY_PATTERNS)
        if has_curiosity:
            score += 15
        else:
            suggestions.append("Create curiosity with 'Why...', 'The Secret to...', or ellipsis")

        # Clarity (no jargon proxy: penalize very long words)
        long_words = [w for w in words if len(w) > 12]
        if not long_words:
            score += 20
        else:
            score += 10
            issues.append(f"Complex words may reduce clarity: {long_words[:3]}")
            suggestions.append("Replace jargon with simpler alternatives")

        return CopyScore(
            element=CopyElement.HEADLINE,
            original=headline,
            score=round(min(score, 100.0), 1),
            issues=issues,
            suggestions=suggestions,
        )

    def score_cta(self, cta: str) -> CopyScore:
        """Score a CTA 0–100 based on conversion principles."""
        score = 0.0
        issues: list[str] = []
        suggestions: list[str] = []

        words = cta.lower().split()
        word_count = len(words)

        # Action verb present
        if any(w in _ACTION_VERBS for w in words):
            score += 30
        else:
            issues.append("CTA missing an action verb")
            suggestions.append(f"Start with a verb: {', '.join(list(_ACTION_VERBS)[:5])}")

        # Urgency word
        if any(w in _URGENCY_WORDS for w in words):
            score += 25
        else:
            suggestions.append("Add urgency: 'now', 'today', or 'instantly'")

        # Value proposition
        value_signals = {"free", "save", "off", "bonus", "exclusive", "get", "access", "unlock"}
        if any(w in value_signals for w in words):
            score += 25
        else:
            issues.append("CTA lacks a clear value proposition")
            suggestions.append("Include the benefit: 'Get Free Access', 'Save 50% Now'")

        # Length: 2–5 words optimal
        if 2 <= word_count <= 5:
            score += 20
        elif 1 == word_count or (5 < word_count <= 8):
            score += 10
            issues.append(f"CTA is {word_count} words — optimal is 2–5")
        else:
            issues.append(f"CTA too long ({word_count} words) — keep it punchy (2–5 words)")
            suggestions.append("Shorten to the essential action + benefit")

        return CopyScore(
            element=CopyElement.CTA,
            original=cta,
            score=round(min(score, 100.0), 1),
            issues=issues,
            suggestions=suggestions,
        )

    def score_email_subject(self, subject: str) -> CopyScore:
        """Score an email subject line 0–100."""
        score = 0.0
        issues: list[str] = []
        suggestions: list[str] = []

        words = subject.split()
        word_count = len(words)
        s_lower = subject.lower()

        # Length: 6–10 words
        if 6 <= word_count <= 10:
            score += 25
        elif 4 <= word_count < 6 or 10 < word_count <= 13:
            score += 15
            issues.append(f"Subject line is {word_count} words — optimal 6–10")
        else:
            score += 5
            issues.append(f"Subject line length ({word_count} words) hurts open rates")
            suggestions.append("Aim for 6–10 words — concise subjects get 20% more opens")

        # Personalization token
        if "{name}" in subject or "{{name}}" in subject:
            score += 20
        else:
            suggestions.append("Add personalization: '{name},' at the start boosts opens ~26%")

        # Urgency or scarcity
        urgency_signals = {"limited", "today", "now", "expires", "last", "hurry", "deadline", "final"}
        if any(w in s_lower for w in urgency_signals):
            score += 20
        else:
            suggestions.append("Add urgency: 'Today Only', 'Last Chance', or expiry date")

        # Question mark
        if "?" in subject:
            score += 15
        else:
            suggestions.append("Try a question — they create curiosity and boost opens")

        # Spam word penalty
        for spam_word in _SPAM_WORDS:
            if spam_word in s_lower:
                score -= 20
                issues.append(f"Spam trigger word detected: '{spam_word}' — may land in spam")

        return CopyScore(
            element=CopyElement.SUBJECT_LINE,
            original=subject,
            score=round(max(0.0, min(score, 100.0)), 1),
            issues=issues,
            suggestions=suggestions,
        )

    # ── AI variant generation ──────────────────────────────────────────────────

    async def generate_variants(
        self,
        element: CopyElement,
        original: str,
        count: int = 3,
    ) -> list[str]:
        """Use AI to generate `count` improved variants of the copy element."""
        if not self._ai:
            return [f"[Variant {i+1}] Improved: {original}" for i in range(count)]

        try:
            response = await self._ai.complete(
                system=(
                    "You are an expert direct-response copywriter. "
                    "Return ONLY a JSON array of improved copy strings. "
                    "No markdown, no explanations — just the JSON array."
                ),
                user=(
                    f"Element type: {element.value}\n"
                    f"Original: {original}\n\n"
                    f"Write {count} improved variants. "
                    f"Each should be more compelling, clear, and conversion-focused. "
                    f"Return as JSON array: [\"variant1\", \"variant2\", ...]"
                ),
                model=AIModel.CREATIVE,
                max_tokens=600,
                json_mode=True,
                agent_name="copy_optimizer",
            )
            if response.success and response.content:
                import json as _json
                parsed = _json.loads(response.content) if isinstance(response.content, str) else response.content
                if isinstance(parsed, list):
                    return [str(v) for v in parsed[:count]]
        except Exception as exc:
            logger.warning("CopyOptimizer.generate_variants: %s", exc)

        # Fallback: return templated variants
        return [f"[Variant {i+1}] {original}" for i in range(count)]

    async def optimize_copy(self, copy_dict: dict[str, str]) -> dict:
        """Score all copy elements and generate improvements for scores <60."""
        _ELEMENT_SCORER = {
            "headline": self.score_headline,
            "subject_line": self.score_email_subject,
            "cta": self.score_cta,
        }

        results: dict[str, dict] = {}

        for key, text in copy_dict.items():
            # Determine element type
            element_key = key.lower().replace(" ", "_")
            scorer = _ELEMENT_SCORER.get(element_key)

            if scorer:
                copy_score = scorer(text)
            else:
                # Generic fallback — use headline scorer as proxy
                copy_score = self.score_headline(text)
                copy_score.element = CopyElement.BODY

            result: dict = {
                "original": text,
                "score": copy_score.score,
                "issues": copy_score.issues,
                "suggestions": copy_score.suggestions,
                "improved": None,
            }

            # Generate improvements for low-scoring copy
            if copy_score.score < 60:
                variants = await self.generate_variants(copy_score.element, text, count=1)
                if variants:
                    result["improved"] = variants[0]
                    copy_score.improved_version = variants[0]

            results[key] = result

        return results

    # ── Reference data ─────────────────────────────────────────────────────────

    def power_words(self) -> dict[str, list[str]]:
        """Return categorized power word dictionary."""
        return _POWER_WORDS.copy()


# ── Singleton ──────────────────────────────────────────────────────────────────

_optimizer_instance: Optional[CopyOptimizer] = None


def get_copy_optimizer() -> CopyOptimizer:
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = CopyOptimizer()
    return _optimizer_instance
