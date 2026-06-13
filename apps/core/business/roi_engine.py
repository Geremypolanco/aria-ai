"""ROI and economic opportunity scoring engine."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_REDIS_KEY = "roi_engine:v1"


def _compute_roi(
    revenue: float,
    effort_hours: float,
    risk: float,
    time_to_revenue_days: int,
    confidence: float,
) -> float:
    revenue_per_hour = revenue / max(effort_hours, 0.1)
    risk_factor = 1.0 - risk * 0.5
    time_factor = 1.0 / (1.0 + time_to_revenue_days / 30.0)
    raw = revenue_per_hour * risk_factor * confidence * time_factor
    return round(min(raw, 1000.0), 4)


@dataclass
class OpportunityScore:
    opportunity_id: str
    name: str
    category: str
    estimated_revenue_usd: float
    estimated_effort_hours: float
    risk_level: float
    time_to_revenue_days: int
    confidence: float
    roi_score: float
    priority_rank: int = 0
    reasoning: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "opportunity_id": self.opportunity_id,
            "name": self.name,
            "category": self.category,
            "estimated_revenue_usd": self.estimated_revenue_usd,
            "estimated_effort_hours": self.estimated_effort_hours,
            "risk_level": self.risk_level,
            "time_to_revenue_days": self.time_to_revenue_days,
            "confidence": self.confidence,
            "roi_score": self.roi_score,
            "priority_rank": self.priority_rank,
            "reasoning": self.reasoning,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityScore":
        return cls(
            opportunity_id=d["opportunity_id"],
            name=d["name"],
            category=d.get("category", "general"),
            estimated_revenue_usd=float(d.get("estimated_revenue_usd", 0)),
            estimated_effort_hours=float(d.get("estimated_effort_hours", 1)),
            risk_level=float(d.get("risk_level", 0.5)),
            time_to_revenue_days=int(d.get("time_to_revenue_days", 7)),
            confidence=float(d.get("confidence", 0.5)),
            roi_score=float(d.get("roi_score", 0)),
            priority_rank=int(d.get("priority_rank", 0)),
            reasoning=d.get("reasoning", ""),
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


class ROIEngine:
    def __init__(self) -> None:
        self._opportunities: dict[str, OpportunityScore] = {}
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from apps.core.memory.redis_client import get_cache
            raw = await get_cache().get(_REDIS_KEY)
            if raw:
                data = json.loads(raw)
                for d in data.get("opportunities", []):
                    opp = OpportunityScore.from_dict(d)
                    self._opportunities[opp.opportunity_id] = opp
        except Exception:
            pass
        self._loaded = True

    async def _persist(self) -> None:
        try:
            from apps.core.memory.redis_client import get_cache
            payload = json.dumps({"opportunities": [o.to_dict() for o in self._opportunities.values()]})
            await get_cache().set(_REDIS_KEY, payload)
        except Exception:
            pass

    async def score_opportunity(
        self,
        name: str,
        category: str,
        estimated_revenue_usd: float,
        estimated_effort_hours: float,
        risk_level: float = 0.3,
        time_to_revenue_days: int = 7,
        confidence: float = 0.7,
        reasoning: str = "",
        opportunity_id: Optional[str] = None,
    ) -> OpportunityScore:
        await self._ensure_loaded()
        import uuid
        oid = opportunity_id or f"opp_{uuid.uuid4().hex[:8]}"
        roi = _compute_roi(
            estimated_revenue_usd, estimated_effort_hours, risk_level,
            time_to_revenue_days, confidence,
        )
        opp = OpportunityScore(
            opportunity_id=oid,
            name=name,
            category=category,
            estimated_revenue_usd=estimated_revenue_usd,
            estimated_effort_hours=estimated_effort_hours,
            risk_level=risk_level,
            time_to_revenue_days=time_to_revenue_days,
            confidence=confidence,
            roi_score=roi,
            reasoning=reasoning,
        )
        self._opportunities[oid] = opp
        await self._persist()
        return opp

    async def rank_opportunities(
        self,
        top_k: int = 10,
        category: Optional[str] = None,
        min_confidence: float = 0.5,
    ) -> list[OpportunityScore]:
        await self._ensure_loaded()
        opps = [
            o for o in self._opportunities.values()
            if o.confidence >= min_confidence
            and (category is None or o.category == category)
        ]
        opps.sort(key=lambda o: o.roi_score, reverse=True)
        for rank, opp in enumerate(opps[:top_k], start=1):
            opp.priority_rank = rank
        return opps[:top_k]

    async def record_outcome(self, opportunity_id: str, actual_revenue: float, success: bool) -> None:
        await self._ensure_loaded()
        opp = self._opportunities.get(opportunity_id)
        if opp is None:
            return
        # Bayesian-style confidence update: pull toward 1.0 on success, 0.0 on failure
        delta = 0.1 if success else -0.15
        opp.confidence = max(0.05, min(0.99, opp.confidence + delta))
        if success and actual_revenue > 0:
            opp.estimated_revenue_usd = (opp.estimated_revenue_usd + actual_revenue) / 2.0
        opp.roi_score = _compute_roi(
            opp.estimated_revenue_usd, opp.estimated_effort_hours,
            opp.risk_level, opp.time_to_revenue_days, opp.confidence,
        )
        await self._persist()

    async def get_portfolio_summary(self) -> dict:
        await self._ensure_loaded()
        opps = list(self._opportunities.values())
        if not opps:
            return {"total_opportunities": 0, "total_estimated_revenue": 0, "avg_roi_score": 0}

        by_cat: dict[str, list[float]] = {}
        for o in opps:
            by_cat.setdefault(o.category, []).append(o.estimated_revenue_usd)

        top = max(opps, key=lambda o: o.roi_score)
        return {
            "total_opportunities": len(opps),
            "total_estimated_revenue_usd": round(sum(o.estimated_revenue_usd for o in opps), 2),
            "avg_roi_score": round(sum(o.roi_score for o in opps) / len(opps), 4),
            "top_opportunity": top.name,
            "top_roi_score": top.roi_score,
            "by_category": {cat: round(sum(rev), 2) for cat, rev in by_cat.items()},
        }

    async def recommend_next_action(self) -> str:
        ranked = await self.rank_opportunities(top_k=1)
        if not ranked:
            return "No scored opportunities. Call score_opportunity() to register candidates."
        top = ranked[0]
        return (
            f"Pursue '{top.name}' ({top.category}): "
            f"ROI score {top.roi_score:.1f}, "
            f"est. ${top.estimated_revenue_usd:.0f} in {top.time_to_revenue_days}d "
            f"({top.confidence*100:.0f}% confidence). {top.reasoning}"
        )

    def to_dict(self) -> dict:
        return {"opportunities": [o.to_dict() for o in self._opportunities.values()]}

    def from_dict(self, d: dict) -> None:
        for item in d.get("opportunities", []):
            opp = OpportunityScore.from_dict(item)
            self._opportunities[opp.opportunity_id] = opp


_engine: Optional[ROIEngine] = None


def get_roi_engine() -> ROIEngine:
    global _engine
    if _engine is None:
        _engine = ROIEngine()
    return _engine
