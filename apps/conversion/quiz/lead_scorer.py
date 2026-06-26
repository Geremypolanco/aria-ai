"""
Lead Scoring — Scores and segments leads based on behavior and quiz results.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache

_LEADS_KEY = "conversion:leads:v1"
_LEADS_TTL = 86400 * 90  # 90 days

_LTV_BY_SEGMENT: dict[str, float] = {
    "premium": 350.0,
    "professional": 350.0,
    "advanced": 200.0,
    "researcher": 200.0,
    "beginner": 75.0,
    "impulse": 75.0,
    "budget": 50.0,
}

_DAYS_TO_CONVERT: dict[str, int] = {
    "impulse": 1,
    "premium": 7,
    "professional": 7,
    "researcher": 14,
    "advanced": 14,
    "beginner": 21,
    "budget": 21,
}


@dataclass
class LeadProfile:
    lead_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    phone: str = ""
    source: str = "organic"  # "quiz"|"popup"|"checkout"|"organic"
    segment: str = "beginner"
    behaviors: list[str] = field(default_factory=list)
    ltv_estimate: float = 75.0
    buy_probability: float = 0.0
    days_to_convert_estimate: int = 21
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "email": self.email,
            "phone": self.phone,
            "source": self.source,
            "segment": self.segment,
            "behaviors": self.behaviors,
            "ltv_estimate": self.ltv_estimate,
            "buy_probability": self.buy_probability,
            "days_to_convert_estimate": self.days_to_convert_estimate,
            "tags": self.tags,
            "created_at": self.created_at,
        }


def _score_lead(
    email: str,
    phone: str,
    source: str,
    behaviors: list[str],
    quiz_segment: str,
    metadata: dict,
) -> float:
    """Calculate buy_probability from available signals."""
    score = 0.0
    if email:
        score += 0.3
    if phone:
        score += 0.2
    if source == "quiz":
        score += 0.2
    if quiz_segment in ("premium", "professional"):
        score += 0.15
    if "page_view" in behaviors or any("view" in b for b in behaviors):
        score += 0.1
    if "add_to_cart" in behaviors or any("cart" in b for b in behaviors):
        score += 0.15
    return min(1.0, score)


class LeadScorer:
    def __init__(self) -> None:
        self._leads: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_LEADS_KEY)
                if isinstance(data, dict):
                    self._leads = data
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_LEADS_KEY, self._leads, ttl_seconds=_LEADS_TTL)
        except Exception:
            pass

    async def score_lead(
        self,
        email: str,
        source: str,
        behaviors: list[str] = None,
        quiz_segment: str = "",
        metadata: dict = None,
    ) -> LeadProfile:
        if metadata is None:
            metadata = {}
        if behaviors is None:
            behaviors = []
        await self._load()

        phone = metadata.get("phone", "")
        segment = quiz_segment if quiz_segment else "beginner"

        buy_probability = _score_lead(email, phone, source, behaviors, segment, metadata)
        ltv_estimate = _LTV_BY_SEGMENT.get(segment, 75.0)
        days_to_convert = _DAYS_TO_CONVERT.get(segment, 21)

        # Build tags
        tags: list[str] = [source, segment]
        if email:
            tags.append("has_email")
        if phone:
            tags.append("has_phone")

        profile = LeadProfile(
            email=email,
            phone=phone,
            source=source,
            segment=segment,
            behaviors=list(behaviors),
            ltv_estimate=ltv_estimate,
            buy_probability=buy_probability,
            days_to_convert_estimate=days_to_convert,
            tags=tags,
        )

        self._leads[profile.lead_id] = profile.to_dict()
        await self._save()
        return profile

    async def enrich_lead(
        self,
        lead_id: str,
        additional_behaviors: list[str],
        purchase_value: float = 0.0,
    ) -> LeadProfile:
        await self._load()

        lead_data = self._leads.get(lead_id, {})
        if not lead_data:
            # Create minimal profile if not found
            profile = LeadProfile(lead_id=lead_id, behaviors=additional_behaviors)
            self._leads[lead_id] = profile.to_dict()
            await self._save()
            return profile

        # Merge behaviors
        existing_behaviors = lead_data.get("behaviors", [])
        merged_behaviors = list(set(existing_behaviors + additional_behaviors))
        lead_data["behaviors"] = merged_behaviors

        # Re-score with updated behaviors
        updated_score = _score_lead(
            lead_data.get("email", ""),
            lead_data.get("phone", ""),
            lead_data.get("source", "organic"),
            merged_behaviors,
            lead_data.get("segment", "beginner"),
            {},
        )
        lead_data["buy_probability"] = updated_score

        # Update LTV if purchase recorded
        if purchase_value > 0:
            lead_data["ltv_estimate"] = max(lead_data.get("ltv_estimate", 0), purchase_value)

        self._leads[lead_id] = lead_data
        await self._save()

        p = lead_data
        return LeadProfile(
            lead_id=p["lead_id"],
            email=p.get("email", ""),
            phone=p.get("phone", ""),
            source=p.get("source", "organic"),
            segment=p.get("segment", "beginner"),
            behaviors=p.get("behaviors", []),
            ltv_estimate=p.get("ltv_estimate", 75.0),
            buy_probability=p.get("buy_probability", 0.0),
            days_to_convert_estimate=p.get("days_to_convert_estimate", 21),
            tags=p.get("tags", []),
            created_at=p.get("created_at", time.time()),
        )

    def hot_leads(self) -> list[dict]:
        """Return leads with buy_probability > 0.7, sorted by probability desc."""
        hot = [lead for lead in self._leads.values() if lead.get("buy_probability", 0.0) > 0.7]
        return sorted(hot, key=lambda l: l.get("buy_probability", 0.0), reverse=True)

    def leads_by_segment(self) -> dict[str, list]:
        """Group leads by segment."""
        result: dict[str, list] = {}
        for lead in self._leads.values():
            seg = lead.get("segment", "unknown")
            if seg not in result:
                result[seg] = []
            result[seg].append(lead)
        return result

    def lead_funnel_report(self) -> dict:
        """Funnel report with projected revenue."""
        all_leads = list(self._leads.values())
        total = len(all_leads)

        by_source: dict[str, int] = {}
        by_segment: dict[str, int] = {}
        hot_count = 0
        total_probability = 0.0
        projected_revenue = 0.0

        for lead in all_leads:
            src = lead.get("source", "unknown")
            seg = lead.get("segment", "unknown")
            prob = lead.get("buy_probability", 0.0)
            ltv = lead.get("ltv_estimate", 0.0)

            by_source[src] = by_source.get(src, 0) + 1
            by_segment[seg] = by_segment.get(seg, 0) + 1
            total_probability += prob
            projected_revenue += ltv * prob
            if prob > 0.7:
                hot_count += 1

        return {
            "total_leads": total,
            "by_source": by_source,
            "by_segment": by_segment,
            "hot_leads_count": hot_count,
            "avg_buy_probability": total_probability / total if total > 0 else 0.0,
            "projected_revenue": round(projected_revenue, 2),
        }


_lead_scorer_instance: LeadScorer | None = None


def get_lead_scorer() -> LeadScorer:
    global _lead_scorer_instance
    if _lead_scorer_instance is None:
        _lead_scorer_instance = LeadScorer()
    return _lead_scorer_instance
