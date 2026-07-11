"""
Capability Registry — ARIA's self-knowledge of what it can do, how well, and via what.

WHY THIS EXISTS
---------------
ARIA already has dozens of integrations (connections/, integrations/, tools/) and a
per-tool reliability layer (tools/intelligence/tool_registry.py). What was missing is
a single place that answers, at the *capability* level:

  - What can ARIA do right now? (the capability matrix)
  - For a goal/category, which provider should it use, and what's the fallback?
  - Is each capability healthy? (health checks)
  - What can it NOT do yet? (explicit gap list — status=PLANNED)

This is the foundation for discovering, evaluating, selecting, monitoring and
substituting tools automatically — the meta-capability that lets the system grow
from dozens to hundreds of integrations maintainably.

DESIGN
------
- A `Capability` describes a unit of ability (key="publishing.linkedin",
  category="publishing", provider="broadcaster", status, quality, verified, requires…).
- Runtime metrics (latency, success rate) are NOT re-implemented here — they are
  delegated to the existing ToolRegistry, keyed by capability key.
- `select(category)` returns the best ACTIVE provider for a category, ranked by
  verified → quality → live reliability score, with the rest available as fallbacks.
- Adding a capability/provider = register one object; selection & matrix update for free.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger("aria.capabilities")


class CapabilityStatus(StrEnum):
    ACTIVE = "active"  # works now
    DEGRADED = "degraded"  # works partially / unreliable / wrong-mode
    DOWN = "down"  # configured-but-failing or missing credentials
    PLANNED = "planned"  # a known gap ARIA does NOT have yet


class Quality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


_QUALITY_RANK = {Quality.HIGH: 3, Quality.MEDIUM: 2, Quality.LOW: 1, Quality.UNKNOWN: 0}


@dataclass
class Capability:
    """A single unit of ability, provided by one adapter/connector/API."""

    key: str  # "publishing.linkedin"
    category: str  # "publishing"
    provider: str  # "broadcaster" | "stripe" | "shopify" | ...
    description: str = ""
    status: CapabilityStatus = CapabilityStatus.ACTIVE
    quality: Quality = Quality.UNKNOWN
    verified: bool = False  # have we actually observed it succeed?
    requires: list[str] = field(default_factory=list)  # secret/permission NAMES (never values)
    cost_per_call_usd: float = 0.0
    rate_limit: str = ""
    standard: str = ""  # e.g. "OAuth2", "MCP", "OpenAPI"
    notes: str = ""
    # Optional async health check returning True if healthy. Not serialized.
    health_check: Callable[[], Awaitable[bool]] | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "category": self.category,
            "provider": self.provider,
            "description": self.description,
            "status": str(self.status),
            "quality": str(self.quality),
            "verified": self.verified,
            "requires": self.requires,
            "cost_per_call_usd": self.cost_per_call_usd,
            "rate_limit": self.rate_limit,
            "standard": self.standard,
            "notes": self.notes,
            "has_health_check": self.health_check is not None,
        }


class CapabilityRegistry:
    """In-memory registry of capabilities, with selection, health checks and a matrix."""

    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    # ── registration ────────────────────────────────────────────────────────
    def register(self, cap: Capability) -> None:
        self._caps[cap.key] = cap
        # Mirror into the reliability layer so live metrics accrue per capability.
        try:
            from apps.core.tools.intelligence.tool_registry import get_tool_registry

            get_tool_registry().register(cap.key, category=cap.category)
        except Exception:  # reliability layer is optional
            pass

    def register_many(self, caps: list[Capability]) -> None:
        for c in caps:
            self.register(c)

    # ── lookup ──────────────────────────────────────────────────────────────
    def get(self, key: str) -> Capability | None:
        return self._caps.get(key)

    def all(self) -> list[Capability]:
        return list(self._caps.values())

    def by_category(self, category: str) -> list[Capability]:
        return [c for c in self._caps.values() if c.category == category]

    def categories(self) -> list[str]:
        return sorted({c.category for c in self._caps.values()})

    # ── selection (which provider to use, with fallbacks) ─────────────────────
    def _reliability_score(self, key: str) -> float:
        try:
            from apps.core.tools.intelligence.tool_registry import get_tool_registry

            stats = get_tool_registry().get_stats(key)
            if stats and stats.get("call_count", 0) > 0:
                return float(stats.get("success_rate", 0.0))
        except Exception:
            pass
        return 0.5  # neutral prior when no data yet

    def select(self, category: str) -> Capability | None:
        """Best ACTIVE provider for a category. None if the category has no active provider."""
        ranked = self.rank(category)
        return ranked[0] if ranked else None

    def rank(self, category: str) -> list[Capability]:
        """All ACTIVE providers for a category, best-first (primary + fallbacks)."""
        active = [c for c in self.by_category(category) if c.status == CapabilityStatus.ACTIVE]
        return sorted(
            active,
            key=lambda c: (
                c.verified,
                _QUALITY_RANK.get(c.quality, 0),
                self._reliability_score(c.key),
            ),
            reverse=True,
        )

    # ── health ────────────────────────────────────────────────────────────────
    async def check(self, key: str) -> bool | None:
        """Run a capability's health check. None if it has none."""
        cap = self._caps.get(key)
        if not cap or cap.health_check is None:
            return None
        try:
            return bool(await cap.health_check())
        except Exception as exc:
            logger.warning("[capabilities] health check %s failed: %s", key, exc)
            return False

    async def check_all(self) -> dict[str, bool | None]:
        return {key: await self.check(key) for key in self._caps}

    # ── reporting ──────────────────────────────────────────────────────────────
    def matrix(self) -> list[dict]:
        """The capability matrix: what ARIA has, quality, verified — sorted by category."""
        return [c.to_dict() for c in sorted(self._caps.values(), key=lambda c: (c.category, c.key))]

    def missing(self) -> list[dict]:
        """Explicit gaps — capabilities ARIA does NOT have yet (status=PLANNED)."""
        return [c.to_dict() for c in self._caps.values() if c.status == CapabilityStatus.PLANNED]

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for c in self._caps.values():
            by_status[str(c.status)] = by_status.get(str(c.status), 0) + 1
        return {
            "total": len(self._caps),
            "by_status": by_status,
            "categories": self.categories(),
            "active": [c.key for c in self._caps.values() if c.status == CapabilityStatus.ACTIVE],
            "gaps": [c.key for c in self._caps.values() if c.status == CapabilityStatus.PLANNED],
        }


# ── Singleton (seeded by catalog.py on first access) ─────────────────────────────
_instance: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _instance
    if _instance is None:
        _instance = CapabilityRegistry()
        try:
            from apps.core.capabilities.catalog import seed_registry

            seed_registry(_instance)
        except Exception as exc:  # never let seeding break the registry
            logger.warning("[capabilities] seeding failed: %s", exc)
    return _instance
