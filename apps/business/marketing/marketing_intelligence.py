"""
Strategic marketing intelligence — competitor analysis, channel scoring,
opportunity identification, funnel health, and growth planning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.marketing.intelligence")

_REDIS_KEY = "marketing_intel:v1"
_TTL = 86400 * 7  # 7 days

# ── Funnel benchmarks ──────────────────────────────────────────────────────────

_FUNNEL_BENCHMARKS = {
    "awareness_ctr": 0.02,          # >2% CTR
    "consideration_engagement": 0.05,  # >5% engagement
    "conversion_rate": 0.02,        # >2% conversion
}

_FUNNEL_RECOMMENDATIONS: dict[str, str] = {
    "awareness_ctr": (
        "Improve ad creatives and headline testing. "
        "A/B test CTAs and visuals to boost CTR above 2%."
    ),
    "consideration_engagement": (
        "Deepen content value and add interactive elements. "
        "Target engagement rate above 5% with quizzes, polls, or long-form video."
    ),
    "conversion_rate": (
        "Optimize landing pages and checkout flow. "
        "Use social proof and urgency triggers to push conversion above 2%."
    ),
}

# ── Default competitor patterns by niche ──────────────────────────────────────

_DEFAULT_COMPETITOR_PATTERNS: dict[str, list[dict]] = {
    "ecommerce": [
        {
            "name": "Competitor A",
            "estimated_traffic": 50000,
            "primary_keywords": ["best products", "buy online", "deals"],
            "content_cadence": "3x/week blog + daily social",
            "pricing_strategy": "Mid-market with frequent sales",
            "weaknesses": ["Slow site speed", "Poor mobile UX", "Limited video content"],
        }
    ],
    "saas": [
        {
            "name": "Competitor B",
            "estimated_traffic": 80000,
            "primary_keywords": ["software", "tool", "platform"],
            "content_cadence": "Weekly blog + bi-weekly newsletter",
            "pricing_strategy": "Freemium with paid tiers",
            "weaknesses": ["Weak community", "Thin content library", "No YouTube presence"],
        }
    ],
    "default": [
        {
            "name": "Market Leader",
            "estimated_traffic": 100000,
            "primary_keywords": ["solution", "guide", "best"],
            "content_cadence": "Daily content across all channels",
            "pricing_strategy": "Premium positioning",
            "weaknesses": ["Low personalization", "Slow to respond to trends", "High churn"],
        }
    ],
}

# ── Channel score weights ──────────────────────────────────────────────────────

_CHANNEL_WEIGHTS = {
    "roi": 0.40,
    "volume": 0.30,
    "effort": 0.20,       # lower effort = higher score
    "time_to_results": 0.10,  # faster = higher score
}

# ── Growth plan templates by objective ────────────────────────────────────────

_GROWTH_PLAN_TEMPLATES: dict[str, dict] = {
    "awareness": {
        "recommended_channels": ["tiktok", "youtube", "instagram", "twitter"],
        "kpis": ["reach", "impressions", "follower_growth", "brand_mentions"],
        "focus": "Top-of-funnel content volume and virality",
    },
    "leads": {
        "recommended_channels": ["seo", "paid_search", "linkedin", "email"],
        "kpis": ["lead_volume", "cpl", "mql_rate", "demo_requests"],
        "focus": "Lead magnet distribution and retargeting",
    },
    "revenue": {
        "recommended_channels": ["email", "seo", "paid_search", "affiliate"],
        "kpis": ["revenue", "roas", "ltv", "conversion_rate"],
        "focus": "Conversion optimization and upsell sequences",
    },
    "retention": {
        "recommended_channels": ["email", "sms", "community", "blog"],
        "kpis": ["churn_rate", "nps", "repeat_purchase_rate", "engagement"],
        "focus": "Post-purchase nurture and loyalty programs",
    },
}


# ── Enums ──────────────────────────────────────────────────────────────────────


class MarketingChannel(str, Enum):
    SEO = "seo"
    PAID_SEARCH = "paid_search"
    SOCIAL_ORGANIC = "social_organic"
    PAID_SOCIAL = "paid_social"
    EMAIL = "email"
    CONTENT = "content"
    AFFILIATE = "affiliate"
    INFLUENCER = "influencer"
    REFERRAL = "referral"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class CompetitorProfile:
    name: str
    estimated_traffic: int
    primary_keywords: list[str]
    content_cadence: str
    pricing_strategy: str
    weaknesses: list[str]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "estimated_traffic": self.estimated_traffic,
            "primary_keywords": self.primary_keywords,
            "content_cadence": self.content_cadence,
            "pricing_strategy": self.pricing_strategy,
            "weaknesses": self.weaknesses,
        }


@dataclass
class MarketOpportunity:
    opportunity: str
    channel: MarketingChannel
    effort: str
    estimated_impact: str
    priority_score: float
    action_items: list[str]

    def to_dict(self) -> dict:
        return {
            "opportunity": self.opportunity,
            "channel": self.channel.value,
            "effort": self.effort,
            "estimated_impact": self.estimated_impact,
            "priority_score": self.priority_score,
            "action_items": self.action_items,
        }


# ── MarketingIntelligence ──────────────────────────────────────────────────────


class MarketingIntelligence:
    """Strategic marketing intelligence — analysis, scoring, and growth planning."""

    def __init__(self) -> None:
        self._cache = get_cache()
        self._ai = get_ai_client()
        self._state: dict = {}

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _load(self) -> dict:
        try:
            data = await self._cache.get(_REDIS_KEY)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def _save(self, data: dict) -> None:
        try:
            await self._cache.set(_REDIS_KEY, data, ttl_seconds=_TTL)
        except Exception as exc:
            logger.warning("MarketingIntelligence._save: %s", exc)

    # ── Core methods ──────────────────────────────────────────────────────────

    async def analyze_market(
        self,
        niche: str,
        competitors: Optional[list[str]] = None,
    ) -> dict:
        """Build competitor profiles and identify market gaps."""
        competitor_profiles: list[CompetitorProfile] = []

        # Try AI-powered analysis first
        if self._ai and competitors:
            try:
                comp_list = ", ".join(competitors)
                response = await self._ai.complete(
                    system=(
                        "You are a strategic market analyst. Return ONLY valid JSON — "
                        "a JSON array of competitor profile objects."
                    ),
                    user=(
                        f"Niche: {niche}\nCompetitors: {comp_list}\n\n"
                        f"For each competitor, analyze and return JSON array where each item has: "
                        f"name, estimated_traffic (int), primary_keywords (list), "
                        f"content_cadence (str), pricing_strategy (str), weaknesses (list of 3)."
                    ),
                    model=AIModel.STRATEGY,
                    max_tokens=1500,
                    json_mode=True,
                    agent_name="marketing_intel",
                )
                if response.success and response.content:
                    import json as _json
                    parsed = _json.loads(response.content) if isinstance(response.content, str) else response.content
                    if isinstance(parsed, list):
                        for item in parsed:
                            competitor_profiles.append(
                                CompetitorProfile(
                                    name=item.get("name", "Unknown"),
                                    estimated_traffic=item.get("estimated_traffic", 10000),
                                    primary_keywords=item.get("primary_keywords", []),
                                    content_cadence=item.get("content_cadence", "weekly"),
                                    pricing_strategy=item.get("pricing_strategy", "market-rate"),
                                    weaknesses=item.get("weaknesses", []),
                                )
                            )
            except Exception as exc:
                logger.warning("MarketingIntelligence.analyze_market AI: %s", exc)

        # Fallback to deterministic defaults
        if not competitor_profiles:
            niche_lower = niche.lower()
            patterns = _DEFAULT_COMPETITOR_PATTERNS.get(
                niche_lower,
                _DEFAULT_COMPETITOR_PATTERNS["default"],
            )
            if competitors:
                for i, comp_name in enumerate(competitors):
                    base = patterns[i % len(patterns)].copy()
                    base["name"] = comp_name
                    competitor_profiles.append(CompetitorProfile(**base))
            else:
                for p in patterns:
                    competitor_profiles.append(CompetitorProfile(**p))

        # Identify gaps from combined weaknesses
        all_weaknesses: list[str] = []
        for cp in competitor_profiles:
            all_weaknesses.extend(cp.weaknesses)

        gaps = list(dict.fromkeys(all_weaknesses))  # deduplicate preserving order

        # Derive opportunities from gaps
        opportunities = [
            f"Capitalize on competitor gap: {gap}" for gap in gaps[:5]
        ]

        result = {
            "niche": niche,
            "competitors": [cp.to_dict() for cp in competitor_profiles],
            "gaps": gaps,
            "opportunities": opportunities,
        }

        # Persist
        state = await self._load()
        state["last_analysis"] = result
        await self._save(state)
        return result

    async def score_channel(
        self,
        channel: MarketingChannel,
        metrics: dict,
    ) -> float:
        """Score a marketing channel 0–100 based on weighted metrics."""
        roi = float(metrics.get("roi", 0))             # expected 0–10 scale
        volume = float(metrics.get("volume", 0))        # expected 0–10 scale
        effort = float(metrics.get("effort", 5))        # 0 = low effort, 10 = high effort
        time_to_results = float(metrics.get("time_to_results", 5))  # 0 = fast, 10 = slow

        # Invert effort and time (lower is better)
        effort_score = 10 - effort
        time_score = 10 - time_to_results

        raw = (
            roi * _CHANNEL_WEIGHTS["roi"]
            + volume * _CHANNEL_WEIGHTS["volume"]
            + effort_score * _CHANNEL_WEIGHTS["effort"]
            + time_score * _CHANNEL_WEIGHTS["time_to_results"]
        )

        # Normalize 0–10 scale → 0–100
        return round(min(raw * 10, 100.0), 1)

    async def identify_opportunities(
        self,
        niche: str,
        current_channels: list[str],
    ) -> list[MarketOpportunity]:
        """Return market opportunities sorted by priority score."""
        current_lower = {c.lower() for c in current_channels}
        opportunities: list[MarketOpportunity] = []

        channel_opportunity_map: list[tuple[MarketingChannel, str, str, str, float, list[str]]] = [
            (
                MarketingChannel.SEO,
                "Organic search traffic through long-tail keyword content",
                "medium",
                "3-6 months to rank, sustained free traffic",
                0.85,
                ["Keyword research for niche terms", "Publish 2 SEO articles/week", "Build internal links"],
            ),
            (
                MarketingChannel.EMAIL,
                "Build owned audience with email list",
                "low",
                "High ROI, direct access to audience",
                0.90,
                ["Create lead magnet", "Set up welcome sequence", "Send weekly newsletter"],
            ),
            (
                MarketingChannel.SOCIAL_ORGANIC,
                "Short-form video content for organic reach",
                "medium",
                "High reach potential on TikTok/Reels",
                0.75,
                ["Produce 3 short videos/week", "Trend-jack relevant content", "Engage with comments daily"],
            ),
            (
                MarketingChannel.CONTENT,
                "Authority content hub for niche",
                "high",
                "Long-term brand authority and SEO",
                0.70,
                ["Create pillar content pages", "Build topic clusters", "Guest post outreach"],
            ),
            (
                MarketingChannel.REFERRAL,
                "Referral program to turn customers into advocates",
                "low",
                "Viral coefficient boost at low CAC",
                0.80,
                ["Launch refer-a-friend program", "Offer dual-sided incentives", "Track referral conversions"],
            ),
            (
                MarketingChannel.INFLUENCER,
                f"Micro-influencer partnerships in {niche}",
                "medium",
                "Trusted reach in target audience",
                0.65,
                ["Identify 10 micro-influencers", "Outreach with product seeding", "Track affiliate links"],
            ),
            (
                MarketingChannel.AFFILIATE,
                "Affiliate program for passive distribution",
                "low",
                "Pay-per-result with no upfront cost",
                0.72,
                ["Set up affiliate dashboard", "Recruit 20 affiliates", "Create promotional materials"],
            ),
            (
                MarketingChannel.PAID_SOCIAL,
                "Retargeting campaigns for warm audiences",
                "low",
                "High conversion on warmed traffic",
                0.68,
                ["Set up pixel tracking", "Build lookalike audiences", "Test creative variants"],
            ),
            (
                MarketingChannel.PAID_SEARCH,
                "Bottom-funnel paid search for purchase intent",
                "low",
                "Immediate traffic with strong intent",
                0.60,
                ["Identify high-intent keywords", "Write compelling ad copy", "Optimize landing pages"],
            ),
        ]

        for channel, opp_desc, effort, impact, base_score, actions in channel_opportunity_map:
            # Boost score if channel not currently active
            priority = base_score + (0.1 if channel.value not in current_lower else -0.05)
            opportunities.append(
                MarketOpportunity(
                    opportunity=opp_desc,
                    channel=channel,
                    effort=effort,
                    estimated_impact=impact,
                    priority_score=round(min(priority, 1.0), 3),
                    action_items=actions,
                )
            )

        return sorted(opportunities, key=lambda o: o.priority_score, reverse=True)

    async def funnel_health_check(self, metrics: dict) -> list[dict]:
        """Check each funnel stage against benchmarks and return failing stages."""
        failing: list[dict] = []

        checks = [
            ("awareness_ctr", "Awareness (CTR)", metrics.get("awareness_ctr", 0)),
            ("consideration_engagement", "Consideration (Engagement)", metrics.get("consideration_engagement", 0)),
            ("conversion_rate", "Conversion (CVR)", metrics.get("conversion_rate", 0)),
        ]

        for key, label, actual in checks:
            benchmark = _FUNNEL_BENCHMARKS[key]
            if actual < benchmark:
                failing.append(
                    {
                        "stage": label,
                        "actual": round(actual, 4),
                        "benchmark": benchmark,
                        "gap": round(benchmark - actual, 4),
                        "recommendation": _FUNNEL_RECOMMENDATIONS[key],
                    }
                )

        return failing

    async def generate_growth_plan(
        self,
        objective: str,
        budget_usd: float,
        timeline_weeks: int,
    ) -> dict:
        """Return a structured growth plan for the given objective and budget."""
        obj_lower = objective.lower()

        # Match objective to template
        template: Optional[dict] = None
        for key, tmpl in _GROWTH_PLAN_TEMPLATES.items():
            if key in obj_lower:
                template = tmpl
                break
        if template is None:
            template = _GROWTH_PLAN_TEMPLATES["leads"]

        weekly_budget = round(budget_usd / max(timeline_weeks, 1), 2)

        # Build weekly actions based on budget tier
        if weekly_budget < 100:
            weekly_actions = [
                "Publish 2 organic content pieces",
                "Engage 30 mins/day on social",
                "Send 1 email to list",
                "Optimize 1 existing page for SEO",
            ]
        elif weekly_budget < 500:
            weekly_actions = [
                "Publish 3 content pieces",
                "Run $50 boosted post test",
                "A/B test 1 email subject line",
                "Reach out to 5 potential affiliates",
                "Monitor SEO rankings weekly",
            ]
        else:
            weekly_actions = [
                "Publish 5 content pieces across channels",
                "Run $200/week paid social campaign",
                "Send 2 segmented email campaigns",
                "Launch retargeting ads for site visitors",
                "Weekly performance review and optimization",
                "Influencer outreach to 10 creators",
            ]

        # Expected outcomes scaled by budget and timeline
        reach_estimate = int(weekly_budget * timeline_weeks * 50)
        conversion_estimate = int(reach_estimate * 0.02)

        plan = {
            "objective": objective,
            "budget_usd": budget_usd,
            "timeline_weeks": timeline_weeks,
            "weekly_budget": weekly_budget,
            "recommended_channels": template["recommended_channels"],
            "weekly_actions": weekly_actions,
            "kpis": template["kpis"],
            "focus": template["focus"],
            "expected_outcomes": {
                "estimated_reach": reach_estimate,
                "estimated_conversions": conversion_estimate,
                "timeline": f"{timeline_weeks} weeks",
            },
        }

        # Persist
        state = await self._load()
        state["last_growth_plan"] = plan
        await self._save(state)
        return plan

    def summary(self) -> dict:
        """Synchronous summary of current marketing intelligence state."""
        return {
            "active_channels": [],
            "top_opportunity": "Email list building (high ROI, owned channel)",
            "market_position": "Gathering data…",
            "_note": "Call analyze_market() and identify_opportunities() for live data",
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_intel_instance: Optional[MarketingIntelligence] = None


def get_marketing_intelligence() -> MarketingIntelligence:
    global _intel_instance
    if _intel_instance is None:
        _intel_instance = MarketingIntelligence()
    return _intel_instance
