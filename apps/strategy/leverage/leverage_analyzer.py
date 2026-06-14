from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LeveragePoint:
    point_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    system: str = ""  # content|traffic|conversion|retention|revenue|operations
    current_performance: float = 0.0  # 0-1
    potential_performance: float = 1.0  # 0-1
    leverage_multiplier: float = 1.0  # potential / max(current, 0.01)
    bottleneck: bool = False
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "point_id": self.point_id,
            "name": self.name,
            "description": self.description,
            "system": self.system,
            "current_performance": self.current_performance,
            "potential_performance": self.potential_performance,
            "leverage_multiplier": self.leverage_multiplier,
            "bottleneck": self.bottleneck,
            "actions": self.actions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LeveragePoint:
        return cls(
            point_id=d.get("point_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            description=d.get("description", ""),
            system=d.get("system", ""),
            current_performance=d.get("current_performance", 0.0),
            potential_performance=d.get("potential_performance", 1.0),
            leverage_multiplier=d.get("leverage_multiplier", 1.0),
            bottleneck=d.get("bottleneck", False),
            actions=d.get("actions", []),
        )


def _build_leverage_point(
    name: str,
    description: str,
    system: str,
    current: float,
    potential: float,
    bottleneck: bool,
    actions: list[str],
) -> LeveragePoint:
    multiplier = potential / max(current, 0.01)
    return LeveragePoint(
        name=name,
        description=description,
        system=system,
        current_performance=round(current, 4),
        potential_performance=round(potential, 4),
        leverage_multiplier=round(multiplier, 2),
        bottleneck=bottleneck,
        actions=actions,
    )


class LeverageAnalyzer:
    async def identify_leverage_points(self, metrics: dict) -> list[LeveragePoint]:
        traffic = metrics.get("traffic", 0.5)
        cvr = metrics.get("conversion_rate", 0.02)
        aov = metrics.get("avg_order_value", 50.0)
        retention = metrics.get("retention_rate", 0.5)
        referral = metrics.get("referral_rate", 0.05)

        points: list[LeveragePoint] = []

        # Conversion rate leverage
        if cvr < 0.02:
            points.append(_build_leverage_point(
                name="Conversion Rate Optimization",
                description=f"CVR at {cvr:.1%} — industry avg is 2-5%. Huge upside.",
                system="conversion",
                current=cvr / 0.05,  # normalize to 0-1 scale where 5% = 1.0
                potential=0.8,
                bottleneck=True,
                actions=[
                    "A/B test landing page headlines and CTAs",
                    "Add trust signals (reviews, guarantees, logos)",
                    "Simplify checkout — reduce steps to 1-2",
                    "Add exit-intent popup with incentive",
                ],
            ))
        elif cvr < 0.05:
            points.append(_build_leverage_point(
                name="Conversion Rate Improvement",
                description=f"CVR at {cvr:.1%} — solid but room to grow to 5%+.",
                system="conversion",
                current=cvr / 0.05,
                potential=0.9,
                bottleneck=False,
                actions=[
                    "Personalize messaging by traffic source",
                    "Add video testimonials above the fold",
                    "Optimize mobile experience",
                ],
            ))

        # Retention leverage
        if retention < 0.5:
            points.append(_build_leverage_point(
                name="Customer Retention",
                description=f"Retention at {retention:.1%} — losing half of customers. LTV is severely limited.",
                system="retention",
                current=retention,
                potential=0.75,
                bottleneck=True,
                actions=[
                    "Implement 30/60/90 day onboarding sequences",
                    "Add proactive customer success check-ins",
                    "Create loyalty/rewards program",
                    "Send monthly value-recap emails",
                ],
            ))
        elif retention < 0.7:
            points.append(_build_leverage_point(
                name="Retention Optimization",
                description=f"Retention at {retention:.1%} — improve to 70%+ to double LTV.",
                system="retention",
                current=retention,
                potential=0.85,
                bottleneck=False,
                actions=[
                    "Identify and address top cancellation reasons",
                    "Add product usage milestone celebrations",
                    "Create advanced user community",
                ],
            ))

        # AOV leverage
        if aov < 50.0:
            points.append(_build_leverage_point(
                name="Average Order Value",
                description=f"AOV at ${aov:.0f} — upsell/bundle opportunities untapped.",
                system="revenue",
                current=aov / 200.0,  # normalize, $200 = 1.0
                potential=0.6,
                bottleneck=False,
                actions=[
                    "Add order bump on checkout page",
                    "Create product bundles at 15-20% discount",
                    "Introduce premium/pro tier with more value",
                    "Add post-purchase upsell sequence",
                ],
            ))

        # Traffic leverage
        if traffic < 0.3:
            points.append(_build_leverage_point(
                name="Traffic Generation",
                description="Low traffic volume limits all downstream metrics.",
                system="traffic",
                current=traffic,
                potential=0.8,
                bottleneck=True,
                actions=[
                    "Launch SEO content calendar targeting buying-intent keywords",
                    "Set up paid acquisition on 1-2 channels",
                    "Start affiliate or partnership program",
                    "Pursue podcast/media appearances for earned traffic",
                ],
            ))

        # Referral leverage
        if referral < 0.05:
            points.append(_build_leverage_point(
                name="Referral / Word of Mouth",
                description=f"Referral rate at {referral:.1%} — viral coefficient below 1. No organic growth loop.",
                system="content",
                current=referral,
                potential=0.2,
                bottleneck=False,
                actions=[
                    "Launch referral program with dual-sided incentive",
                    "Create shareable results/outcomes for customers",
                    "Add social sharing to key moments in product",
                ],
            ))

        return sorted(points, key=lambda p: p.leverage_multiplier, reverse=True)

    async def bottleneck_analysis(self, metrics: dict) -> dict:
        points = await self.identify_leverage_points(metrics)
        bottlenecks = [p for p in points if p.bottleneck]

        if not bottlenecks:
            # Find highest leverage non-bottleneck
            primary = points[0] if points else None
            return {
                "primary_bottleneck": primary.name if primary else "None identified",
                "impact_score": primary.leverage_multiplier if primary else 1.0,
                "fix_priority": primary.actions[:3] if primary else [],
                "estimated_revenue_lift_pct": round(
                    (primary.leverage_multiplier - 1) * 100 if primary else 0, 1
                ),
            }

        primary = bottlenecks[0]
        lift_pct = (primary.leverage_multiplier - 1) * 100

        return {
            "primary_bottleneck": primary.name,
            "impact_score": primary.leverage_multiplier,
            "fix_priority": primary.actions[:4],
            "estimated_revenue_lift_pct": round(lift_pct, 1),
        }

    async def constraint_removal_plan(self, bottleneck: str) -> list[dict]:
        """Returns ordered action plan to remove the named bottleneck."""
        plans: dict[str, list[dict]] = {
            "conversion": [
                {"step": 1, "action": "Audit current funnel with heatmaps and session recordings", "expected_outcome": "Identify top 3 drop-off points", "timeframe_days": 3},
                {"step": 2, "action": "Fix top friction point (form length, load speed, or clarity)", "expected_outcome": "5-15% CVR improvement at that stage", "timeframe_days": 7},
                {"step": 3, "action": "A/B test new headline and primary CTA", "expected_outcome": "Identify winning variant with 95% confidence", "timeframe_days": 14},
                {"step": 4, "action": "Add social proof section (reviews, logos, stats)", "expected_outcome": "Build trust, reduce bounce rate by 10-20%", "timeframe_days": 5},
                {"step": 5, "action": "Implement exit-intent offer", "expected_outcome": "Recover 5-10% of abandoning visitors", "timeframe_days": 3},
            ],
            "retention": [
                {"step": 1, "action": "Survey churned customers to identify top 3 exit reasons", "expected_outcome": "Actionable retention insights", "timeframe_days": 7},
                {"step": 2, "action": "Fix #1 churn reason (product gap, pricing, or UX)", "expected_outcome": "Reduce churn by 20-30%", "timeframe_days": 21},
                {"step": 3, "action": "Launch 30-day onboarding email sequence", "expected_outcome": "Improve activation rate by 15%", "timeframe_days": 10},
                {"step": 4, "action": "Add in-app milestone celebrations and progress tracking", "expected_outcome": "Increase daily active usage by 10%", "timeframe_days": 14},
            ],
            "traffic": [
                {"step": 1, "action": "Keyword research — find 20 buying-intent keywords with low competition", "expected_outcome": "Content roadmap for organic growth", "timeframe_days": 5},
                {"step": 2, "action": "Publish 4 cornerstone SEO articles targeting priority keywords", "expected_outcome": "Begin ranking in 60-90 days", "timeframe_days": 30},
                {"step": 3, "action": "Launch paid acquisition test on top 1 channel ($500 budget)", "expected_outcome": "Establish CPL/CPA benchmark", "timeframe_days": 14},
                {"step": 4, "action": "Set up referral program for customer-led growth", "expected_outcome": "5-10% of new customers from referrals", "timeframe_days": 10},
            ],
            "revenue": [
                {"step": 1, "action": "Analyze purchase data to find natural upsell moments", "expected_outcome": "Identify 2-3 upsell opportunities", "timeframe_days": 3},
                {"step": 2, "action": "Create complementary product bundle at 15% discount", "expected_outcome": "Increase AOV by 25-40%", "timeframe_days": 7},
                {"step": 3, "action": "Add post-purchase 1-click upsell", "expected_outcome": "10-15% upsell take rate", "timeframe_days": 5},
                {"step": 4, "action": "Launch premium tier with expanded value", "expected_outcome": "20% of customers upgrade", "timeframe_days": 21},
            ],
        }

        bottleneck_key = bottleneck.lower().split()[0]
        plan = plans.get(bottleneck_key, plans.get("conversion", []))

        if not plan:
            plan = [
                {"step": 1, "action": f"Audit current state of '{bottleneck}'", "expected_outcome": "Baseline measurement established", "timeframe_days": 5},
                {"step": 2, "action": f"Identify root cause of underperformance in '{bottleneck}'", "expected_outcome": "Prioritized fix list", "timeframe_days": 7},
                {"step": 3, "action": "Implement top fix and measure impact", "expected_outcome": "Measurable improvement", "timeframe_days": 14},
            ]

        return plan

    async def simulate_improvement(
        self, metrics: dict, lever: str, improvement_pct: float
    ) -> dict:
        traffic = metrics.get("traffic", 1000)
        cvr = metrics.get("conversion_rate", 0.02)
        aov = metrics.get("avg_order_value", 50.0)
        retention = metrics.get("retention_rate", 0.5)

        # Current monthly revenue estimate
        monthly_customers = traffic * cvr
        base_monthly_revenue = monthly_customers * aov * (1 + retention)

        # Apply improvement to the specified lever
        new_metrics = dict(metrics)
        lever_lower = lever.lower()
        multiplier = 1.0 + (improvement_pct / 100.0)

        if "conversion" in lever_lower or "cvr" in lever_lower:
            new_metrics["conversion_rate"] = cvr * multiplier
        elif "traffic" in lever_lower or "visitor" in lever_lower:
            new_metrics["traffic"] = traffic * multiplier
        elif "order" in lever_lower or "aov" in lever_lower:
            new_metrics["avg_order_value"] = aov * multiplier
        elif "retention" in lever_lower:
            new_metrics["retention_rate"] = min(1.0, retention * multiplier)
        else:
            # Default: apply to CVR
            new_metrics["conversion_rate"] = cvr * multiplier

        new_cvr = new_metrics.get("conversion_rate", cvr)
        new_traffic = new_metrics.get("traffic", traffic)
        new_aov = new_metrics.get("avg_order_value", aov)
        new_retention = new_metrics.get("retention_rate", retention)

        new_monthly_customers = new_traffic * new_cvr
        new_monthly_revenue = new_monthly_customers * new_aov * (1 + new_retention)
        revenue_lift = new_monthly_revenue - base_monthly_revenue
        lift_pct = (revenue_lift / max(base_monthly_revenue, 1.0)) * 100

        return {
            "lever": lever,
            "improvement_pct": improvement_pct,
            "base_monthly_revenue_usd": round(base_monthly_revenue, 2),
            "projected_monthly_revenue_usd": round(new_monthly_revenue, 2),
            "revenue_lift_usd": round(revenue_lift, 2),
            "revenue_lift_pct": round(lift_pct, 2),
            "annualized_lift_usd": round(revenue_lift * 12, 2),
        }


_analyzer_instance: Optional[LeverageAnalyzer] = None


def get_leverage_analyzer() -> LeverageAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = LeverageAnalyzer()
    return _analyzer_instance
