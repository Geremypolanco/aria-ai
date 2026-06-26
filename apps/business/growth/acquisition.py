"""
Customer Acquisition System — Phase 5
Tracks leads, campaigns, and attribution across acquisition channels.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_LEADS_KEY = "acquisition:leads:v1"
_LEADS_TTL = 86400 * 60  # 60 days


class AcquisitionChannel(StrEnum):
    ORGANIC_SEARCH = "organic_search"
    SOCIAL_ORGANIC = "social_organic"
    EMAIL = "email"
    REFERRAL = "referral"
    PAID_SEARCH = "paid_search"
    AFFILIATE = "affiliate"
    YOUTUBE = "youtube"
    CONTENT = "content"


class LeadQuality(StrEnum):
    HOT = "hot"  # score >= 80
    WARM = "warm"  # score 50-79
    COLD = "cold"  # score < 50


@dataclass
class AcquisitionLead:
    lead_id: str
    email: str
    source: AcquisitionChannel
    score: float
    quality: LeadQuality
    utm_source: str = ""
    utm_campaign: str = ""
    created_at: float = field(default_factory=time.time)
    converted: bool = False
    revenue_attributed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["quality"] = self.quality.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AcquisitionLead:
        d = dict(d)
        d["source"] = AcquisitionChannel(d["source"])
        d["quality"] = LeadQuality(d["quality"])
        return cls(**d)


@dataclass
class AcquisitionCampaign:
    campaign_id: str
    name: str
    channel: AcquisitionChannel
    budget_usd: float
    target_cac: float
    leads_generated: int = 0
    conversions: int = 0
    spend_usd: float = 0.0
    revenue_usd: float = 0.0

    @property
    def actual_cac(self) -> float:
        if self.conversions == 0:
            return 0.0
        return self.spend_usd / self.conversions

    @property
    def roi(self) -> float:
        if self.spend_usd == 0:
            return 0.0
        return (self.revenue_usd - self.spend_usd) / self.spend_usd

    @property
    def roas(self) -> float:
        if self.spend_usd == 0:
            return 0.0
        return self.revenue_usd / self.spend_usd


class AcquisitionEngine:
    """Manages lead capture, qualification, conversion tracking, and funnel metrics."""

    def __init__(self) -> None:
        self._leads: dict[str, AcquisitionLead] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_LEADS_KEY)
            if data and isinstance(data, dict):
                for lead_id, ld in data.items():
                    try:
                        self._leads[lead_id] = AcquisitionLead.from_dict(ld)
                    except Exception:
                        logger.warning("Skipping malformed lead %s", lead_id)
        except Exception:
            logger.exception("AcquisitionEngine._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {lid: lead.to_dict() for lid, lead in self._leads.items()}
            await cache.set(_LEADS_KEY, payload, ttl_seconds=_LEADS_TTL)
        except Exception:
            logger.exception("AcquisitionEngine._save failed")

    # ------------------------------------------------------------------
    # Lead scoring
    # ------------------------------------------------------------------

    def _score_lead(
        self,
        email: str,
        source: AcquisitionChannel,
        utm_campaign: str,
    ) -> float:
        score = 40.0  # base score

        # Known high-value domains
        high_value_domains = {
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
        }
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain and domain not in high_value_domains:
            score += 20.0  # business / custom domain

        # UTM presence signals intent
        if utm_campaign:
            score += 15.0

        # Channel-based scoring
        if source == AcquisitionChannel.REFERRAL:
            score += 25.0
        elif source == AcquisitionChannel.PAID_SEARCH or source == AcquisitionChannel.AFFILIATE:
            score += 10.0
        elif source == AcquisitionChannel.EMAIL:
            score += 5.0

        return min(score, 100.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_lead(
        self,
        email: str,
        source: AcquisitionChannel,
        score: float | None = None,
        utm_source: str = "",
        utm_campaign: str = "",
    ) -> AcquisitionLead:
        """Create a new lead, derive quality, persist to Redis. Deduplicates by email."""
        await self._load()

        # Deduplicate by email
        for existing in self._leads.values():
            if existing.email == email:
                return existing

        computed_score = (
            score if score is not None else self._score_lead(email, source, utm_campaign)
        )

        if computed_score >= 80:
            quality = LeadQuality.HOT
        elif computed_score >= 50:
            quality = LeadQuality.WARM
        else:
            quality = LeadQuality.COLD

        lead = AcquisitionLead(
            lead_id=str(uuid.uuid4()),
            email=email,
            source=source,
            score=computed_score,
            quality=quality,
            utm_source=utm_source,
            utm_campaign=utm_campaign,
        )
        self._leads[lead.lead_id] = lead
        await self._save()
        return lead

    async def qualify_lead(self, lead_id: str) -> LeadQuality | None:
        """Return current LeadQuality for the given lead."""
        await self._load()
        lead = self._leads.get(lead_id)
        if not lead:
            return None
        return lead.quality

    async def convert_lead(self, lead_id: str, revenue_usd: float) -> bool:
        """Mark lead as converted and attribute revenue."""
        await self._load()
        lead = self._leads.get(lead_id)
        if not lead:
            return False
        lead.converted = True
        lead.revenue_attributed = revenue_usd
        await self._save()
        return True

    async def get_leads(
        self,
        quality_filter: LeadQuality | None = None,
        limit: int = 100,
    ) -> list[AcquisitionLead]:
        """Return leads, optionally filtered by quality, newest first."""
        await self._load()
        leads = list(self._leads.values())
        if quality_filter is not None:
            leads = [lp for lp in leads if lp.quality == quality_filter]
        leads.sort(key=lambda lp: lp.created_at, reverse=True)
        return leads[:limit]

    async def funnel_metrics(self) -> dict[str, Any]:
        """Compute top-level funnel health metrics."""
        await self._load()
        total = len(self._leads)
        hot = sum(1 for lp in self._leads.values() if lp.quality == LeadQuality.HOT)
        warm = sum(1 for lp in self._leads.values() if lp.quality == LeadQuality.WARM)
        cold = sum(1 for lp in self._leads.values() if lp.quality == LeadQuality.COLD)
        converted = [lp for lp in self._leads.values() if lp.converted]
        total_revenue = sum(lp.revenue_attributed for lp in converted)
        conversion_rate = len(converted) / total if total > 0 else 0.0
        avg_cac = total_revenue / len(converted) if converted and total_revenue > 0 else 0.0
        return {
            "total_leads": total,
            "hot_count": hot,
            "warm_count": warm,
            "cold_count": cold,
            "conversion_rate": conversion_rate,
            "total_attributed_revenue": total_revenue,
            "avg_cac": avg_cac,
        }

    async def best_acquisition_channels(self) -> list[dict[str, Any]]:
        """Return channels ranked by conversion rate descending."""
        await self._load()
        channel_stats: dict[str, dict[str, int | float]] = {}

        for lead in self._leads.values():
            ch = lead.source.value
            if ch not in channel_stats:
                channel_stats[ch] = {"leads": 0, "conversions": 0, "revenue": 0.0}
            channel_stats[ch]["leads"] += 1  # type: ignore[operator]
            if lead.converted:
                channel_stats[ch]["conversions"] += 1  # type: ignore[operator]
                channel_stats[ch]["revenue"] += lead.revenue_attributed  # type: ignore[operator]

        results = []
        for ch, stats in channel_stats.items():
            leads_count = int(stats["leads"])
            conversions = int(stats["conversions"])
            cr = conversions / leads_count if leads_count > 0 else 0.0
            results.append(
                {
                    "channel": ch,
                    "leads": leads_count,
                    "conversions": conversions,
                    "conversion_rate": cr,
                    "revenue": stats["revenue"],
                }
            )

        results.sort(key=lambda r: r["conversion_rate"], reverse=True)
        return results


# ------------------------------------------------------------------
# Singleton factory
# ------------------------------------------------------------------

_acquisition_engine_instance: AcquisitionEngine | None = None


def get_acquisition_engine() -> AcquisitionEngine:
    global _acquisition_engine_instance
    if _acquisition_engine_instance is None:
        _acquisition_engine_instance = AcquisitionEngine()
    return _acquisition_engine_instance
