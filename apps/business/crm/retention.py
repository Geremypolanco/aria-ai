from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from apps.core.memory.redis_client import get_cache

_CAMPAIGNS_KEY = "retention:campaigns:v1"
_OUTREACH_QUEUE_KEY = "retention:outreach_queue:v1"
_CAMPAIGNS_TTL = 86400 * 90


class RetentionAction(str, Enum):
    WIN_BACK_EMAIL = "win_back_email"
    DISCOUNT_OFFER = "discount_offer"
    PERSONAL_OUTREACH = "personal_outreach"
    LOYALTY_REWARD = "loyalty_reward"
    REFERRAL_INVITE = "referral_invite"
    SATISFACTION_SURVEY = "satisfaction_survey"


@dataclass
class RetentionCampaign:
    campaign_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    action: RetentionAction = RetentionAction.WIN_BACK_EMAIL
    target_segment: str = ""
    trigger_condition: str = ""
    customers_targeted: int = 0
    customers_responded: int = 0
    revenue_recovered_usd: float = 0.0
    created_at: float = field(default_factory=time.time)

    @property
    def response_rate(self) -> float:
        return self.customers_responded / max(self.customers_targeted, 1)

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "action": self.action.value,
            "target_segment": self.target_segment,
            "trigger_condition": self.trigger_condition,
            "customers_targeted": self.customers_targeted,
            "customers_responded": self.customers_responded,
            "revenue_recovered_usd": self.revenue_recovered_usd,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RetentionCampaign:
        return cls(
            campaign_id=d["campaign_id"],
            name=d["name"],
            action=RetentionAction(d["action"]),
            target_segment=d.get("target_segment", ""),
            trigger_condition=d.get("trigger_condition", ""),
            customers_targeted=d.get("customers_targeted", 0),
            customers_responded=d.get("customers_responded", 0),
            revenue_recovered_usd=d.get("revenue_recovered_usd", 0.0),
            created_at=d.get("created_at", time.time()),
        )


