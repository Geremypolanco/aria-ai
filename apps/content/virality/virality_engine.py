"""
Advanced virality analysis and title optimization engine.
Detects viral patterns, scores shareability, and generates title alternatives.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.content.virality")


# ── Enums ──────────────────────────────────────────────────────────────────────

class ViralPattern(str, Enum):
    SHOCK_VALUE = "shock_value"
    CURIOSITY_GAP = "curiosity_gap"
    SOCIAL_PROOF = "social_proof"
    FEAR_OF_MISSING_OUT = "fear_of_missing_out"
    HOW_TO = "how_to"
    LIST_FORMAT = "list_format"
    CONTROVERSY = "controversy"
    TRANSFORMATION = "transformation"
    INSIDER_SECRET = "insider_secret"
    CHALLENGE = "challenge"


# ── Pattern keyword triggers ───────────────────────────────────────────────────

_PATTERN_KEYWORDS: dict[ViralPattern, list[str]] = {
    ViralPattern.SHOCK_VALUE: ["shocking", "unbelievable", "exposed", "scandal", "jaw-dropping", "disturbing"],
    ViralPattern.CURIOSITY_GAP: ["you won't believe", "the reason why", "what nobody tells you", "the truth about", "this is why"],
    ViralPattern.SOCIAL_PROOF: ["everyone is", "millions of", "experts agree", "studies show", "trending", "going viral"],
    ViralPattern.FEAR_OF_MISSING_OUT: ["don't miss", "before it's gone", "last chance", "limited time", "running out", "fomo"],
    ViralPattern.HOW_TO: ["how to", "step by step", "tutorial", "guide", "learn", "master"],
    ViralPattern.LIST_FORMAT: ["top 10", "5 ways", "7 tips", "3 secrets", "10 things", "reasons why"],
    ViralPattern.CONTROVERSY: ["controversial", "unpopular opinion", "hot take", "debate", "disagree", "wrong about"],
    ViralPattern.TRANSFORMATION: ["went from", "transformed", "lost 30", "made $", "changed my life", "before and after"],
    ViralPattern.INSIDER_SECRET: ["secret", "insider", "behind the scenes", "what they don't want", "hidden", "classified"],
    ViralPattern.CHALLENGE: ["challenge", "try this", "dare you", "impossible", "can you", "attempt"],
}

# Platform virality multipliers (some patterns work better on certain platforms)
_PLATFORM_PATTERN_FIT: dict[str, list[ViralPattern]] = {
    "tiktok": [ViralPattern.CHALLENGE, ViralPattern.TRANSFORMATION, ViralPattern.SHOCK_VALUE],
    "youtube": [ViralPattern.CURIOSITY_GAP, ViralPattern.HOW_TO, ViralPattern.LIST_FORMAT],
    "instagram": [ViralPattern.TRANSFORMATION, ViralPattern.SOCIAL_PROOF, ViralPattern.INSIDER_SECRET],
    "twitter": [ViralPattern.CONTROVERSY, ViralPattern.SHOCK_VALUE, ViralPattern.HOW_TO],
    "linkedin": [ViralPattern.HOW_TO, ViralPattern.SOCIAL_PROOF, ViralPattern.TRANSFORMATION],
    "blog": [ViralPattern.HOW_TO, ViralPattern.LIST_FORMAT, ViralPattern.CURIOSITY_GAP],
}

# Title templates per pattern for fallback generation
_TITLE_TEMPLATES: dict[ViralPattern, list[str]] = {
    ViralPattern.CURIOSITY_GAP: [
        "The Real Reason {topic} Works (Nobody Talks About This)",
        "What They Don't Tell You About {topic}",
        "This Is Why Most People Fail at {topic}",
    ],
    ViralPattern.HOW_TO: [
        "How to {topic} in 7 Days (Step-by-Step Guide)",
        "The Exact Process I Used to Master {topic}",
        "How to {topic} Even If You're a Complete Beginner",
    ],
    ViralPattern.LIST_FORMAT: [
        "10 {topic} Tips Nobody Tells You",
        "5 {topic} Secrets That Changed Everything",
        "7 Ways to {topic} Faster Than You Think",
    ],
    ViralPattern.TRANSFORMATION: [
        "How I Went From Zero to {topic} in 90 Days",
        "My {topic} Transformation: What Actually Worked",
        "The {topic} Strategy That Changed My Life",
    ],
    ViralPattern.SHOCK_VALUE: [
        "The Shocking Truth About {topic}",
        "I Tried {topic} for 30 Days — Here's What Happened",
        "{topic}: The Brutal Honest Review Nobody Gives",
    ],
    ViralPattern.SOCIAL_PROOF: [
        "Why 1 Million People Are Switching to {topic}",
        "The {topic} Method Everyone Is Talking About",
        "Experts Agree: {topic} Is the Future",
    ],
    ViralPattern.CONTROVERSY: [
        "Unpopular Opinion: {topic} Is Overrated",
        "Why I Quit {topic} (And You Should Too)",
        "The {topic} Advice Everyone Gets Wrong",
    ],
    ViralPattern.INSIDER_SECRET: [
        "The Hidden {topic} Secret Top Creators Use",
        "What Industry Insiders Know About {topic}",
        "The {topic} Blueprint Nobody Shares",
    ],
    ViralPattern.FEAR_OF_MISSING_OUT: [
        "Don't Sleep on {topic} — Here's Why",
        "The {topic} Opportunity You're Missing Right Now",
        "Act Fast: The {topic} Window Is Closing",
    ],
    ViralPattern.CHALLENGE: [
        "I Did the {topic} Challenge for 30 Days",
        "Can You Master {topic} in a Week? (I Tried)",
        "The Ultimate {topic} Challenge — Try It",
    ],
}


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ViralAnalysis:
    content: str
    platform: str
    patterns_detected: list[ViralPattern]
    virality_score: float  # 0-1
    hook_score: float  # 0-1
    shareability_score: float  # 0-1
    emotional_trigger: str
    target_emotion: str
    title_alternatives: list[str]
    analysis_notes: str

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "platform": self.platform,
            "patterns_detected": [p.value for p in self.patterns_detected],
            "virality_score": self.virality_score,
            "hook_score": self.hook_score,
            "shareability_score": self.shareability_score,
            "emotional_trigger": self.emotional_trigger,
            "target_emotion": self.target_emotion,
            "title_alternatives": self.title_alternatives,
            "analysis_notes": self.analysis_notes,
        }


# ── Main class ─────────────────────────────────────────────────────────────────

class ViralityEngine:
    """Detects viral patterns and optimizes content for maximum shareability."""

    def __init__(self) -> None:
        self._ai = get_ai_client()

    def _detect_patterns(self, content: str) -> list[ViralPattern]:
        """Detect viral patterns via keyword matching."""
        content_lower = content.lower()
        detected: list[ViralPattern] = []
        for pattern, keywords in _PATTERN_KEYWORDS.items():
            for kw in keywords:
                if kw in content_lower:
                    detected.append(pattern)
                    break
        return detected

    def _score_virality(self, patterns: list[ViralPattern], platform: str) -> float:
        """Score virality 0-1 based on pattern count and platform fit."""
        if not patterns:
            return 0.10
        base = min(1.0, len(patterns) * 0.15 + 0.10)
        # Bonus for platform-fit patterns
        platform_fit = _PLATFORM_PATTERN_FIT.get(platform.lower(), [])
        fit_count = sum(1 for p in patterns if p in platform_fit)
        fit_bonus = fit_count * 0.08
        return round(min(1.0, base + fit_bonus), 3)

    def _score_hook(self, content: str) -> float:
        """Score hook strength 0-1 from first 100 chars."""
        first = content[:100].lower()
        score = 0.3
        if "?" in first:
            score += 0.25
        if "!" in first:
            score += 0.15
        if any(kw in first for kw in ("you", "your", "how", "why", "secret", "never")):
            score += 0.20
        return round(min(1.0, score), 3)

    def _detect_emotion(self, content: str) -> tuple[str, str]:
        """Return (emotional_trigger, target_emotion)."""
        content_lower = content.lower()
        triggers = {
            "fear": ["fail", "lose", "mistake", "wrong", "danger", "risk"],
            "desire": ["success", "rich", "dream", "achieve", "win", "goal"],
            "curiosity": ["secret", "why", "how", "truth", "hidden", "discover"],
            "anger": ["scam", "lie", "wrong", "stupid", "ridiculous", "unfair"],
            "joy": ["amazing", "incredible", "celebrate", "love", "happy", "great"],
        }
        for emotion, words in triggers.items():
            if any(w in content_lower for w in words):
                return (words[0], emotion)
        return ("general appeal", "neutral")

    def _fallback_titles(self, content: str, platform: str) -> list[str]:
        """Generate title alternatives from templates."""
        patterns = self._detect_patterns(content)
        topic = " ".join(content.split()[:3]).strip("?!.,")
        if not topic:
            topic = "this topic"

        # Pick top 3 templates from detected patterns (or defaults)
        used_patterns = patterns[:3] if patterns else [ViralPattern.HOW_TO, ViralPattern.CURIOSITY_GAP, ViralPattern.LIST_FORMAT]
        titles: list[str] = []
        for pattern in used_patterns[:3]:
            templates = _TITLE_TEMPLATES.get(pattern, _TITLE_TEMPLATES[ViralPattern.HOW_TO])
            title = templates[0].format(topic=topic.title())
            titles.append(title)
        return titles[:3]

    async def analyze(self, content: str, platform: str = "general") -> ViralAnalysis:
        """Analyze content for viral patterns and generate improvement suggestions."""
        patterns = self._detect_patterns(content)
        virality_score = self._score_virality(patterns, platform)
        hook_score = self._score_hook(content)
        shareability_score = round((virality_score + hook_score) / 2, 3)
        emotional_trigger, target_emotion = self._detect_emotion(content)

        # Try AI for title alternatives
        title_alternatives = []
        try:
            if self._ai:
                prompt = (
                    f"Generate 3 viral title/hook alternatives for this {platform} content:\n"
                    f"{content[:500]}\n\n"
                    "Return JSON: {\"titles\": [\"title1\", \"title2\", \"title3\"]}"
                )
                result = await self._ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    title_alternatives = result.get("titles", [])[:3]
        except Exception as exc:
            logger.debug("ViralityEngine.analyze AI call failed: %s", exc)

        if not title_alternatives:
            title_alternatives = self._fallback_titles(content, platform)

        pattern_names = [p.value for p in patterns]
        notes = (
            f"Detected {len(patterns)} viral pattern(s): {', '.join(pattern_names) or 'none'}. "
            f"Platform fit for {platform}: "
            f"{'good' if virality_score > 0.5 else 'needs improvement'}."
        )

        return ViralAnalysis(
            content=content,
            platform=platform,
            patterns_detected=patterns,
            virality_score=virality_score,
            hook_score=hook_score,
            shareability_score=shareability_score,
            emotional_trigger=emotional_trigger,
            target_emotion=target_emotion,
            title_alternatives=title_alternatives,
            analysis_notes=notes,
        )

    async def optimize_title(self, title: str, platform: str = "youtube") -> list[str]:
        """Generate 3 viral title alternatives for the given title."""
        # Try AI
        try:
            if self._ai:
                prompt = (
                    f"Rewrite this {platform} title into 3 more viral versions:\n'{title}'\n\n"
                    "Return JSON: {\"titles\": [\"v1\", \"v2\", \"v3\"]}"
                )
                result = await self._ai.generate(prompt, model=AIModel.FAST, json_mode=True)
                if result and isinstance(result, dict):
                    titles = result.get("titles", [])[:3]
                    if titles:
                        return titles
        except Exception as exc:
            logger.debug("optimize_title AI call failed: %s", exc)

        # Fallback: apply templates to existing title topic
        topic = title[:30].rstrip("?!.,")
        return [
            f"The Truth About {topic} Nobody Tells You",
            f"How to {topic} (The Right Way)",
            f"Why Most People Get {topic} Wrong",
        ]

    async def predict_shares(
        self,
        content: str,
        current_followers: int = 1000,
    ) -> dict:
        """Predict share count and viral probability."""
        analysis = await self.analyze(content)
        virality = analysis.virality_score
        predicted_shares = int(current_followers * virality * 0.08)
        viral_threshold = current_followers * 3
        probability_viral = round(virality * 0.25, 3)

        tips: list[str] = []
        if virality < 0.4:
            tips.append("Add a curiosity gap opener ('The reason nobody talks about...')")
        if analysis.hook_score < 0.5:
            tips.append("Strengthen your first line — make it impossible to scroll past")
        if ViralPattern.LIST_FORMAT not in analysis.patterns_detected:
            tips.append("Use a numbered list format to boost shareability")
        if ViralPattern.SOCIAL_PROOF not in analysis.patterns_detected:
            tips.append("Add social proof ('10,000 people already use this')")

        return {
            "predicted_shares": predicted_shares,
            "viral_threshold": viral_threshold,
            "probability_viral": probability_viral,
            "acceleration_tips": tips[:4],
        }

    async def audience_fatigue_check(self, content_history: list[str]) -> dict:
        """Detect pattern overuse and suggest diversification."""
        if not content_history:
            return {
                "fatigue_detected": False,
                "dominant_pattern": "none",
                "diversity_score": 1.0,
                "recommendation": "No content history to analyze.",
            }

        pattern_counts: dict[str, int] = {}
        for content in content_history:
            patterns = self._detect_patterns(content)
            for p in patterns:
                pattern_counts[p.value] = pattern_counts.get(p.value, 0) + 1

        if not pattern_counts:
            return {
                "fatigue_detected": False,
                "dominant_pattern": "none",
                "diversity_score": 1.0,
                "recommendation": "No strong viral patterns detected — try adding more hooks.",
            }

        dominant = max(pattern_counts, key=lambda k: pattern_counts[k])
        dominant_count = pattern_counts[dominant]
        total_patterns = sum(pattern_counts.values())
        unique_patterns = len(pattern_counts)
        max_possible = len(ViralPattern)

        diversity_score = round(unique_patterns / max_possible, 3)
        fatigue_detected = dominant_count / max(total_patterns, 1) > 0.5

        recommendation = (
            f"You're over-indexing on '{dominant}' ({dominant_count}/{total_patterns} uses). "
            "Try mixing in TRANSFORMATION or CHALLENGE patterns."
            if fatigue_detected
            else f"Good pattern diversity ({unique_patterns} different patterns). Keep it up!"
        )

        return {
            "fatigue_detected": fatigue_detected,
            "dominant_pattern": dominant,
            "diversity_score": diversity_score,
            "recommendation": recommendation,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_virality_engine_instance: Optional[ViralityEngine] = None


def get_virality_engine() -> ViralityEngine:
    global _virality_engine_instance
    if _virality_engine_instance is None:
        _virality_engine_instance = ViralityEngine()
    return _virality_engine_instance
