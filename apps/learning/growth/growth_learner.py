from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from apps.core.memory.redis_client import get_cache

_LEARNER_KEY = "growth_learner:v1"
_LEARNER_TTL = 86400 * 180
_MAX_EXPERIMENTS = 500


class StrategyOutcome(StrEnum):
    WIN = "win"
    LOSS = "loss"
    PARTIAL = "partial"
    NEUTRAL = "neutral"


@dataclass
class GrowthExperiment:
    exp_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy: str = ""
    channel: str = ""
    hypothesis: str = ""
    variant: str = ""
    result: StrategyOutcome = StrategyOutcome.NEUTRAL
    roi: float = 0.0
    reach: int = 0
    conversions: int = 0
    cost_usd: float = 0.0
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    learnings: str = ""

    def to_dict(self) -> dict:
        return {
            "exp_id": self.exp_id,
            "strategy": self.strategy,
            "channel": self.channel,
            "hypothesis": self.hypothesis,
            "variant": self.variant,
            "result": self.result.value,
            "roi": self.roi,
            "reach": self.reach,
            "conversions": self.conversions,
            "cost_usd": self.cost_usd,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "learnings": self.learnings,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GrowthExperiment:
        return cls(
            exp_id=d["exp_id"],
            strategy=d["strategy"],
            channel=d["channel"],
            hypothesis=d.get("hypothesis", ""),
            variant=d.get("variant", ""),
            result=StrategyOutcome(d.get("result", StrategyOutcome.NEUTRAL.value)),
            roi=d.get("roi", 0.0),
            reach=d.get("reach", 0),
            conversions=d.get("conversions", 0),
            cost_usd=d.get("cost_usd", 0.0),
            started_at=d.get("started_at", time.time()),
            ended_at=d.get("ended_at", 0.0),
            learnings=d.get("learnings", ""),
        )


@dataclass
class StrategyKnowledge:
    strategy: str
    channel: str
    win_count: int = 0
    loss_count: int = 0
    total_roi: float = 0.0
    total_reach: int = 0
    confidence: float = 0.5

    def update(self, outcome: StrategyOutcome, roi: float) -> None:
        if outcome == StrategyOutcome.WIN:
            self.win_count += 1
            self.confidence = min(0.99, self.confidence + 0.1)
        elif outcome == StrategyOutcome.LOSS:
            self.loss_count += 1
            self.confidence = max(0.1, self.confidence - 0.15)
        self.total_roi += roi

    @property
    def avg_roi(self) -> float:
        total = self.win_count + self.loss_count
        return self.total_roi / total if total > 0 else 0.0

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "channel": self.channel,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "total_roi": self.total_roi,
            "total_reach": self.total_reach,
            "confidence": self.confidence,
            "avg_roi": self.avg_roi,
            "win_rate": self.win_rate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StrategyKnowledge:
        return cls(
            strategy=d["strategy"],
            channel=d["channel"],
            win_count=d.get("win_count", 0),
            loss_count=d.get("loss_count", 0),
            total_roi=d.get("total_roi", 0.0),
            total_reach=d.get("total_reach", 0),
            confidence=d.get("confidence", 0.5),
        )


class GrowthLearner:
    def __init__(self) -> None:
        self._data: dict = {"experiments": [], "knowledge": {}}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> dict:
        if self._loaded:
            return self._data
        try:
            cache = get_cache()
            data = await cache.get(_LEARNER_KEY)
            if data and isinstance(data, dict):
                self._data = data
        except Exception:
            pass
        self._loaded = True
        return self._data

    async def _save(self, data: dict) -> None:
        self._data = data
        try:
            cache = get_cache()
            await cache.set(_LEARNER_KEY, data, ttl_seconds=_LEARNER_TTL)
        except Exception:
            pass

    def _knowledge_key(self, strategy: str, channel: str) -> str:
        return f"{strategy}::{channel}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record_experiment(
        self,
        strategy: str,
        channel: str,
        hypothesis: str,
        variant: str,
        result: StrategyOutcome,
        roi: float,
        reach: int,
        conversions: int,
        cost: float,
        learnings: str,
    ) -> GrowthExperiment:
        data = await self._load()
        experiments: list[dict] = data.get("experiments", [])
        knowledge: dict[str, dict] = data.get("knowledge", {})

        exp = GrowthExperiment(
            strategy=strategy,
            channel=channel,
            hypothesis=hypothesis,
            variant=variant,
            result=result,
            roi=roi,
            reach=reach,
            conversions=conversions,
            cost_usd=cost,
            ended_at=time.time(),
            learnings=learnings,
        )
        experiments.append(exp.to_dict())

        # update knowledge base
        key = self._knowledge_key(strategy, channel)
        if key in knowledge:
            sk = StrategyKnowledge.from_dict(knowledge[key])
        else:
            sk = StrategyKnowledge(strategy=strategy, channel=channel)
        sk.update(result, roi)
        sk.total_reach += reach
        knowledge[key] = sk.to_dict()

        data["experiments"] = experiments[-_MAX_EXPERIMENTS:]
        data["knowledge"] = knowledge
        await self._save(data)
        return exp

    async def get_knowledge(
        self,
        strategy: str | None = None,
        channel: str | None = None,
    ) -> list[StrategyKnowledge]:
        data = await self._load()
        knowledge = data.get("knowledge", {})
        result = [StrategyKnowledge.from_dict(v) for v in knowledge.values()]
        if strategy:
            result = [k for k in result if k.strategy == strategy]
        if channel:
            result = [k for k in result if k.channel == channel]
        return result

    async def best_strategies(self, top_k: int = 5) -> list[StrategyKnowledge]:
        knowledge = await self.get_knowledge()
        scored = sorted(knowledge, key=lambda k: k.confidence * k.avg_roi, reverse=True)
        return scored[:top_k]

    async def failing_strategies(self, min_attempts: int = 3) -> list[StrategyKnowledge]:
        knowledge = await self.get_knowledge()
        return [
            k
            for k in knowledge
            if (k.win_count + k.loss_count) >= min_attempts and k.win_rate < 0.2
        ]

    async def recommend_next_experiment(
        self,
        available_channels: list[str],
        available_budget: float,
    ) -> dict:
        knowledge = await self.get_knowledge()
        # find best knowledge for available channels
        channel_knowledge = [k for k in knowledge if k.channel in available_channels]
        if channel_knowledge:
            best = max(channel_knowledge, key=lambda k: k.confidence * k.avg_roi)
            return {
                "strategy": best.strategy,
                "channel": best.channel,
                "hypothesis": f"Continue scaling '{best.strategy}' on '{best.channel}' — win rate {best.win_rate:.0%}",
                "recommended_budget": min(available_budget, available_budget * best.win_rate),
                "confidence": best.confidence,
            }
        # no prior knowledge: suggest first available channel
        channel = available_channels[0] if available_channels else "organic"
        return {
            "strategy": "content_marketing",
            "channel": channel,
            "hypothesis": "Test content marketing on new channel to establish baseline performance",
            "recommended_budget": available_budget * 0.1,
            "confidence": 0.3,
        }

    async def evolve_strategy(self, strategy: str) -> str:
        data = await self._load()
        experiments = [GrowthExperiment.from_dict(e) for e in data.get("experiments", [])]
        strategy_exps = [e for e in experiments if e.strategy == strategy]
        winning = [e for e in strategy_exps if e.result == StrategyOutcome.WIN]

        if not winning:
            return f"No winning experiments found for '{strategy}'. Try new channels or variants."

        top_by_roi = sorted(winning, key=lambda e: e.roi, reverse=True)[:3]
        common_channels = list({e.channel for e in top_by_roi})
        top_learnings = [e.learnings for e in top_by_roi if e.learnings]

        evolved = (
            f"Evolved '{strategy}': Focus on channels {common_channels}. "
            f"Top learnings: {'; '.join(top_learnings[:2]) if top_learnings else 'N/A'}. "
            f"Best ROI achieved: {top_by_roi[0].roi:.2f}x on '{top_by_roi[0].channel}'."
        )
        return evolved

    async def learning_report(self) -> dict:
        data = await self._load()
        experiments = [GrowthExperiment.from_dict(e) for e in data.get("experiments", [])]
        await self.get_knowledge()

        wins = [e for e in experiments if e.result == StrategyOutcome.WIN]
        overall_win_rate = len(wins) / max(len(experiments), 1)
        key_learnings = [e.learnings for e in wins if e.learnings][:10]

        top = await self.best_strategies(top_k=5)
        worst = await self.failing_strategies()

        return {
            "total_experiments": len(experiments),
            "win_rate_overall": round(overall_win_rate, 4),
            "top_strategies": [k.to_dict() for k in top],
            "worst_strategies": [k.to_dict() for k in worst],
            "key_learnings": key_learnings,
        }


_learner_instance: GrowthLearner | None = None


def get_growth_learner() -> GrowthLearner:
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = GrowthLearner()
    return _learner_instance