class RetentionEngine:
    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load_campaigns(self) -> dict[str, RetentionCampaign]:
        try:
            cache = get_cache()
            data = await cache.get(_CAMPAIGNS_KEY)
            if data and isinstance(data, dict):
                return {k: RetentionCampaign.from_dict(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    async def _save_campaigns(self, campaigns: dict[str, RetentionCampaign]) -> None:
        try:
            cache = get_cache()
            await cache.set(_CAMPAIGNS_KEY, {k: v.to_dict() for k, v in campaigns.items()}, ttl_seconds=_CAMPAIGNS_TTL)
        except Exception:
            pass

    async def _queue_outreach(self, items: list[dict]) -> None:
        try:
            cache = get_cache()
            existing = await cache.get(_OUTREACH_QUEUE_KEY) or []
            existing.extend(items)
            await cache.set(_OUTREACH_QUEUE_KEY, existing[-1000:], ttl_seconds=_CAMPAIGNS_TTL)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_campaign(
        self,
        name: str,
        action: RetentionAction,
        target_segment: str,
        trigger_condition: str,
    ) -> RetentionCampaign:
        campaign = RetentionCampaign(
            name=name,
            action=action,
            target_segment=target_segment,
            trigger_condition=trigger_condition,
        )
        campaigns = await self._load_campaigns()
        campaigns[campaign.campaign_id] = campaign
        await self._save_campaigns(campaigns)
        return campaign

    async def run_win_back(self, customers: list[dict]) -> dict:
        inactive = [c for c in customers if (time.time() - c.get("last_purchase_ts", 0)) / 86400 > 60]
        if not inactive:
            return {"campaign_id": None, "targeted": 0, "queued": 0}

        campaign = await self.create_campaign(
            name="Win-Back Campaign",
            action=RetentionAction.WIN_BACK_EMAIL,
            target_segment="inactive_60d",
            trigger_condition="last_purchase > 60 days ago",
        )
        campaign.customers_targeted = len(inactive)

        outreach_items = [
            {
                "campaign_id": campaign.campaign_id,
                "action": RetentionAction.WIN_BACK_EMAIL.value,
                "customer_email": c.get("email", ""),
                "customer_name": c.get("name", ""),
                "queued_at": time.time(),
            }
            for c in inactive
        ]
        await self._queue_outreach(outreach_items)

        campaigns = await self._load_campaigns()
        campaigns[campaign.campaign_id] = campaign
        await self._save_campaigns(campaigns)

        return {
            "campaign_id": campaign.campaign_id,
            "targeted": len(inactive),
            "queued": len(outreach_items),
        }

    async def run_loyalty_rewards(self, customers: list[dict]) -> dict:
        eligible = [c for c in customers if c.get("segment") in ("VIP", "Loyal") or c.get("total_spent_usd", 0) > 200]
        if not eligible:
            return {"campaign_id": None, "targeted": 0}

        campaign = await self.create_campaign(
            name="Loyalty Rewards",
            action=RetentionAction.LOYALTY_REWARD,
            target_segment="vip_loyal",
            trigger_condition="segment in [VIP, Loyal]",
        )
        campaign.customers_targeted = len(eligible)

        outreach_items = [
            {
                "campaign_id": campaign.campaign_id,
                "action": RetentionAction.LOYALTY_REWARD.value,
                "customer_email": c.get("email", ""),
                "queued_at": time.time(),
            }
            for c in eligible
        ]
        await self._queue_outreach(outreach_items)

        campaigns = await self._load_campaigns()
        campaigns[campaign.campaign_id] = campaign
        await self._save_campaigns(campaigns)

        return {"campaign_id": campaign.campaign_id, "targeted": len(eligible)}

    async def churn_prevention_workflow(self, at_risk_customers: list[dict]) -> dict:
        actions_scheduled: dict[str, list[str]] = {
            "discount_offer": [],
            "personal_outreach": [],
            "escalated": [],
        }

        outreach_items: list[dict] = []
        for customer in at_risk_customers:
            risk = customer.get("churn_risk", "medium")
            email = customer.get("email", "")

            if risk == "medium":
                action = RetentionAction.DISCOUNT_OFFER
                actions_scheduled["discount_offer"].append(email)
            elif risk == "high":
                action = RetentionAction.PERSONAL_OUTREACH
                actions_scheduled["personal_outreach"].append(email)
            else:  # critical
                action = RetentionAction.PERSONAL_OUTREACH
                actions_scheduled["escalated"].append(email)

            outreach_items.append({
                "action": action.value,
                "customer_email": email,
                "churn_risk": risk,
                "queued_at": time.time(),
            })

        await self._queue_outreach(outreach_items)
        actions_scheduled["total_scheduled"] = len(outreach_items)  # type: ignore[assignment]
        return actions_scheduled

    async def record_campaign_result(self, campaign_id: str, responses: int, revenue: float) -> bool:
        campaigns = await self._load_campaigns()
        campaign = campaigns.get(campaign_id)
        if not campaign:
            return False
        campaign.customers_responded += responses
        campaign.revenue_recovered_usd += revenue
        await self._save_campaigns(campaigns)
        return True

    async def campaign_summary(self) -> dict:
        campaigns = await self._load_campaigns()
        if not campaigns:
            return {
                "active_campaigns": 0,
                "total_recovered_revenue": 0.0,
                "avg_response_rate": 0.0,
                "best_action_by_response_rate": None,
            }

        total_recovered = sum(c.revenue_recovered_usd for c in campaigns.values())
        avg_response = sum(c.response_rate for c in campaigns.values()) / len(campaigns)

        by_action: dict[str, list[float]] = {}
        for c in campaigns.values():
            key = c.action.value
            by_action.setdefault(key, []).append(c.response_rate)

        best_action = max(by_action, key=lambda k: sum(by_action[k]) / max(len(by_action[k]), 1)) if by_action else None

        return {
            "active_campaigns": len(campaigns),
            "total_recovered_revenue": round(total_recovered, 2),
            "avg_response_rate": round(avg_response, 4),
            "best_action_by_response_rate": best_action,
        }


_retention_instance: RetentionEngine | None = None


def get_retention_engine() -> RetentionEngine:
    global _retention_instance
    if _retention_instance is None:
        _retention_instance = RetentionEngine()
    return _retention_instance
