"""
growth_engine.py — Revenue & Growth engine for ARIA AI.

Integrates GrowthBook and PostHog for:
  - Professional A/B testing of marketing strategies (GrowthBook)
  - Product analytics with funnels and conversions (PostHog)
  - Continuous experimentation to optimize revenue
  - Real-time business event tracking
  - Cohort analysis and customer retention

ARIA needs to learn what works. Not just execute.
This module closes the loop: execute → measure → learn → optimize.

Reference:
  - GrowthBook: https://github.com/growthbook/growthbook-python
  - PostHog: https://github.com/posthog/posthog-python
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.growth_engine")

# ── GrowthBook import with fallback ──────────────────────────────────────────
try:
    from growthbook import Experiment, GrowthBook, Result  # noqa: F401

    GROWTHBOOK_AVAILABLE = True
    logger.info("[GrowthBook] Library loaded successfully.")
except ImportError:
    GROWTHBOOK_AVAILABLE = False
    logger.warning(
        "[GrowthBook] growthbook not installed. "
        "Using native A/B testing. "
        "Install with: pip install growthbook"
    )
    GrowthBook = None  # type: ignore[assignment,misc]
    Experiment = None  # type: ignore[assignment,misc]

# ── PostHog import with fallback ─────────────────────────────────────────────
try:
    import posthog

    POSTHOG_AVAILABLE = True
    logger.info("[PostHog] Library loaded successfully.")
except ImportError:
    POSTHOG_AVAILABLE = False
    logger.warning(
        "[PostHog] posthog not installed. "
        "Using native logging. "
        "Install with: pip install posthog"
    )
    posthog = None  # type: ignore[assignment]


# ── GrowthBook Engine ─────────────────────────────────────────────────────────


class AriaGrowthBookEngine:
    """
    A/B Testing engine for ARIA AI with GrowthBook.

    Lets ARIA experiment with different strategies and learn
    which ones generate more revenue and conversions.

    Typical ARIA experiments:
    - Ebook pricing ($7 vs $17 vs $27)
    - Content publishing schedule (morning vs afternoon vs evening)
    - CTA type in emails (urgency vs benefit vs social proof)
    - Distribution channel (TikTok vs Instagram vs Twitter)
    - Sales email length (short vs long)

    Usage:
        engine = AriaGrowthBookEngine()

        # Create pricing experiment
        variant = engine.get_variant(
            experiment_id="ebook_price_test",
            user_id="campaign_001",
            variants=["$7", "$17", "$27"],
        )
        print(f"Price to use: {variant}")

        # Record conversion
        engine.track_conversion(
            experiment_id="ebook_price_test",
            user_id="campaign_001",
            value=17.0,
        )
    """

    def __init__(
        self,
        api_host: str = "http://localhost:3100",
        client_key: str = "",
    ) -> None:
        self._api_host = api_host
        self._client_key = client_key
        self._experiments: dict[str, dict] = {}
        self._results: list[dict] = []

    def get_variant(
        self,
        experiment_id: str,
        user_id: str,
        variants: list[Any],
        weights: list[float] | None = None,
    ) -> Any:
        """
        Gets the variant assigned to a user in an experiment.

        Uses deterministic hashing for consistent assignment.
        The same user_id always receives the same variant.

        Args:
            experiment_id: Unique experiment ID
            user_id: User or campaign ID
            variants: List of possible variants
            weights: Distribution weights (default: equal distribution)

        Returns:
            The variant assigned to the user
        """
        if not variants:
            return None

        if GROWTHBOOK_AVAILABLE and GrowthBook is not None:
            try:
                gb = GrowthBook(
                    attributes={"id": user_id},
                    api_host=self._api_host,
                    client_key=self._client_key,
                )
                exp = Experiment(
                    key=experiment_id,
                    variations=variants,
                    weights=weights,
                )
                result = gb.run(exp)
                variant = result.value

                # Record assignment
                self._record_assignment(experiment_id, user_id, variant, result.in_experiment)
                return variant

            except Exception as exc:
                logger.warning("[GrowthBook] Error in experiment %s: %s", experiment_id, exc)

        # Fallback: deterministic hashing
        return self._hash_variant(experiment_id, user_id, variants, weights)

    def _hash_variant(
        self,
        experiment_id: str,
        user_id: str,
        variants: list[Any],
        weights: list[float] | None = None,
    ) -> Any:
        """Deterministic hash-based assignment when GrowthBook is not available."""
        hash_input = f"{experiment_id}_{user_id}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)

        if weights:
            # Weighted distribution
            cumulative = 0.0
            normalized_hash = (hash_value % 10000) / 10000.0
            for variant, weight in zip(variants, weights, strict=False):
                cumulative += weight
                if normalized_hash <= cumulative:
                    return variant
            return variants[-1]
        # Uniform distribution
        return variants[hash_value % len(variants)]

    def _record_assignment(
        self,
        experiment_id: str,
        user_id: str,
        variant: Any,
        in_experiment: bool,
    ) -> None:
        """Records the variant assignment."""
        if experiment_id not in self._experiments:
            self._experiments[experiment_id] = {
                "id": experiment_id,
                "assignments": {},
                "conversions": [],
                "created_at": datetime.now(UTC).isoformat(),
            }
        self._experiments[experiment_id]["assignments"][user_id] = {
            "variant": variant,
            "in_experiment": in_experiment,
            "assigned_at": datetime.now(UTC).isoformat(),
        }

    def track_conversion(
        self,
        experiment_id: str,
        user_id: str,
        value: float = 1.0,
        metric: str = "revenue",
    ) -> None:
        """
        Records a conversion for an experiment.

        Args:
            experiment_id: Experiment ID
            user_id: User ID
            value: Conversion value (e.g. $27.0 for a sale)
            metric: Metric to track ('revenue', 'conversion', 'clicks')
        """
        conversion = {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "value": value,
            "metric": metric,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._results.append(conversion)

        if experiment_id in self._experiments:
            self._experiments[experiment_id]["conversions"].append(conversion)

        logger.info(
            "[GrowthBook] Conversion recorded: exp=%s user=%s value=%.2f",
            experiment_id,
            user_id,
            value,
        )

    def get_experiment_results(self, experiment_id: str) -> dict[str, Any]:
        """
        Gets the statistical results of an experiment.

        Returns:
            Results analysis by variant with key metrics
        """
        if experiment_id not in self._experiments:
            return {"error": f"Experiment '{experiment_id}' not found"}

        exp = self._experiments[experiment_id]
        assignments = exp.get("assignments", {})
        conversions = exp.get("conversions", [])

        # Group by variant
        variant_stats: dict[str, dict] = {}
        for user_id, assignment in assignments.items():
            variant = str(assignment["variant"])
            if variant not in variant_stats:
                variant_stats[variant] = {"users": 0, "conversions": 0, "total_value": 0.0}
            variant_stats[variant]["users"] += 1

        for conv in conversions:
            user_id = conv["user_id"]
            if user_id in assignments:
                variant = str(assignments[user_id]["variant"])
                if variant in variant_stats:
                    variant_stats[variant]["conversions"] += 1
                    variant_stats[variant]["total_value"] += conv.get("value", 0.0)

        # Calculate metrics
        for variant, stats in variant_stats.items():
            users = stats["users"]
            stats["conversion_rate"] = stats["conversions"] / users if users > 0 else 0.0
            stats["avg_value"] = stats["total_value"] / max(stats["conversions"], 1)

        return {
            "experiment_id": experiment_id,
            "total_users": len(assignments),
            "total_conversions": len(conversions),
            "variants": variant_stats,
            "winner": (
                max(variant_stats.items(), key=lambda x: x[1]["total_value"])[0]
                if variant_stats
                else None
            ),
        }

    def get_all_experiments(self) -> list[dict[str, Any]]:
        """Lists all active experiments."""
        return [
            {
                "id": exp_id,
                "users": len(exp.get("assignments", {})),
                "conversions": len(exp.get("conversions", [])),
                "created_at": exp.get("created_at", ""),
            }
            for exp_id, exp in self._experiments.items()
        ]


# ── PostHog Analytics Engine ──────────────────────────────────────────────────


class AriaPostHogEngine:
    """
    Product Analytics engine for ARIA AI with PostHog.

    Lets ARIA measure:
    - Complete conversion funnels (content → lead → sale)
    - Real-time business events
    - Customer cohorts and retention
    - Feature flags for gradual rollouts
    - Session recordings for behavior analysis

    Nearly mandatory for a Revenue Engine.

    Usage:
        engine = AriaPostHogEngine()

        # Track business event
        engine.capture_event(
            distinct_id="campaign_001",
            event="sale_completed",
            properties={"amount": 27.0, "product": "Ebook Fitness", "channel": "tiktok"}
        )

        # Identify user/campaign
        engine.identify(
            distinct_id="campaign_001",
            properties={"niche": "fitness", "total_revenue": 270.0}
        )
    """

    def __init__(
        self,
        api_key: str = "",
        host: str = "https://app.posthog.com",
    ) -> None:
        self._api_key = api_key
        self._host = host
        self._initialized = False
        self._event_buffer: list[dict] = []

        if POSTHOG_AVAILABLE and api_key and posthog is not None:
            try:
                posthog.project_api_key = api_key
                posthog.host = host
                posthog.debug = False
                self._initialized = True
                logger.info("[PostHog] Initialized successfully (host=%s)", host)
            except Exception as exc:
                logger.warning("[PostHog] Initialization error: %s", exc)

    def capture_event(
        self,
        distinct_id: str,
        event: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Captures a business event in PostHog.

        Args:
            distinct_id: Unique ID of the user, campaign, or agent
            event: Event name (e.g. 'sale_completed', 'content_published')
            properties: Event properties (amount, channel, niche, etc.)
        """
        props = properties or {}
        props["timestamp"] = datetime.now(UTC).isoformat()
        props["source"] = "aria_ai"

        event_data = {
            "distinct_id": distinct_id,
            "event": event,
            "properties": props,
            "timestamp": props["timestamp"],
        }

        if self._initialized and posthog is not None:
            try:
                posthog.capture(
                    distinct_id=distinct_id,
                    event=event,
                    properties=props,
                )
                logger.debug("[PostHog] Event captured: %s | %s", event, distinct_id)
            except Exception as exc:
                logger.warning("[PostHog] Error capturing event: %s", exc)
                self._event_buffer.append(event_data)
        else:
            # Local buffer when PostHog is not available
            self._event_buffer.append(event_data)
            logger.debug("[PostHog] Event buffered: %s | %s", event, distinct_id)

    def identify(
        self,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Identifies a user/campaign with its properties.

        Args:
            distinct_id: Unique ID
            properties: Profile properties (niche, total_revenue, etc.)
        """
        if self._initialized and posthog is not None:
            try:
                posthog.identify(
                    distinct_id=distinct_id,
                    properties=properties or {},
                )
            except Exception as exc:
                logger.warning("[PostHog] Error in identify: %s", exc)

    def capture_funnel_step(
        self,
        funnel_id: str,
        step: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Captures a step in a conversion funnel.

        Typical ARIA funnels:
        - content_funnel: content_created → lead_generated → email_sent → sale_completed
        - product_funnel: idea_generated → product_created → published → first_sale
        - campaign_funnel: campaign_started → content_published → engagement → conversion

        Args:
            funnel_id: Funnel ID (e.g. 'content_to_sale')
            step: Current step (e.g. 'lead_generated')
            distinct_id: User/campaign ID
            properties: Additional step data
        """
        props = properties or {}
        props["funnel_id"] = funnel_id
        props["funnel_step"] = step

        self.capture_event(
            distinct_id=distinct_id,
            event=f"funnel_{funnel_id}_{step}",
            properties=props,
        )

    def capture_revenue_event(
        self,
        amount_usd: float,
        channel: str,
        product: str,
        campaign_id: str = "",
        agent: str = "",
    ) -> None:
        """
        Captures a revenue event for Revenue Attribution analysis.

        Args:
            amount_usd: Amount in USD
            channel: Source channel (tiktok, email, organic, etc.)
            product: Product sold
            campaign_id: ID of the campaign that generated the sale
            agent: ARIA agent that executed the action
        """
        distinct_id = campaign_id or f"revenue_{channel}_{datetime.now().strftime('%Y%m%d')}"

        self.capture_event(
            distinct_id=distinct_id,
            event="revenue_generated",
            properties={
                "amount_usd": amount_usd,
                "channel": channel,
                "product": product,
                "campaign_id": campaign_id,
                "agent": agent,
                "currency": "USD",
            },
        )

    def capture_agent_action(
        self,
        agent_name: str,
        action: str,
        success: bool,
        duration_ms: int = 0,
        roi: float = 0.0,
    ) -> None:
        """
        Captures an agent action for performance analysis.

        Args:
            agent_name: Agent name (orchestrator, cfo, marketing, etc.)
            action: Action executed
            success: Whether it succeeded
            duration_ms: Duration in milliseconds
            roi: ROI generated
        """
        self.capture_event(
            distinct_id=f"agent_{agent_name}",
            event="agent_action",
            properties={
                "agent": agent_name,
                "action": action,
                "success": success,
                "duration_ms": duration_ms,
                "roi_usd": roi,
            },
        )

    def get_buffered_events(self) -> list[dict[str, Any]]:
        """Returns the buffered events (when PostHog is not available)."""
        return self._event_buffer.copy()

    def flush_buffer(self) -> int:
        """Clears the event buffer and returns the number of events."""
        count = len(self._event_buffer)
        self._event_buffer.clear()
        return count

    def get_status(self) -> dict[str, Any]:
        """Status of the PostHog engine."""
        return {
            "posthog_available": POSTHOG_AVAILABLE,
            "initialized": self._initialized,
            "api_key_configured": bool(self._api_key),
            "buffered_events": len(self._event_buffer),
            "host": self._host,
        }


# ── Unified Growth Engine ─────────────────────────────────────────────────────


class AriaGrowthEngine:
    """
    Unified Revenue & Growth engine for ARIA AI.

    Combines GrowthBook (A/B testing) and PostHog (analytics) to
    close the continuous learning loop:

        Execute → Measure → Learn → Optimize → Execute

    Integrates with:
    - ExecutionPipeline (measure each execution's results)
    - MarketingAgent (optimize campaigns)
    - CFO Agent (attribute revenue)
    - EvolutionAgent (learn and improve)
    """

    def __init__(
        self,
        posthog_api_key: str = "",
        posthog_host: str = "https://app.posthog.com",
        growthbook_api_host: str = "http://localhost:3100",
        growthbook_client_key: str = "",
    ) -> None:
        self.ab_testing = AriaGrowthBookEngine(
            api_host=growthbook_api_host,
            client_key=growthbook_client_key,
        )
        self.analytics = AriaPostHogEngine(
            api_key=posthog_api_key,
            host=posthog_host,
        )

    async def run_experiment(
        self,
        experiment_id: str,
        variants: list[Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Runs a complete experiment: assigns a variant and tracks it in PostHog.

        Args:
            experiment_id: Unique experiment ID
            variants: Variants to test
            context: Additional context (niche, campaign_id, etc.)

        Returns:
            Dict with the assigned variant and experiment metadata
        """
        ctx = context or {}
        user_id = ctx.get("campaign_id") or ctx.get("user_id") or str(uuid.uuid4())

        # Assign variant with GrowthBook
        variant = self.ab_testing.get_variant(
            experiment_id=experiment_id,
            user_id=user_id,
            variants=variants,
        )

        # Track in PostHog
        self.analytics.capture_event(
            distinct_id=user_id,
            event="experiment_started",
            properties={
                "experiment_id": experiment_id,
                "variant": str(variant),
                **ctx,
            },
        )

        logger.info(
            "[GrowthEngine] Experiment %s: user=%s variant=%s", experiment_id, user_id, variant
        )

        return {
            "experiment_id": experiment_id,
            "user_id": user_id,
            "variant": variant,
            "context": ctx,
        }

    async def record_outcome(
        self,
        experiment_id: str,
        user_id: str,
        success: bool,
        revenue_usd: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Records the outcome of an experiment.

        Args:
            experiment_id: Experiment ID
            user_id: User ID
            success: Whether it succeeded
            revenue_usd: Revenue generated
            metadata: Additional data
        """
        # Record conversion in GrowthBook
        if success or revenue_usd > 0:
            self.ab_testing.track_conversion(
                experiment_id=experiment_id,
                user_id=user_id,
                value=revenue_usd,
                metric="revenue",
            )

        # Track in PostHog
        self.analytics.capture_event(
            distinct_id=user_id,
            event="experiment_outcome",
            properties={
                "experiment_id": experiment_id,
                "success": success,
                "revenue_usd": revenue_usd,
                **(metadata or {}),
            },
        )

    def get_full_report(self) -> dict[str, Any]:
        """Complete report of growth status."""
        return {
            "experiments": self.ab_testing.get_all_experiments(),
            "analytics_status": self.analytics.get_status(),
            "growthbook_available": GROWTHBOOK_AVAILABLE,
            "posthog_available": POSTHOG_AVAILABLE,
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_growth_engine_instance: AriaGrowthEngine | None = None


def get_growth_engine() -> AriaGrowthEngine:
    """Returns ARIA's Growth engine singleton."""
    global _growth_engine_instance
    if _growth_engine_instance is None:
        import os

        _growth_engine_instance = AriaGrowthEngine(
            posthog_api_key=os.getenv("POSTHOG_API_KEY", ""),
            posthog_host=os.getenv("POSTHOG_HOST", "https://app.posthog.com"),
            growthbook_api_host=os.getenv("GROWTHBOOK_API_HOST", "http://localhost:3100"),
            growthbook_client_key=os.getenv("GROWTHBOOK_CLIENT_KEY", ""),
        )
    return _growth_engine_instance
