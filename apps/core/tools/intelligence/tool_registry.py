"""
tool_registry.py — Per-tool reliability intelligence layer for ARIA AI.

Tracks call counts, success rates, latency, and error patterns per tool.
Persists to Redis under key "tool_registry:v1".
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("aria.tool_registry")

_REGISTRY_KEY = "tool_registry:v1"
_MAX_ERROR_PATTERNS = 10


@dataclass
class ToolRecord:
    name: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    last_used: str | None = None
    error_patterns: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count

    @property
    def avg_latency_ms(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_latency_ms / self.call_count

    def _composite_score(self) -> float:
        return self.success_rate * (1 / (1 + self.avg_latency_ms / 1000))

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ToolRecord:
        return cls(**d)


class ToolRegistry:
    """
    Per-tool reliability intelligence layer.

    Usage:
        registry = get_tool_registry()
        registry.register("web_search", category="web", tags=["search"])
        registry.record_call("web_search", success=True, latency_ms=320.5)
        stats = registry.get_stats("web_search")
        best = registry.best_tools(category="web", top_k=3)
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolRecord] = {}
        self._loaded = False
        self._cache = None

    def _get_cache(self):
        if self._cache is None:
            from apps.core.memory.redis_client import get_cache

            self._cache = get_cache()
        return self._cache

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            cache = self._get_cache()
            raw = await cache.get(_REGISTRY_KEY)
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                self._tools = {name: ToolRecord.from_dict(record) for name, record in data.items()}
                logger.info("[ToolRegistry] Loaded %d tools from Redis", len(self._tools))
        except Exception as exc:
            logger.warning("[ToolRegistry] Could not load from Redis: %s", exc)
        finally:
            # Prevent retry loops on persistent Redis failures.
            self._loaded = True

    async def _persist(self) -> None:
        try:
            cache = self._get_cache()
            payload = {name: record.to_dict() for name, record in self._tools.items()}
            await cache.set(_REGISTRY_KEY, json.dumps(payload), ttl_seconds=60 * 60 * 24 * 30)
        except Exception as exc:
            logger.warning("[ToolRegistry] Persist failed: %s", exc)

    # ── PUBLIC API ────────────────────────────────────────────

    def register(self, name: str, category: str = "general", tags: list[str] | None = None) -> None:
        if name in self._tools:
            return
        self._tools[name] = ToolRecord(
            name=name,
            category=category,
            tags=tags or [],
        )

    def record_call(
        self,
        name: str,
        success: bool,
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        if name not in self._tools:
            self.register(name)

        record = self._tools[name]
        record.call_count += 1
        record.total_latency_ms += latency_ms
        record.last_used = datetime.now(UTC).isoformat()

        if success:
            record.success_count += 1
        else:
            record.failure_count += 1
            if error:
                # Keep only the last N errors; list acts as a bounded deque.
                record.error_patterns.append(str(error))
                if len(record.error_patterns) > _MAX_ERROR_PATTERNS:
                    record.error_patterns = record.error_patterns[-_MAX_ERROR_PATTERNS:]

    def best_tools(
        self,
        category: str | None = None,
        min_success_rate: float = 0.5,
        top_k: int = 5,
    ) -> list[ToolRecord]:
        candidates = [
            r
            for r in self._tools.values()
            if (category is None or r.category == category)
            and r.call_count > 0
            and r.success_rate >= min_success_rate
        ]
        candidates.sort(key=lambda r: r._composite_score(), reverse=True)
        return candidates[:top_k]

    def failing_tools(self, threshold: float = 0.3) -> list[ToolRecord]:
        return [r for r in self._tools.values() if r.call_count >= 3 and r.success_rate < threshold]

    def get_stats(self, name: str) -> dict | None:
        record = self._tools.get(name)
        if record is None:
            return None
        return {
            **record.to_dict(),
            "success_rate": record.success_rate,
            "avg_latency_ms": record.avg_latency_ms,
            "composite_score": record._composite_score(),
        }

    def summary(self) -> dict:
        all_records = list(self._tools.values())
        active = [r for r in all_records if r.call_count > 0]

        avg_success = sum(r.success_rate for r in active) / len(active) if active else 0.0

        sorted_active = sorted(active, key=lambda r: r.success_rate, reverse=True)
        most_reliable = sorted_active[0].name if sorted_active else None
        least_reliable = sorted_active[-1].name if sorted_active else None

        return {
            "total_tools": len(all_records),
            "active_tools": len(active),
            "avg_success_rate": round(avg_success, 4),
            "most_reliable": most_reliable,
            "least_reliable": least_reliable,
        }

    def to_dict(self) -> dict:
        return {name: record.to_dict() for name, record in self._tools.items()}

    def from_dict(self, d: dict) -> None:
        self._tools = {name: ToolRecord.from_dict(record) for name, record in d.items()}


# ── SINGLETON ─────────────────────────────────────────────────
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
