"""
CMO Agent — Campaign strategy, brand positioning, and growth marketing.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_KEY = "executive:cmo:v1"
_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class CampaignBrief:
    brief_id: str
    campaign_name: str
    objective: str
    target_audience: str
    key_message: str
    channels: list
    budget_usd: float
    timeline_days: int
    kpis: dict
    created_at: float

    def to_dict(self) -> dict:
        return {
            "brief_id": self.brief_id,
            "campaign_name": self.campaign_name,
            "objective": self.objective,
            "target_audience": self.target_audience,
            "key_message": self.key_message,
            "channels": self.channels,
            "budget_usd": self.budget_usd,
            "timeline_days": self.timeline_days,
            "kpis": self.kpis,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CampaignBrief":
        return cls(
            brief_id=data["brief_id"],
            campaign_name=data["campaign_name"],
            objective=data.get("objective", ""),
            target_audience=data.get("target_audience", ""),
            key_message=data.get("key_message", ""),
            channels=data.get("channels", []),
            budget_usd=data.get("budget_usd", 0.0),
            timeline_days=data.get("timeline_days", 30),
            kpis=data.get("kpis", {}),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class BrandPosition:
    position_id: str
    niche: str
    positioning_statement: str
    unique_value: str
    tone: str
    competitors: list
    differentiation: str

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "niche": self.niche,
            "positioning_statement": self.positioning_statement,
            "unique_value": self.unique_value,
            "tone": self.tone,
            "competitors": self.competitors,
            "differentiation": self.differentiation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BrandPosition":
        return cls(
            position_id=data["position_id"],
            niche=data["niche"],
            positioning_statement=data.get("positioning_statement", ""),
            unique_value=data.get("unique_value", ""),
            tone=data.get("tone", "professional"),
            competitors=data.get("competitors", []),
            differentiation=data.get("differentiation", ""),
        )


class CMOAgent:
    def __init__(self) -> None:
        self._briefs: list[dict] = []
        self._positions: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._briefs = data.get("briefs", [])
                    self._positions = data.get("positions", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "briefs": self._briefs[-200:],
                "positions": self._positions[-200:],
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    async def create_campaign_brief(
        self,
        objective: str,
        target_audience: str,
        budget_usd: float,
        channels: list,
    ) -> CampaignBrief:
        await self._load()
        channels_text = ", ".join(channels) if channels else "digital"
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are the CMO. Create a campaign brief. "
                "Reply with: NAME: <campaign name> | MESSAGE: <key message> | "
                "KPI_CTR: <target click rate %> | KPI_CONV: <target conversion %> | "
                "TIMELINE: <days>"
            ),
            user=(
                f"Objective: {objective}\n"
                f"Target audience: {target_audience}\n"
                f"Budget: ${budget_usd:,.0f}\n"
                f"Channels: {channels_text}"
            ),
            model=AIModel.CREATIVE,
            max_tokens=300,
        )
        content = resp.content if resp.success else ""

        campaign_name = f"Campaign {uuid.uuid4().hex[:6].upper()}"
        key_message = f"Transform your results with {objective}"
        kpis = {"ctr_pct": 2.5, "conversion_pct": 3.0}
        timeline_days = 30

        if content:
            try:
                parts = content.split("|")
                for part in parts:
                    part = part.strip()
                    if part.startswith("NAME:"):
                        campaign_name = part.split("NAME:")[-1].strip()
                    elif part.startswith("MESSAGE:"):
                        key_message = part.split("MESSAGE:")[-1].strip()
                    elif part.startswith("KPI_CTR:"):
                        val = part.split(":")[-1].strip()
                        kpis["ctr_pct"] = float("".join(c for c in val if c.isdigit() or c == ".") or "2.5")
                    elif part.startswith("KPI_CONV:"):
                        val = part.split(":")[-1].strip()
                        kpis["conversion_pct"] = float("".join(c for c in val if c.isdigit() or c == ".") or "3.0")
                    elif part.startswith("TIMELINE:"):
                        val = part.split(":")[-1].strip()
                        timeline_days = int("".join(c for c in val if c.isdigit()) or "30")
            except Exception:
                pass

        brief = CampaignBrief(
            brief_id=str(uuid.uuid4()),
            campaign_name=campaign_name,
            objective=objective,
            target_audience=target_audience,
            key_message=key_message,
            channels=list(channels),
            budget_usd=budget_usd,
            timeline_days=timeline_days,
            kpis=kpis,
            created_at=time.time(),
        )
        self._briefs.append(brief.to_dict())
        await self._save()
        return brief

    async def define_brand_position(
        self,
        niche: str,
        strengths: list,
    ) -> BrandPosition:
        await self._load()
        strengths_text = ", ".join(strengths) if strengths else "quality, speed, value"
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are the CMO. Define brand positioning. "
                "Reply with: STATEMENT: <positioning statement> | "
                "VALUE: <unique value proposition> | TONE: <brand tone> | "
                "DIFF: <key differentiator>"
            ),
            user=f"Niche: {niche}\nStrengths: {strengths_text}",
            model=AIModel.CREATIVE,
            max_tokens=300,
        )
        content = resp.content if resp.success else ""

        positioning_statement = f"The #1 {niche} solution for serious professionals"
        unique_value = f"Combining {strengths_text} to deliver unmatched results"
        tone = "professional"
        differentiation = f"Superior {strengths[0] if strengths else 'quality'} at competitive price"

        if content:
            try:
                parts = content.split("|")
                for part in parts:
                    part = part.strip()
                    if part.startswith("STATEMENT:"):
                        positioning_statement = part.split("STATEMENT:")[-1].strip()
                    elif part.startswith("VALUE:"):
                        unique_value = part.split("VALUE:")[-1].strip()
                    elif part.startswith("TONE:"):
                        tone = part.split("TONE:")[-1].strip().lower()
                    elif part.startswith("DIFF:"):
                        differentiation = part.split("DIFF:")[-1].strip()
            except Exception:
                pass

        pos = BrandPosition(
            position_id=str(uuid.uuid4()),
            niche=niche,
            positioning_statement=positioning_statement,
            unique_value=unique_value,
            tone=tone,
            competitors=[],
            differentiation=differentiation,
        )
        self._positions.append(pos.to_dict())
        await self._save()
        return pos

    async def growth_strategy(
        self,
        current_metrics: dict,
        goal_metric: str,
    ) -> dict:
        ai = get_ai_client()
        metrics_text = "; ".join(f"{k}: {v}" for k, v in current_metrics.items())
        resp = await ai.complete(
            system=(
                "You are the CMO. Create a concise growth strategy. "
                "Focus on channel mix, content pillars, ad strategy, and timeline."
            ),
            user=f"Current metrics: {metrics_text}\nGoal: improve {goal_metric}",
            model=AIModel.STRATEGY,
            max_tokens=300,
        )
        content = resp.content if resp.success else ""

        return {
            "channel_mix": ["organic_search", "paid_social", "email", "content"],
            "content_pillars": ["education", "social_proof", "product_demos"],
            "ad_strategy": content or "Run targeted paid ads with retargeting",
            "timeline": "30-day sprint: weeks 1-2 content, weeks 3-4 paid amplification",
            "goal_metric": goal_metric,
            "current_metrics": current_metrics,
        }

    def active_campaigns(self) -> list[dict]:
        # All campaigns are considered active for simplicity
        return list(self._briefs)

    def marketing_summary(self) -> dict:
        all_channels: list[str] = []
        for b in self._briefs:
            all_channels.extend(b.get("channels", []))
        unique_channels = list(set(all_channels))
        return {
            "total_campaigns": len(self._briefs),
            "active_positions": len(self._positions),
            "channels_active": unique_channels,
        }


_instance: Optional[CMOAgent] = None


def get_cmo_agent() -> CMOAgent:
    global _instance
    if _instance is None:
        _instance = CMOAgent()
    return _instance
