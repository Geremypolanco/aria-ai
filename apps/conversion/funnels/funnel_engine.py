"""
Funnel Engine — Full funnel builder with stage tracking and conversion optimization.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_FUNNELS_KEY = "conversion:funnels:v1"
_FUNNELS_TTL = 86400 * 90  # 90 days

# Default stage templates per funnel type
_FUNNEL_STAGES: dict[str, list[str]] = {
    "ecommerce": ["awareness", "interest", "consideration", "cart", "checkout", "purchase", "retention"],
    "lead_gen": ["awareness", "interest", "signup", "nurture", "qualified", "converted"],
    "saas": ["discovery", "trial", "activation", "expansion", "renewal"],
    "content": ["discover", "engage", "subscribe", "share", "purchase"],
    "quiz": ["land", "engage", "quiz_complete", "email_capture", "offer", "purchase"],
}


@dataclass
class FunnelStage:
    stage_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    funnel_id: str = ""
    name: str = ""              # "awareness", "interest", "consideration", etc.
    order: int = 0
    entry_count: int = 0
    exit_count: int = 0
    conversion_rate: float = 0.0    # exit_count / max(entry_count, 1)
    avg_time_in_stage_hours: float = 0.0
    drop_off_reason: str = ""
    optimization_opportunity: str = ""

    def to_dict(self) -> dict:
        return {
            "stage_id": self.stage_id,
            "funnel_id": self.funnel_id,
            "name": self.name,
            "order": self.order,
            "entry_count": self.entry_count,
            "exit_count": self.exit_count,
            "conversion_rate": self.conversion_rate,
            "avg_time_in_stage_hours": self.avg_time_in_stage_hours,
            "drop_off_reason": self.drop_off_reason,
            "optimization_opportunity": self.optimization_opportunity,
        }


@dataclass
class Funnel:
    funnel_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    funnel_type: str = ""        # "ecommerce", "lead_gen", "saas", "content", "quiz"
    niche: str = ""
    stages: list = field(default_factory=list)   # list of FunnelStage dicts
    total_entries: int = 0
    total_conversions: int = 0
    overall_cvr: float = 0.0
    revenue_generated: float = 0.0
    top_drop_off_stage: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "funnel_id": self.funnel_id,
            "name": self.name,
            "funnel_type": self.funnel_type,
            "niche": self.niche,
            "stages": self.stages,
            "total_entries": self.total_entries,
            "total_conversions": self.total_conversions,
            "overall_cvr": self.overall_cvr,
            "revenue_generated": self.revenue_generated,
            "top_drop_off_stage": self.top_drop_off_stage,
            "created_at": self.created_at,
        }


class FunnelEngine:
    """Full funnel builder with stage tracking and conversion optimization."""

    def __init__(self) -> None:
        self._funnels: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_FUNNELS_KEY)
                if isinstance(data, dict):
                    self._funnels = data.get("funnels", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _FUNNELS_KEY,
                {"funnels": self._funnels[-500:]},
                ttl_seconds=_FUNNELS_TTL,
            )
        except Exception:
            pass

    async def create_funnel(self, name: str, funnel_type: str, niche: str) -> Funnel:
        """AI designs optimal stages for funnel type."""
        await self._load()

        # Get default stages for this funnel type
        stage_names = _FUNNEL_STAGES.get(funnel_type, _FUNNEL_STAGES["ecommerce"])

        funnel = Funnel(
            name=name,
            funnel_type=funnel_type,
            niche=niche,
        )

        # AI can enhance stage descriptions
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a conversion funnel expert. Given a funnel type and niche, "
                "describe the key optimization opportunity for each stage. "
                "Return JSON array: [{stage_name: str, optimization_opportunity: str, avg_time_hours: float}]. "
                "Return only valid JSON array."
            ),
            user=(
                f"Funnel type: {funnel_type}\nNiche: {niche}\n"
                f"Stages: {', '.join(stage_names)}\n"
                "Describe optimization opportunities for each stage."
            ),
            model=AIModel.FAST,
            max_tokens=500,
        )

        stage_optimizations: dict[str, dict] = {}
        if resp.success and resp.content:
            try:
                import json
                import re
                content = resp.content.strip()
                match = re.search(r'\[.*\]', content, re.DOTALL)
                if match:
                    ai_stages = json.loads(match.group())
                    for s in ai_stages:
                        if isinstance(s, dict):
                            stage_optimizations[s.get("stage_name", "")] = s
            except Exception:
                pass

        # Build stages
        stages = []
        for i, stage_name in enumerate(stage_names):
            ai_info = stage_optimizations.get(stage_name, {})
            stage = FunnelStage(
                funnel_id=funnel.funnel_id,
                name=stage_name,
                order=i,
                avg_time_in_stage_hours=float(ai_info.get("avg_time_hours", 24.0)),
                optimization_opportunity=ai_info.get("optimization_opportunity", f"Optimize {stage_name} conversion"),
            )
            stages.append(stage.to_dict())

        funnel.stages = stages
        self._funnels.append(funnel.to_dict())
        await self._save()
        return funnel

    async def record_stage_entry(
        self, funnel_id: str, stage_name: str, count: int = 1
    ) -> None:
        """Increment entry_count for a stage."""
        await self._load()

        for funnel in self._funnels:
            if funnel.get("funnel_id") == funnel_id:
                for stage in funnel.get("stages", []):
                    if stage.get("name") == stage_name:
                        stage["entry_count"] = stage.get("entry_count", 0) + count
                        # Update overall entries for first stage
                        if stage.get("order", 999) == 0:
                            funnel["total_entries"] = funnel.get("total_entries", 0) + count
                        break
                break

        await self._save()

    async def record_stage_exit(
        self, funnel_id: str, stage_name: str, count: int = 1
    ) -> None:
        """Increment exit_count and recalculate CVR."""
        await self._load()

        for funnel in self._funnels:
            if funnel.get("funnel_id") == funnel_id:
                stages = funnel.get("stages", [])
                for stage in stages:
                    if stage.get("name") == stage_name:
                        stage["exit_count"] = stage.get("exit_count", 0) + count
                        entry = stage.get("entry_count", 0)
                        exit_c = stage.get("exit_count", 0)
                        stage["conversion_rate"] = exit_c / max(entry, 1)

                        # Update overall conversions if this is the last stage
                        is_last = stage.get("order", 0) == len(stages) - 1
                        if is_last:
                            funnel["total_conversions"] = funnel.get("total_conversions", 0) + count
                            total_entries = funnel.get("total_entries", 0)
                            total_convs = funnel.get("total_conversions", 0)
                            funnel["overall_cvr"] = total_convs / max(total_entries, 1)

                        break
                break

        await self._save()

    async def analyze_funnel(self, funnel_id: str) -> dict:
        """AI analyzes funnel and returns optimization recommendations."""
        await self._load()

        funnel = self.get_funnel(funnel_id)
        if not funnel:
            return {"error": "Funnel not found"}

        stages = funnel.get("stages", [])
        stage_summary = "\n".join(
            f"- {s['name']}: entry={s.get('entry_count', 0)}, "
            f"exit={s.get('exit_count', 0)}, CVR={s.get('conversion_rate', 0):.1%}"
            for s in stages
        )

        # Find top drop-off stage
        top_drop_off = ""
        max_drop = 0
        for s in stages:
            entries = s.get("entry_count", 0)
            exits = s.get("exit_count", 0)
            drop = entries - exits
            if drop > max_drop and entries > 0:
                max_drop = drop
                top_drop_off = s.get("name", "")

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a conversion optimization expert. Analyze this funnel and provide actionable recommendations. "
                "Return JSON: {top_opportunity: str, recommended_actions: [str], predicted_cvr_improvement: float, quick_wins: [str]}. "
                "Return only valid JSON."
            ),
            user=(
                f"Funnel: {funnel.get('name')} ({funnel.get('funnel_type')})\n"
                f"Niche: {funnel.get('niche')}\n"
                f"Overall CVR: {funnel.get('overall_cvr', 0):.1%}\n"
                f"Stages:\n{stage_summary}\n\n"
                "Analyze and recommend optimizations."
            ),
            model=AIModel.FAST,
            max_tokens=500,
        )

        if resp.success and resp.content:
            try:
                import json
                import re
                content = resp.content.strip()
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                    result["top_drop_off_stage"] = top_drop_off
                    return result
            except Exception:
                pass

        return {
            "top_opportunity": f"Optimize {top_drop_off or 'early'} stage drop-off",
            "recommended_actions": [
                "A/B test headlines",
                "Add social proof",
                "Simplify checkout",
                "Add exit intent popup",
            ],
            "predicted_cvr_improvement": 0.15,
            "quick_wins": ["Add urgency timer", "Reduce form fields"],
            "top_drop_off_stage": top_drop_off,
        }

    async def optimize_stage(self, funnel_id: str, stage_name: str) -> dict:
        """AI generates specific optimization for a stage."""
        await self._load()

        funnel = self.get_funnel(funnel_id)
        if not funnel:
            return {"error": "Funnel not found"}

        stage_data = None
        for s in funnel.get("stages", []):
            if s.get("name") == stage_name:
                stage_data = s
                break

        if not stage_data:
            return {"error": f"Stage '{stage_name}' not found"}

        current_cvr = stage_data.get("conversion_rate", 0.0)

        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are a conversion rate optimization expert. Generate specific tactics to improve a funnel stage. "
                "Return JSON: {current_cvr: float, target_cvr: float, tactics: [str], ab_test_idea: str}. "
                "Return only valid JSON."
            ),
            user=(
                f"Funnel: {funnel.get('name')} ({funnel.get('funnel_type')})\n"
                f"Stage: {stage_name}\n"
                f"Current CVR: {current_cvr:.1%}\n"
                f"Entry count: {stage_data.get('entry_count', 0)}\n"
                f"Optimization opportunity: {stage_data.get('optimization_opportunity', '')}\n\n"
                "Generate specific optimization tactics for this stage."
            ),
            model=AIModel.FAST,
            max_tokens=400,
        )

        if resp.success and resp.content:
            try:
                import json
                import re
                content = resp.content.strip()
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                    # Ensure required fields
                    result.setdefault("current_cvr", current_cvr)
                    result.setdefault("target_cvr", min(current_cvr + 0.1, 0.9))
                    result.setdefault("tactics", ["Add social proof", "A/B test CTA"])
                    result.setdefault("ab_test_idea", f"Test two versions of {stage_name} page")
                    return result
            except Exception:
                pass

        return {
            "current_cvr": current_cvr,
            "target_cvr": min(current_cvr + 0.1, 0.9),
            "tactics": [
                "Add social proof and testimonials",
                "Simplify the conversion action",
                "Add urgency/scarcity elements",
                "Improve headline clarity",
            ],
            "ab_test_idea": f"Test long-form vs short-form {stage_name} page",
        }

    def get_funnel(self, funnel_id: str) -> Optional[dict]:
        """Get a funnel by ID."""
        for funnel in self._funnels:
            if funnel.get("funnel_id") == funnel_id:
                return funnel
        return None

    def funnel_analytics(self) -> dict:
        """Return analytics across all funnels."""
        total = len(self._funnels)
        by_type: dict[str, int] = {}
        total_revenue = 0.0
        all_cvrs = []

        for f in self._funnels:
            ft = f.get("funnel_type", "unknown")
            by_type[ft] = by_type.get(ft, 0) + 1
            total_revenue += f.get("revenue_generated", 0.0)
            cvr = f.get("overall_cvr", 0.0)
            if cvr > 0:
                all_cvrs.append(cvr)

        avg_cvr = sum(all_cvrs) / len(all_cvrs) if all_cvrs else 0.0

        return {
            "total_funnels": total,
            "by_type": by_type,
            "avg_overall_cvr": round(avg_cvr, 4),
            "total_revenue_tracked": round(total_revenue, 2),
        }

    def list_funnels(self) -> list[dict]:
        """Return all funnels."""
        return list(self._funnels)


# ── SINGLETON ─────────────────────────────────────────────
_instance: Optional[FunnelEngine] = None


def get_funnel_engine() -> FunnelEngine:
    global _instance
    if _instance is None:
        _instance = FunnelEngine()
    return _instance
