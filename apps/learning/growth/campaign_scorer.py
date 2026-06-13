from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CampaignMetrics:
    campaign_id: str
    name: str
    channel: str
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    revenue_usd: float = 0.0
    cost_usd: float = 0.0

    @property
    def ctr(self) -> float:
        return self.clicks / max(self.impressions, 1)

    @property
    def conversion_rate(self) -> float:
        return self.conversions / max(self.clicks, 1)

    @property
    def roas(self) -> float:
        return self.revenue_usd / max(self.cost_usd, 0.01)

    @property
    def cpa(self) -> float:
        return self.cost_usd / max(self.conversions, 1)

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "channel": self.channel,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "conversions": self.conversions,
            "revenue_usd": self.revenue_usd,
            "cost_usd": self.cost_usd,
            "ctr": self.ctr,
            "conversion_rate": self.conversion_rate,
            "roas": self.roas,
            "cpa": self.cpa,
        }


@dataclass
class CampaignScore:
    campaign_id: str
    name: str
    composite_score: float
    roas_score: float
    ctr_score: float
    conversion_score: float
    efficiency_score: float
    grade: str

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "composite_score": self.composite_score,
            "roas_score": self.roas_score,
            "ctr_score": self.ctr_score,
            "conversion_score": self.conversion_score,
            "efficiency_score": self.efficiency_score,
            "grade": self.grade,
        }


def _grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


class CampaignScorer:
    def score_campaign(self, metrics: CampaignMetrics) -> CampaignScore:
        # 5x ROAS = 100 points
        roas_score = min(100.0, metrics.roas * 20)
        # 2% CTR = 100 points
        ctr_score = min(100.0, metrics.ctr * 5000)
        # 3% CVR = 100 points
        conversion_score = min(100.0, metrics.conversion_rate * 3333)
        # $0 CPA = 100, $50+ = 0
        efficiency_score = min(100.0, max(0.0, 100.0 - (metrics.cpa / 50 * 100)))

        composite = (
            roas_score * 0.4
            + ctr_score * 0.2
            + conversion_score * 0.3
            + efficiency_score * 0.1
        )

        return CampaignScore(
            campaign_id=metrics.campaign_id,
            name=metrics.name,
            composite_score=round(composite, 2),
            roas_score=round(roas_score, 2),
            ctr_score=round(ctr_score, 2),
            conversion_score=round(conversion_score, 2),
            efficiency_score=round(efficiency_score, 2),
            grade=_grade(composite),
        )

    def rank_campaigns(self, campaigns: list[CampaignMetrics]) -> list[CampaignScore]:
        scores = [self.score_campaign(m) for m in campaigns]
        return sorted(scores, key=lambda s: s.composite_score, reverse=True)

    def identify_winners(self, campaigns: list[CampaignMetrics], threshold: float = 70.0) -> list[CampaignScore]:
        return [s for s in self.rank_campaigns(campaigns) if s.composite_score >= threshold]

    def identify_losers(self, campaigns: list[CampaignMetrics], threshold: float = 40.0) -> list[CampaignScore]:
        return [s for s in self.rank_campaigns(campaigns) if s.composite_score < threshold]

    async def benchmark_report(self, campaigns: list[CampaignMetrics]) -> dict:
        if not campaigns:
            return {
                "avg_score": 0.0,
                "winners": [],
                "losers": [],
                "best_channel_by_score": None,
                "total_revenue": 0.0,
                "total_spend": 0.0,
                "overall_roas": 0.0,
            }

        scores = self.rank_campaigns(campaigns)
        avg_score = sum(s.composite_score for s in scores) / len(scores)

        winners = [s.to_dict() for s in scores if s.composite_score >= 70.0]
        losers = [s.to_dict() for s in scores if s.composite_score < 40.0]

        # best channel by average score
        channel_scores: dict[str, list[float]] = {}
        for m, s in zip(campaigns, [self.score_campaign(m) for m in campaigns]):
            channel_scores.setdefault(m.channel, []).append(s.composite_score)
        best_channel = max(
            channel_scores,
            key=lambda c: sum(channel_scores[c]) / max(len(channel_scores[c]), 1),
        ) if channel_scores else None

        total_revenue = sum(m.revenue_usd for m in campaigns)
        total_spend = sum(m.cost_usd for m in campaigns)
        overall_roas = total_revenue / max(total_spend, 0.01)

        return {
            "avg_score": round(avg_score, 2),
            "winners": winners,
            "losers": losers,
            "best_channel_by_score": best_channel,
            "total_revenue": round(total_revenue, 2),
            "total_spend": round(total_spend, 2),
            "overall_roas": round(overall_roas, 2),
        }


_scorer_instance: CampaignScorer | None = None


def get_campaign_scorer() -> CampaignScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = CampaignScorer()
    return _scorer_instance
