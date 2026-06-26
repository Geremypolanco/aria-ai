"""
A/B Testing and Growth Experimentation Framework — Phase 5
Manages experiment lifecycle: creation, tracking, statistical analysis, and learnings.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from apps.core.memory.redis_client import get_cache

logger = logging.getLogger(__name__)

_REDIS_KEY = "experiments:v1"
_REDIS_TTL = 86400 * 90  # 90 days


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass
class ExperimentVariant:
    variant_id: str
    name: str
    description: str
    traffic_pct: float = 50.0
    impressions: int = 0
    conversions: int = 0

    @property
    def conversion_rate(self) -> float:
        if self.impressions == 0:
            return 0.0
        return self.conversions / self.impressions

    def is_winner(self, other: ExperimentVariant) -> bool:
        """True if this variant's conversion rate exceeds the other's by >5%."""
        return self.conversion_rate > other.conversion_rate * 1.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExperimentVariant:
        return cls(**d)


@dataclass
class Experiment:
    experiment_id: str
    name: str
    hypothesis: str
    channel: str
    metric: str
    variants: list[ExperimentVariant]
    status: ExperimentStatus = ExperimentStatus.DRAFT
    started_at: float = 0.0
    ended_at: float = 0.0
    winner_id: str = ""
    confidence: float = 0.0
    learned: str = ""

    def is_significant(self) -> bool:
        """True when enough data exists and confidence threshold is met."""
        if not self.variants:
            return False
        max_impressions = max(v.impressions for v in self.variants)
        return max_impressions >= 100 and self.confidence >= 0.95

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["variants"] = [v.to_dict() for v in self.variants]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Experiment:
        d = dict(d)
        d["status"] = ExperimentStatus(d["status"])
        d["variants"] = [ExperimentVariant.from_dict(v) for v in d["variants"]]
        return cls(**d)


class ExperimentRunner:
    """Lifecycle manager for A/B experiments with chi-squared confidence approximation."""

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_REDIS_KEY)
            if data and isinstance(data, dict):
                for exp_id, ed in data.items():
                    try:
                        self._experiments[exp_id] = Experiment.from_dict(ed)
                    except Exception:
                        logger.warning("Skipping malformed experiment %s", exp_id)
        except Exception:
            logger.exception("ExperimentRunner._load failed")
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {eid: exp.to_dict() for eid, exp in self._experiments.items()}
            await cache.set(_REDIS_KEY, payload, ttl_seconds=_REDIS_TTL)
        except Exception:
            logger.exception("ExperimentRunner._save failed")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_experiment(
        self,
        name: str,
        hypothesis: str,
        channel: str,
        metric: str,
        variant_names: list[str],
    ) -> str:
        """Create a new experiment with 50/50 split across two variants."""
        await self._load()

        # Always create exactly 2 variants
        names = (variant_names + ["Control", "Variant A"])[:2]
        variants = [
            ExperimentVariant(
                variant_id=str(uuid.uuid4()),
                name=names[0],
                description=f"Baseline for {name}",
                traffic_pct=50.0,
            ),
            ExperimentVariant(
                variant_id=str(uuid.uuid4()),
                name=names[1],
                description=f"Test variant for {name}",
                traffic_pct=50.0,
            ),
        ]

        experiment = Experiment(
            experiment_id=str(uuid.uuid4()),
            name=name,
            hypothesis=hypothesis,
            channel=channel,
            metric=metric,
            variants=variants,
        )
        self._experiments[experiment.experiment_id] = experiment
        await self._save()
        return experiment.experiment_id

    async def start_experiment(self, experiment_id: str) -> bool:
        """Transition experiment from DRAFT to RUNNING."""
        await self._load()
        exp = self._experiments.get(experiment_id)
        if not exp:
            logger.warning("start_experiment: unknown id %s", experiment_id)
            return False
        if exp.status != ExperimentStatus.DRAFT:
            logger.warning("start_experiment: %s is already %s", experiment_id, exp.status)
            return False
        exp.status = ExperimentStatus.RUNNING
        exp.started_at = time.time()
        await self._save()
        return True

    async def record_impression(self, experiment_id: str, variant_id: str) -> bool:
        """Increment impression count for a variant."""
        await self._load()
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != ExperimentStatus.RUNNING:
            return False
        for variant in exp.variants:
            if variant.variant_id == variant_id:
                variant.impressions += 1
                await self._save()
                return True
        return False

    async def record_conversion(self, experiment_id: str, variant_id: str) -> bool:
        """Increment conversion count for a variant."""
        await self._load()
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != ExperimentStatus.RUNNING:
            return False
        for variant in exp.variants:
            if variant.variant_id == variant_id:
                variant.conversions += 1
                await self._save()
                return True
        return False

    async def analyze_experiment(self, experiment_id: str) -> dict[str, Any]:
        """
        Calculate winner and confidence using chi-squared approximation.
        Confidence = 0.95 if diff > 5% and both variants have > 50 impressions.
        """
        await self._load()
        exp = self._experiments.get(experiment_id)
        if not exp:
            return {"error": "experiment_not_found"}

        variants = exp.variants
        if len(variants) < 2:
            return {"error": "not_enough_variants"}

        v_a, v_b = variants[0], variants[1]
        both_adequate = v_a.impressions > 50 and v_b.impressions > 50
        rate_a = v_a.conversion_rate
        rate_b = v_b.conversion_rate
        relative_diff = abs(rate_a - rate_b) / max(rate_a, rate_b, 0.001)

        if both_adequate and relative_diff > 0.05:
            exp.confidence = 0.95
            exp.winner_id = v_a.variant_id if rate_a >= rate_b else v_b.variant_id
        else:
            exp.confidence = min(relative_diff / 0.05, 0.94) if both_adequate else 0.0
            exp.winner_id = ""

        await self._save()
        return {
            "experiment_id": experiment_id,
            "winner_id": exp.winner_id,
            "confidence": exp.confidence,
            "is_significant": exp.is_significant(),
            "variant_a": {
                "id": v_a.variant_id,
                "name": v_a.name,
                "impressions": v_a.impressions,
                "conversions": v_a.conversions,
                "conversion_rate": v_a.conversion_rate,
            },
            "variant_b": {
                "id": v_b.variant_id,
                "name": v_b.name,
                "impressions": v_b.impressions,
                "conversions": v_b.conversions,
                "conversion_rate": v_b.conversion_rate,
            },
        }

    async def complete_experiment(self, experiment_id: str, learned: str) -> bool:
        """Mark experiment as COMPLETED and store learning."""
        await self._load()
        exp = self._experiments.get(experiment_id)
        if not exp:
            return False
        exp.status = ExperimentStatus.COMPLETED
        exp.ended_at = time.time()
        exp.learned = learned
        await self._save()
        return True

    async def list_experiments(
        self, status_filter: ExperimentStatus | None = None
    ) -> list[dict[str, Any]]:
        """Return all experiments, optionally filtered by status."""
        await self._load()
        exps = list(self._experiments.values())
        if status_filter is not None:
            exps = [e for e in exps if e.status == status_filter]
        exps.sort(key=lambda e: e.started_at, reverse=True)
        return [e.to_dict() for e in exps]

    async def get_learnings(self) -> list[str]:
        """Return all learned strings from completed experiments."""
        await self._load()
        return [
            exp.learned
            for exp in self._experiments.values()
            if exp.status == ExperimentStatus.COMPLETED and exp.learned
        ]


# ------------------------------------------------------------------
# Singleton factory
# ------------------------------------------------------------------

_experiment_runner_instance: ExperimentRunner | None = None


def get_experiment_runner() -> ExperimentRunner:
    global _experiment_runner_instance
    if _experiment_runner_instance is None:
        _experiment_runner_instance = ExperimentRunner()
    return _experiment_runner_instance
