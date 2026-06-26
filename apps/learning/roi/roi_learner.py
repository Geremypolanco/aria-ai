"""
ROI Learner — Learns which actions, channels, and campaigns generate the best ROI.
Tracks investment vs revenue and detects patterns to optimize future allocation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_ROI_KEY = "learning:roi:v1"
_ROI_TTL = 86400 * 90  # 90 days
_MAX_OBSERVATIONS = 500


@dataclass
class ROIObservation:
    obs_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action_type: str = ""  # "content", "ad", "email", "quiz", "bundle", "flash_sale"
    channel: str = ""
    investment_usd: float = 0.0
    revenue_usd: float = 0.0
    roi_multiplier: float = 0.0  # revenue / investment
    time_to_return_days: int = 0
    context: dict = field(default_factory=dict)  # niche, audience, season, etc.
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "obs_id": self.obs_id,
            "action_type": self.action_type,
            "channel": self.channel,
            "investment_usd": self.investment_usd,
            "revenue_usd": self.revenue_usd,
            "roi_multiplier": self.roi_multiplier,
            "time_to_return_days": self.time_to_return_days,
            "context": self.context,
            "ts": self.ts,
        }


@dataclass
class ROIPattern:
    pattern_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pattern_type: str = ""  # "best_channel", "best_action", "worst_channel", "seasonal"
    description: str = ""
    confidence: float = 0.0  # 0-1
    supporting_obs: int = 0  # number of observations
    recommendation: str = ""
    estimated_uplift_pct: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "confidence": self.confidence,
            "supporting_obs": self.supporting_obs,
            "recommendation": self.recommendation,
            "estimated_uplift_pct": self.estimated_uplift_pct,
            "created_at": self.created_at,
        }


class ROILearner:
    """Learns which actions, channels, and campaigns generate the best ROI."""

    def __init__(self) -> None:
        self._observations: list[dict] = []
        self._patterns: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_ROI_KEY)
                if isinstance(data, dict):
                    self._observations = data.get("observations", [])
                    self._patterns = data.get("patterns", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _ROI_KEY,
                {
                    "observations": self._observations[-_MAX_OBSERVATIONS:],
                    "patterns": self._patterns[-100:],
                },
                ttl_seconds=_ROI_TTL,
            )
        except Exception:
            pass

    async def record_observation(
        self,
        action_type: str,
        channel: str,
        investment_usd: float,
        revenue_usd: float,
        time_to_return_days: int = 30,
        context: dict = None,
    ) -> ROIObservation:
        """Record a new ROI observation."""
        if context is None:
            context = {}
        await self._load()

        roi_multiplier = revenue_usd / max(investment_usd, 0.01)

        obs = ROIObservation(
            action_type=action_type,
            channel=channel,
            investment_usd=investment_usd,
            revenue_usd=revenue_usd,
            roi_multiplier=roi_multiplier,
            time_to_return_days=time_to_return_days,
            context=context or {},
        )

        self._observations.append(obs.to_dict())
        await self._save()
        return obs

    async def detect_patterns(self) -> list[ROIPattern]:
        """AI analyzes last 50 observations and detects patterns."""
        await self._load()

        recent = self._observations[-50:]
        if not recent:
            return []

        ai = get_ai_client()
        obs_summary = "\n".join(
            f"- {o['action_type']} / {o['channel']}: ROI {o['roi_multiplier']:.2f}x "
            f"(${o['investment_usd']:.0f} in, ${o['revenue_usd']:.0f} out, {o['time_to_return_days']}d)"
            for o in recent[:20]
        )

        resp = await ai.complete(
            system=(
                "You are an ROI pattern analyst. Analyze the observations and identify patterns. "
                "Return JSON array of patterns. Each pattern: "
                "{pattern_type, description, confidence (0-1), recommendation, estimated_uplift_pct}. "
                "Pattern types: best_channel, best_action, worst_channel, seasonal. "
                "Return only valid JSON array."
            ),
            user=f"Analyze these ROI observations:\n{obs_summary}\n\nIdentify 3-5 key patterns.",
            model=AIModel.FAST,
            max_tokens=600,
        )

        patterns: list[ROIPattern] = []
        if resp.success and resp.content:
            try:
                import json
                import re

                content = resp.content.strip()
                # Extract JSON array
                match = re.search(r"\[.*\]", content, re.DOTALL)
                if match:
                    raw_patterns = json.loads(match.group())
                    for p in raw_patterns[:5]:
                        if isinstance(p, dict):
                            pattern = ROIPattern(
                                pattern_type=p.get("pattern_type", "best_channel"),
                                description=p.get("description", ""),
                                confidence=float(p.get("confidence", 0.7)),
                                supporting_obs=len(recent),
                                recommendation=p.get("recommendation", ""),
                                estimated_uplift_pct=float(p.get("estimated_uplift_pct", 10.0)),
                            )
                            patterns.append(pattern)
            except Exception:
                # Fallback: create a basic pattern from data
                channel_roi = self.roi_by_channel()
                if channel_roi:
                    best = max(channel_roi.items(), key=lambda x: x[1]["avg_roi"])
                    pattern = ROIPattern(
                        pattern_type="best_channel",
                        description=f"Channel '{best[0]}' shows highest avg ROI of {best[1]['avg_roi']:.2f}x",
                        confidence=0.7,
                        supporting_obs=len(recent),
                        recommendation=f"Increase investment in {best[0]}",
                        estimated_uplift_pct=15.0,
                    )
                    patterns.append(pattern)

        if not patterns and len(recent) > 0:
            # Always return at least one pattern if we have data
            channel_roi = self.roi_by_channel()
            if channel_roi:
                best_ch = max(channel_roi.items(), key=lambda x: x[1]["avg_roi"])
                patterns.append(
                    ROIPattern(
                        pattern_type="best_channel",
                        description=f"Best performing channel: {best_ch[0]}",
                        confidence=0.6,
                        supporting_obs=len(recent),
                        recommendation=f"Prioritize {best_ch[0]}",
                        estimated_uplift_pct=10.0,
                    )
                )

        self._patterns = [p.to_dict() for p in patterns]
        await self._save()
        return patterns

    async def recommend_allocation(self, total_budget_usd: float) -> dict:
        """AI recommends budget split based on observed ROI patterns."""
        await self._load()

        channel_roi = self.roi_by_channel()
        patterns_summary = "\n".join(
            f"- {p['pattern_type']}: {p['description']}" for p in self._patterns[:5]
        )
        channel_summary = "\n".join(
            f"- {ch}: avg ROI {data['avg_roi']:.2f}x ({data['total_observations']} obs)"
            for ch, data in channel_roi.items()
        )

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a budget allocation expert. Based on ROI data, recommend budget allocation. "
                "Return JSON: {allocations: {channel: percentage}, reasoning: str, expected_roi: float}. "
                "Percentages must sum to 100. Return only valid JSON."
            ),
            user=(
                f"Total budget: ${total_budget_usd:.0f}\n\n"
                f"Channel ROI data:\n{channel_summary or 'No data yet'}\n\n"
                f"Patterns detected:\n{patterns_summary or 'No patterns yet'}\n\n"
                "Recommend optimal budget allocation."
            ),
            model=AIModel.FAST,
            max_tokens=400,
        )

        if resp.success and resp.content:
            try:
                import json
                import re

                content = resp.content.strip()
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                    if "allocations" in result:
                        return result
            except Exception:
                pass

        # Fallback allocation based on observed ROI
        if channel_roi:
            total_roi = sum(v["avg_roi"] for v in channel_roi.values())
            allocations = {
                ch: round((data["avg_roi"] / max(total_roi, 0.01)) * 100, 1)
                for ch, data in channel_roi.items()
            }
        else:
            allocations = {"content": 40.0, "email": 30.0, "ads": 20.0, "other": 10.0}

        return {
            "allocations": allocations,
            "reasoning": "Based on observed ROI performance across channels.",
            "expected_roi": (
                sum(v["avg_roi"] for v in channel_roi.values()) / max(len(channel_roi), 1)
                if channel_roi
                else 2.0
            ),
        }

    def best_actions(self, top_n: int = 5) -> list[dict]:
        """Return top N actions sorted by avg roi_multiplier."""
        action_roi: dict[str, list[float]] = {}
        for obs in self._observations:
            at = obs.get("action_type", "unknown")
            action_roi.setdefault(at, []).append(obs.get("roi_multiplier", 0.0))

        ranked = [
            {
                "action_type": at,
                "avg_roi": sum(rois) / len(rois),
                "count": len(rois),
                "total_revenue": sum(
                    o.get("revenue_usd", 0)
                    for o in self._observations
                    if o.get("action_type") == at
                ),
            }
            for at, rois in action_roi.items()
        ]
        ranked.sort(key=lambda x: x["avg_roi"], reverse=True)
        return ranked[:top_n]

    def worst_actions(self, bottom_n: int = 3) -> list[dict]:
        """Return bottom N actions sorted by avg roi_multiplier."""
        all_actions = self.best_actions(top_n=100)
        all_actions.sort(key=lambda x: x["avg_roi"])
        return all_actions[:bottom_n]

    def roi_by_channel(self) -> dict:
        """Return ROI stats grouped by channel."""
        channel_data: dict[str, dict] = {}
        for obs in self._observations:
            ch = obs.get("channel", "unknown")
            if ch not in channel_data:
                channel_data[ch] = {"rois": [], "revenue": 0.0}
            channel_data[ch]["rois"].append(obs.get("roi_multiplier", 0.0))
            channel_data[ch]["revenue"] += obs.get("revenue_usd", 0.0)

        return {
            ch: {
                "avg_roi": sum(d["rois"]) / len(d["rois"]) if d["rois"] else 0.0,
                "total_observations": len(d["rois"]),
                "total_revenue": d["revenue"],
            }
            for ch, d in channel_data.items()
        }

    def learning_report(self) -> dict:
        """Comprehensive learning report."""
        channel_roi = self.roi_by_channel()
        best_actions = self.best_actions(top_n=1)
        best_channel = (
            max(channel_roi.items(), key=lambda x: x[1]["avg_roi"])[0] if channel_roi else "none"
        )
        all_rois = [o.get("roi_multiplier", 0.0) for o in self._observations]
        avg_roi = sum(all_rois) / len(all_rois) if all_rois else 0.0
        total_revenue = sum(o.get("revenue_usd", 0.0) for o in self._observations)

        return {
            "total_observations": len(self._observations),
            "patterns_detected": len(self._patterns),
            "best_channel": best_channel,
            "best_action": best_actions[0]["action_type"] if best_actions else "none",
            "avg_roi_multiplier": round(avg_roi, 3),
            "total_revenue_tracked": round(total_revenue, 2),
        }


# ── SINGLETON ─────────────────────────────────────────────
_instance: ROILearner | None = None


def get_roi_learner() -> ROILearner:
    global _instance
    if _instance is None:
        _instance = ROILearner()
    return _instance
