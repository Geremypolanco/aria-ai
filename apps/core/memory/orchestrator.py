"""
ARIA Memory Orchestrator — unified retrieval across all memory layers.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.memory.orchestrator")

try:
    from .semantic_memory import SemanticMemory, Fact, get_semantic_memory
    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False
    SemanticMemory = None  # type: ignore[assignment,misc]
    Fact = None  # type: ignore[assignment]
    get_semantic_memory = None  # type: ignore[assignment]

try:
    from .procedural.procedural_memory import ProceduralMemory, Procedure, get_procedural_memory
    _PROCEDURAL_AVAILABLE = True
except ImportError:
    _PROCEDURAL_AVAILABLE = False
    ProceduralMemory = None  # type: ignore[assignment,misc]
    Procedure = None  # type: ignore[assignment]
    get_procedural_memory = None  # type: ignore[assignment]

try:
    from .temporal.temporal_memory import TemporalMemory, TemporalEvent, get_temporal_memory
    _TEMPORAL_AVAILABLE = True
except ImportError:
    _TEMPORAL_AVAILABLE = False
    TemporalMemory = None  # type: ignore[assignment,misc]
    TemporalEvent = None  # type: ignore[assignment]
    get_temporal_memory = None  # type: ignore[assignment]

# Episodic memory does not exist yet; all call sites check _EPISODIC_AVAILABLE.
_EPISODIC_AVAILABLE = False

_HOUR = 3600.0
_DAY = 86400.0

_CONTRADICTION_SIGNALS = frozenset({
    "not", "no longer", "never", "failed", "failure", "false",
    "incorrect", "wrong", "invalid", "broken", "removed", "deleted",
    "disabled", "deprecated", "stopped", "cancelled",
})
_SUCCESS_SIGNALS = frozenset({
    "success", "succeeded", "true", "correct", "valid", "working",
    "enabled", "active", "completed", "done", "achieved",
})


@dataclass
class RankedMemoryItem:
    source_layer: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryContext:
    query: str
    facts: list[Any] = field(default_factory=list)
    procedures: list[Any] = field(default_factory=list)
    recent_events: list[Any] = field(default_factory=list)
    conflicts: list[tuple[Any, Any]] = field(default_factory=list)
    ranked_items: list[RankedMemoryItem] = field(default_factory=list)


def _recency_weight(ts: float) -> float:
    age = datetime.now(timezone.utc).timestamp() - ts
    if age <= _HOUR:
        return 1.0
    if age <= _DAY:
        return 0.8
    return 0.5


def _token_set(text: str) -> set[str]:
    return set(text.lower().split())


def _word_overlap(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _polarity(text: str) -> str:
    tokens = _token_set(text)
    has_neg = bool(tokens & _CONTRADICTION_SIGNALS)
    has_pos = bool(tokens & _SUCCESS_SIGNALS)
    if has_neg and not has_pos:
        return "negative"
    if has_pos and not has_neg:
        return "positive"
    return "neutral"


def _detect_conflicts(facts: list[Any]) -> list[tuple[Any, Any]]:
    """
    Two facts conflict when they share the same category, their content
    overlaps enough to be about the same entity (>70%), but carry opposite
    polarities. A neutral fact never triggers a conflict pairing so that
    purely descriptive statements don't shadow each other.
    """
    conflicts: list[tuple[Any, Any]] = []
    n = len(facts)
    for i in range(n):
        for j in range(i + 1, n):
            fa, fb = facts[i], facts[j]
            if getattr(fa, "category", None) != getattr(fb, "category", None):
                continue
            if _word_overlap(fa.content, fb.content) < 0.7:
                continue
            pa, pb = _polarity(fa.content), _polarity(fb.content)
            if pa == "neutral" or pb == "neutral":
                continue
            if pa != pb:
                conflicts.append((fa, fb))
    return conflicts


def _deduplicate(items: list[RankedMemoryItem]) -> list[RankedMemoryItem]:
    """
    Drop items whose content overlaps >80% with a higher-scored item already
    in the accepted list. Items arrive pre-sorted descending by score so the
    first occurrence is always the dominant one.
    """
    accepted: list[RankedMemoryItem] = []
    for candidate in items:
        for kept in accepted:
            if _word_overlap(candidate.content, kept.content) > 0.8:
                break
        else:
            accepted.append(candidate)
    return accepted


def _fact_to_ranked(fact: Any, base_score: float) -> RankedMemoryItem:
    try:
        created_ts = datetime.fromisoformat(fact.created_at).timestamp()
    except Exception:
        created_ts = datetime.now(timezone.utc).timestamp()

    rw = _recency_weight(created_ts)
    score = base_score * getattr(fact, "confidence", 1.0) * rw
    return RankedMemoryItem(
        source_layer="semantic",
        content=fact.content,
        score=score,
        metadata={
            "id": fact.id,
            "category": fact.category,
            "confidence": fact.confidence,
            "source": fact.source,
            "created_at": fact.created_at,
        },
    )


def _procedure_to_ranked(proc: Any) -> RankedMemoryItem:
    try:
        created_ts = datetime.fromisoformat(proc.created_at).timestamp()
    except Exception:
        created_ts = datetime.now(timezone.utc).timestamp()

    rw = _recency_weight(created_ts)
    score = proc.utility_score() * rw
    content = f"{proc.name}: {proc.goal_pattern} ({len(proc.steps)} steps)"
    return RankedMemoryItem(
        source_layer="procedural",
        content=content,
        score=score,
        metadata={
            "id": proc.id,
            "name": proc.name,
            "success_rate": proc.success_rate,
            "execution_count": proc.execution_count,
            "is_trusted": proc.is_trusted,
        },
    )


def _event_to_ranked(event: Any) -> RankedMemoryItem:
    rw = _recency_weight(event.ts)
    # importance is the semantic weight for temporal events; confidence
    # doesn't exist here, so treat importance as the confidence proxy.
    score = getattr(event, "importance", 0.5) * rw
    content_parts = [f"[{event.event_type.value}] {event.entity_name}"]
    payload_summary = " ".join(
        f"{k}={v}" for k, v in list(event.payload.items())[:3]
    )
    if payload_summary:
        content_parts.append(payload_summary)
    content = " ".join(content_parts)
    return RankedMemoryItem(
        source_layer="temporal",
        content=content,
        score=score,
        metadata={
            "id": event.id,
            "ts": event.ts,
            "ts_iso": event.ts_iso,
            "event_type": event.event_type.value,
            "entity_id": event.entity_id,
            "success": event.success,
        },
    )


class MemoryOrchestrator:
    """
    Single entry point for reading and writing across all ARIA memory layers.

    Layer availability is discovered at runtime so the orchestrator degrades
    gracefully as individual backends come online incrementally.
    """

    def __init__(self) -> None:
        self._semantic: Optional[Any] = get_semantic_memory() if _SEMANTIC_AVAILABLE else None
        self._procedural: Optional[Any] = get_procedural_memory() if _PROCEDURAL_AVAILABLE else None
        self._temporal: Optional[Any] = get_temporal_memory() if _TEMPORAL_AVAILABLE else None

    # ── Public API ───────────────────────────────────────────────────────

    async def retrieve(self, query: str, top_k: int = 10) -> MemoryContext:
        ctx = MemoryContext(query=query)

        results = await asyncio.gather(
            self._fetch_semantic(query, top_k),
            self._fetch_procedural(query),
            self._fetch_temporal(top_k),
            return_exceptions=True,
        )

        facts = results[0] if not isinstance(results[0], BaseException) else []
        procedures = results[1] if not isinstance(results[1], BaseException) else []
        events = results[2] if not isinstance(results[2], BaseException) else []

        if isinstance(results[0], BaseException):
            logger.warning("[Orchestrator] Semantic fetch failed: %s", results[0])
        if isinstance(results[1], BaseException):
            logger.warning("[Orchestrator] Procedural fetch failed: %s", results[1])
        if isinstance(results[2], BaseException):
            logger.warning("[Orchestrator] Temporal fetch failed: %s", results[2])

        ctx.facts = facts
        ctx.procedures = procedures
        ctx.recent_events = events
        ctx.conflicts = _detect_conflicts(facts)

        ranked: list[RankedMemoryItem] = []

        for i, fact in enumerate(facts):
            # Position within the already-ranked semantic results encodes
            # relative relevance; map rank 0 → 1.0, rank n → diminishing.
            position_score = 1.0 / (1.0 + i)
            ranked.append(_fact_to_ranked(fact, base_score=position_score))

        for proc in procedures:
            ranked.append(_procedure_to_ranked(proc))

        for event in events:
            ranked.append(_event_to_ranked(event))

        ranked.sort(key=lambda r: r.score, reverse=True)
        ranked = _deduplicate(ranked)
        ctx.ranked_items = ranked[:top_k]

        return ctx

    async def store_fact(
        self,
        content: str,
        category: str = "world_fact",
        source: str = "aria",
        confidence: float = 0.8,
    ) -> Optional[str]:
        if not _SEMANTIC_AVAILABLE or self._semantic is None:
            logger.warning("[Orchestrator] Semantic memory unavailable; fact not stored")
            return None
        return await self._semantic.store(
            content=content,
            category=category,
            source=source,
            confidence=confidence,
        )

    def summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "layers_available": {
                "semantic": _SEMANTIC_AVAILABLE,
                "procedural": _PROCEDURAL_AVAILABLE,
                "temporal": _TEMPORAL_AVAILABLE,
                "episodic": _EPISODIC_AVAILABLE,
            }
        }
        if _SEMANTIC_AVAILABLE and self._semantic is not None:
            try:
                result["semantic"] = self._semantic.summary()
            except Exception as exc:
                result["semantic"] = {"error": str(exc)}

        if _PROCEDURAL_AVAILABLE and self._procedural is not None:
            try:
                result["procedural"] = self._procedural.summary()
            except Exception as exc:
                result["procedural"] = {"error": str(exc)}

        if _TEMPORAL_AVAILABLE and self._temporal is not None:
            try:
                result["temporal"] = self._temporal.summary()
            except Exception as exc:
                result["temporal"] = {"error": str(exc)}

        return result

    # ── Private fetch helpers ─────────────────────────────────────────────

    async def _fetch_semantic(self, query: str, top_k: int) -> list[Any]:
        if not _SEMANTIC_AVAILABLE or self._semantic is None:
            return []
        return await self._semantic.search(query, top_k=top_k)

    async def _fetch_procedural(self, query: str) -> list[Any]:
        if not _PROCEDURAL_AVAILABLE or self._procedural is None:
            return []
        proc = await self._procedural.retrieve(query)
        return [proc] if proc is not None else []

    async def _fetch_temporal(self, n: int) -> list[Any]:
        if not _TEMPORAL_AVAILABLE or self._temporal is None:
            return []
        return await self._temporal.recent(n)


_orchestrator: Optional[MemoryOrchestrator] = None


def get_memory_orchestrator() -> MemoryOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MemoryOrchestrator()
    return _orchestrator
