from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.tools.ai_client import get_ai_client, AIModel


class PersuasionPrinciple(str, Enum):
    RECIPROCITY = "reciprocity"
    COMMITMENT = "commitment"
    SOCIAL_PROOF = "social_proof"
    AUTHORITY = "authority"
    LIKING = "liking"
    SCARCITY = "scarcity"
    UNITY = "unity"
    LOSS_AVERSION = "loss_aversion"


@dataclass
class PersuasionTactic:
    tactic_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    principle: PersuasionPrinciple = PersuasionPrinciple.RECIPROCITY
    title: str = ""
    description: str = ""
    copy_template: str = ""
    context: str = ""
    estimated_cvr_lift: float = 0.0
    applicable_platforms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tactic_id": self.tactic_id,
            "principle": self.principle.value,
            "title": self.title,
            "description": self.description,
            "copy_template": self.copy_template,
            "context": self.context,
            "estimated_cvr_lift": self.estimated_cvr_lift,
            "applicable_platforms": self.applicable_platforms,
        }


class PersuasionEngine:
    _DEFAULT_TACTICS: list[PersuasionTactic] = [
        PersuasionTactic(
            principle=PersuasionPrinciple.RECIPROCITY,
            title="Give First",
            description="Offer free value before asking for purchase",
            copy_template="Get our FREE [guide/tool] → [benefit]",
            context="Top of funnel, lead generation, email opt-in",
            estimated_cvr_lift=0.15,
            applicable_platforms=["email", "landing page", "social media", "blog"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.SCARCITY,
            title="Limited Availability",
            description="Only [N] spots/units remaining — creates urgency",
            copy_template="⚡ Only [3] left at this price",
            context="Product pages, checkout, flash sales",
            estimated_cvr_lift=0.25,
            applicable_platforms=["landing page", "email", "ads", "checkout"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.SOCIAL_PROOF,
            title="Wisdom of Crowds",
            description="Show that many others have already taken the desired action",
            copy_template="Join [10,000]+ customers who already [achieved result]",
            context="Hero sections, near CTA buttons, testimonial pages",
            estimated_cvr_lift=0.20,
            applicable_platforms=["landing page", "ads", "email", "social media"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.AUTHORITY,
            title="Expert Endorsement",
            description="Leverage credibility from recognized experts or publications",
            copy_template="Trusted by [expert/publication] — [specific endorsement quote]",
            context="Hero sections, about pages, PR placements",
            estimated_cvr_lift=0.18,
            applicable_platforms=["landing page", "email", "ads", "press"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.LOSS_AVERSION,
            title="Don't Miss Out",
            description="Frame the cost of inaction rather than the benefit of action",
            copy_template="Don't let [problem] cost you [amount/time] — fix it today",
            context="Re-engagement emails, retargeting ads, sales pages",
            estimated_cvr_lift=0.22,
            applicable_platforms=["email", "ads", "landing page", "retargeting"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.COMMITMENT,
            title="Small Steps First",
            description="Get micro-commitment before the big ask — foot-in-the-door",
            copy_template="Start with a free [quiz/trial/assessment] — no credit card needed",
            context="Cold traffic, skeptical audiences, high-ticket offers",
            estimated_cvr_lift=0.17,
            applicable_platforms=["ads", "landing page", "email", "social media"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.LIKING,
            title="Relatable Story",
            description="Share authentic stories that mirror the audience's own experience",
            copy_template="I was exactly where you are — [shared struggle]. Here's what changed everything.",
            context="Content marketing, email sequences, video scripts",
            estimated_cvr_lift=0.16,
            applicable_platforms=["email", "video", "blog", "social media"],
        ),
        PersuasionTactic(
            principle=PersuasionPrinciple.UNITY,
            title="Us vs. Them",
            description="Create in-group identity — we share the same values and mission",
            copy_template="[Group identity] don't settle for [inferior alternative]. We built this for you.",
            context="Brand positioning, community building, niche audiences",
            estimated_cvr_lift=0.14,
            applicable_platforms=["landing page", "email", "social media", "community"],
        ),
    ]

    def __init__(self) -> None:
        self._ai = get_ai_client()

    async def recommend_tactics(
        self, context: str, target_emotion: str = "desire"
    ) -> list[PersuasionTactic]:
        context_lower = context.lower()
        scored: list[tuple[float, PersuasionTactic]] = []

        emotion_principle_map: dict[str, list[PersuasionPrinciple]] = {
            "desire": [PersuasionPrinciple.SCARCITY, PersuasionPrinciple.SOCIAL_PROOF, PersuasionPrinciple.LOSS_AVERSION],
            "trust": [PersuasionPrinciple.AUTHORITY, PersuasionPrinciple.SOCIAL_PROOF, PersuasionPrinciple.COMMITMENT],
            "urgency": [PersuasionPrinciple.SCARCITY, PersuasionPrinciple.LOSS_AVERSION, PersuasionPrinciple.COMMITMENT],
            "belonging": [PersuasionPrinciple.UNITY, PersuasionPrinciple.SOCIAL_PROOF, PersuasionPrinciple.LIKING],
            "fear": [PersuasionPrinciple.LOSS_AVERSION, PersuasionPrinciple.AUTHORITY, PersuasionPrinciple.SCARCITY],
        }
        preferred = emotion_principle_map.get(target_emotion, [])

        for tactic in self._DEFAULT_TACTICS:
            score = tactic.estimated_cvr_lift

            # Boost if principle matches emotion
            if tactic.principle in preferred:
                score += 0.1

            # Boost if context keywords match
            for keyword in tactic.context.lower().split(", "):
                if keyword in context_lower:
                    score += 0.05

            scored.append((score, tactic))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:5]]

    async def generate_copy(
        self, principle: PersuasionPrinciple, product: str, audience: str
    ) -> str:
        # Find matching tactic template
        tactic = next(
            (t for t in self._DEFAULT_TACTICS if t.principle == principle), None
        )
        template = tactic.copy_template if tactic else "[value proposition for {product}]"

        try:
            if self._ai:
                prompt = (
                    f"Write persuasive marketing copy using the '{principle.value}' principle "
                    f"for product: '{product}', targeting: '{audience}'. "
                    f"Use this template as inspiration: '{template}'. "
                    f"Return only the copy text, 1-3 sentences."
                )
                result = await self._ai.complete(prompt, model=AIModel.CREATIVE, max_tokens=150)
                if result and result.success and result.content:
                    return result.content.strip()
        except Exception:
            pass

        # Fallback: fill template
        return (
            template.replace("[product]", product)
            .replace("[audience]", audience)
            .replace("[guide/tool]", product)
        )

    async def score_copy(self, copy_text: str) -> dict:
        copy_lower = copy_text.lower()
        detected: list[str] = []
        score = 0.0

        principle_keywords: dict[PersuasionPrinciple, list[str]] = {
            PersuasionPrinciple.SCARCITY: ["only", "limited", "last", "few", "spots", "expires", "ending"],
            PersuasionPrinciple.SOCIAL_PROOF: ["customers", "users", "reviews", "rated", "trusted", "join", "people"],
            PersuasionPrinciple.AUTHORITY: ["expert", "certified", "proven", "endorsed", "featured", "award"],
            PersuasionPrinciple.LOSS_AVERSION: ["don't miss", "lose", "cost you", "risk", "without", "before it's gone"],
            PersuasionPrinciple.RECIPROCITY: ["free", "gift", "bonus", "complimentary", "no charge"],
            PersuasionPrinciple.COMMITMENT: ["start", "try", "begin", "first step", "no obligation"],
            PersuasionPrinciple.LIKING: ["you", "your", "we", "together", "story", "journey"],
            PersuasionPrinciple.UNITY: ["us", "community", "we believe", "our mission", "together"],
        }

        principle_scores: dict[str, float] = {}
        for principle, keywords in principle_keywords.items():
            matches = sum(1 for kw in keywords if kw in copy_lower)
            if matches > 0:
                detected.append(principle.value)
                p_score = min(0.15, matches * 0.05)
                score += p_score
                principle_scores[principle.value] = p_score

        score = min(1.0, score)
        strongest = max(principle_scores, key=lambda k: principle_scores[k]) if principle_scores else ""

        improvement = (
            "Add urgency (scarcity) and social proof to increase conversion rate."
            if "scarcity" not in detected and "social_proof" not in detected
            else "Consider adding a specific CTA with a single clear action."
        )

        return {
            "copy": copy_text,
            "principles_detected": detected,
            "persuasion_score": round(score, 4),
            "strongest_principle": strongest,
            "improvement": improvement,
        }

    async def optimize_cta(
        self, current_cta: str, principle: PersuasionPrinciple
    ) -> list[str]:
        variations: list[str] = []

        try:
            if self._ai:
                prompt = (
                    f"Rewrite this CTA button/text using the '{principle.value}' persuasion principle. "
                    f"Current CTA: '{current_cta}'. "
                    f"Return exactly 3 improved variations, one per line, no numbering or bullets."
                )
                result = await self._ai.complete(prompt, model=AIModel.FAST, max_tokens=120)
                if result and result.success and result.content:
                    lines = [line.strip() for line in result.content.split("\n") if line.strip()]
                    variations = lines[:3]
        except Exception:
            pass

        # Fallback variations per principle
        if not variations:
            fallbacks: dict[PersuasionPrinciple, list[str]] = {
                PersuasionPrinciple.SCARCITY: [
                    f"Claim Your Spot — Only 3 Left",
                    f"Get Access Before It's Gone",
                    f"⚡ Limited Time: {current_cta}",
                ],
                PersuasionPrinciple.SOCIAL_PROOF: [
                    f"Join 10,000+ Happy Customers",
                    f"See Why Everyone Is Switching",
                    f"{current_cta} — 4.9★ Rated",
                ],
                PersuasionPrinciple.LOSS_AVERSION: [
                    f"Stop Losing Money — {current_cta}",
                    f"Don't Fall Behind — Act Now",
                    f"Every Day You Wait Costs You More",
                ],
            }
            variations = fallbacks.get(principle, [
                f"Yes, I Want This!",
                f"Get Instant Access",
                f"Start My Free Trial",
            ])

        return variations[:3]


_engine_instance: Optional[PersuasionEngine] = None


def get_persuasion_engine() -> PersuasionEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PersuasionEngine()
    return _engine_instance
