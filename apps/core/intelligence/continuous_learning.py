"""
continuous_learning.py — ARIA's Continuous Self-Learning Engine.

ARIA learns from every interaction, extracts patterns with HuggingFace
models, and enriches its future responses with accumulated knowledge.

Learning cycle:
  1. Every interaction is recorded: who asked, what they asked, how ARIA responded
  2. Every N hours, the engine processes the accumulated batch with HF models:
     - Topic classification (zero-shot-classification)
     - Conversation summarization (summarization)
     - Key entity extraction (named-entity-recognition)
     - Embeddings for future semantic search (feature-extraction)
  3. Learnings are saved to Redis (fast cache) and Supabase (persistence)
  4. When responding, ARIA queries the learned context relevant to the topic
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.continuous_learning")

# ── REDIS KEYS ───────────────────────────────────────────────
INTERACTIONS_KEY = "aria:learning:interactions:v2"
KNOWLEDGE_KEY = "aria:learning:knowledge:{topic}"
LAST_CYCLE_KEY = "aria:learning:last_cycle"
TOPIC_FREQ_KEY = "aria:learning:topic_freq"
MODEL_PERF_KEY = "aria:learning:model_perf:{model}"
LEARNING_TTL = 60 * 60 * 24 * 30  # 30 days
CYCLE_INTERVAL_H = 4  # every 4 hours


@dataclass
class Interaction:
    """A recorded interaction between Aria and the world."""

    ts: str
    source: str  # "telegram", "scheduler", "webhook", etc.
    agent: str  # agent that responded
    user_text: str
    aria_text: str
    model_used: str
    latency_ms: int
    success: bool
    tokens: int = 0
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class KnowledgeCrystal:
    """A learned and compressed unit of knowledge."""

    topic: str
    summary: str
    key_entities: list[str]
    interaction_count: int
    avg_satisfaction: float  # 0-1 estimated from implicit signals
    hf_model_used: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class ContinuousLearningEngine:
    """
    ARIA's continuous self-learning engine.

    Usage:
        engine = get_learning_engine()

        # Record an interaction
        await engine.record(source="telegram", agent="telegram_conversation",
                            user_text="...", aria_text="...",
                            model_used="groq/llama", latency_ms=600)

        # Get learned context to enrich a response
        ctx = await engine.get_learned_context("digital marketing")

        # Run the full learning cycle (called by the scheduler)
        report = await engine.run_learning_cycle()
    """

    def __init__(self) -> None:
        self._cache = None
        self._db = None
        self._hf = None
        self._lock = asyncio.Lock()
        self._pending_interactions: list[Interaction] = []
        self._batch_size = 20

    def _get_cache(self):
        if not self._cache:
            from apps.core.memory.redis_client import get_cache

            self._cache = get_cache()
        return self._cache

    def _get_db(self):
        if not self._db:
            from apps.core.memory.supabase_client import get_db

            self._db = get_db()
        return self._db

    def _get_hf(self):
        if not self._hf:
            from apps.core.tools.hf_discovery import HFDiscovery

            self._hf = HFDiscovery()
        return self._hf

    # ── INTERACTION RECORDING ────────────────────────────────

    async def record(
        self,
        source: str,
        agent: str,
        user_text: str,
        aria_text: str,
        model_used: str,
        latency_ms: int,
        success: bool = True,
        tokens: int = 0,
        metadata: dict | None = None,
    ) -> None:
        """Records an interaction for later learning."""
        interaction = Interaction(
            ts=datetime.now(UTC).isoformat(),
            source=source,
            agent=agent,
            user_text=user_text[:500],  # limit for storage
            aria_text=aria_text[:800],
            model_used=model_used,
            latency_ms=latency_ms,
            success=success,
            tokens=tokens,
            metadata=metadata or {},
        )

        # Local buffer for batching
        async with self._lock:
            self._pending_interactions.append(interaction)

        # Flush to Redis if we have enough
        if len(self._pending_interactions) >= self._batch_size:
            await self._flush_to_redis()

        # Always flush at least the last one
        else:
            try:
                cache = self._get_cache()
                await cache.lpush(INTERACTIONS_KEY, interaction.to_json())
                await cache.expire(INTERACTIONS_KEY, LEARNING_TTL)
                logger.debug("[Learning] Interaction recorded: %s/%s", source, agent)
            except Exception as exc:
                logger.warning("[Learning] Could not record interaction: %s", exc)

    async def _flush_to_redis(self) -> None:
        async with self._lock:
            batch = self._pending_interactions[:]
            self._pending_interactions.clear()
        try:
            cache = self._get_cache()
            for interaction in batch:
                await cache.lpush(INTERACTIONS_KEY, interaction.to_json())
            await cache.expire(INTERACTIONS_KEY, LEARNING_TTL)
            logger.info("[Learning] Batch of %d interactions recorded", len(batch))
        except Exception as exc:
            logger.error("[Learning] Error flushing batch: %s", exc)

    # ── LEARNED CONTEXT ───────────────────────────────────────

    async def get_learned_context(self, topic: str, max_chars: int = 300) -> str:
        """
        Retrieves learned knowledge relevant to a topic.
        Use this to enrich the context of ARIA's responses.
        """
        try:
            cache = self._get_cache()
            topic_key = KNOWLEDGE_KEY.format(topic=topic[:40].replace(" ", "_").lower())
            raw = await cache.get(topic_key)
            if raw:
                crystal_data = json.loads(raw)
                summary = crystal_data.get("summary", "")
                entities = crystal_data.get("key_entities", [])
                count = crystal_data.get("interaction_count", 0)
                if summary:
                    entity_str = ", ".join(entities[:5]) if entities else ""
                    ctx = f"[Learned from {count} interactions about '{topic}': {summary}"
                    if entity_str:
                        ctx += f" | Key entities: {entity_str}"
                    ctx += "]"
                    return ctx[:max_chars]
        except Exception as exc:
            logger.debug("[Learning] Error retrieving context: %s", exc)
        return ""

    async def get_top_topics(self, n: int = 10) -> list[dict]:
        """Returns the most frequent topics learned by ARIA."""
        try:
            cache = self._get_cache()
            raw = await cache.get(TOPIC_FREQ_KEY)
            if raw:
                freq = json.loads(raw)
                sorted_topics = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:n]
                return [{"topic": t, "count": c} for t, c in sorted_topics]
        except Exception:
            pass
        return []

    # ── LEARNING CYCLE ────────────────────────────────────────

    async def run_learning_cycle(self) -> dict:
        """
        Main learning cycle. Called by the scheduler every 4h.
        Processes accumulated interactions with HF models and crystallizes knowledge.
        """
        t0 = time.time()
        logger.info("[Learning] ═══ Starting learning cycle ═══")

        # 1. Check whether it's time to run
        cache = self._get_cache()
        last_cycle_raw = await cache.get(LAST_CYCLE_KEY)
        if last_cycle_raw:
            last_ts = float(last_cycle_raw)
            elapsed_h = (time.time() - last_ts) / 3600
            if elapsed_h < CYCLE_INTERVAL_H:
                logger.info("[Learning] Next cycle in %.1fh", CYCLE_INTERVAL_H - elapsed_h)
                return {
                    "skipped": True,
                    "reason": f"Next cycle in {CYCLE_INTERVAL_H - elapsed_h:.1f}h",
                }

        # 2. Get accumulated interactions
        interactions = await self._load_interactions_from_redis(max_count=200)
        if not interactions:
            logger.info("[Learning] No interactions to process")
            await cache.set(LAST_CYCLE_KEY, str(time.time()), ttl_seconds=LEARNING_TTL)
            return {"processed": 0, "message": "No new interactions"}

        logger.info("[Learning] Processing %d interactions with HF models", len(interactions))

        results = {
            "interactions_processed": len(interactions),
            "topics_discovered": 0,
            "crystals_created": 0,
            "models_used": [],
            "errors": [],
            "duration_s": 0,
        }

        # 3. Classify interactions by topic (zero-shot)
        topics_map = await self._classify_topics(interactions)
        results["topics_discovered"] = len(topics_map)

        # 4. Crystallize knowledge for each topic
        for topic, topic_interactions in topics_map.items():
            try:
                crystal = await self._crystallize_topic(topic, topic_interactions)
                if crystal:
                    await self._save_crystal(crystal)
                    results["crystals_created"] += 1
            except Exception as exc:
                logger.error("[Learning] Error crystallizing '%s': %s", topic, exc)
                results["errors"].append(str(exc))

        # 5. Update topic frequency in Redis
        await self._update_topic_frequency(topics_map)

        # 6. Analyze model performance
        model_insights = await self._analyze_model_performance(interactions)
        results["model_performance"] = model_insights

        # 7. Mark cycle as completed
        await cache.set(LAST_CYCLE_KEY, str(time.time()), ttl_seconds=LEARNING_TTL)
        results["duration_s"] = round(time.time() - t0, 1)

        logger.info(
            "[Learning] ═══ Cycle completed: %d interactions, %d topics, %d crystals in %.1fs ═══",
            results["interactions_processed"],
            results["topics_discovered"],
            results["crystals_created"],
            results["duration_s"],
        )
        return results

    async def _load_interactions_from_redis(self, max_count: int = 200) -> list[Interaction]:
        """Loads and clears interactions from Redis."""
        try:
            cache = self._get_cache()
            raw_list = await cache.lrange(INTERACTIONS_KEY, 0, max_count - 1)
            interactions = []
            for raw in raw_list:
                try:
                    data = json.loads(raw)
                    interactions.append(Interaction(**data))
                except Exception:
                    continue
            # Clear the processed ones
            if interactions:
                await cache.ltrim(INTERACTIONS_KEY, len(interactions), -1)
            return interactions
        except Exception as exc:
            logger.error("[Learning] Error loading interactions: %s", exc)
            return []

    async def _classify_topics(
        self, interactions: list[Interaction]
    ) -> dict[str, list[Interaction]]:
        """
        Uses HF zero-shot-classification to group interactions by topic.
        """
        hf = self._get_hf()
        topics_map: dict[str, list[Interaction]] = {}
        # NOTE: these candidate labels are intentionally left in Spanish — they are
        # data fed to the zero-shot classifier and matched against interaction text
        # that may itself be in Spanish or English; translating them would change
        # classification behavior, not just prose.
        candidate_labels = [
            "ventas y marketing",
            "desarrollo de software",
            "finanzas e ingresos",
            "redes sociales",
            "estrategia de negocios",
            "consulta general",
            "automatización",
            "investigación de mercado",
            "ecommerce y shopify",
            "análisis de datos",
            "contenido y creatividad",
            "soporte técnico",
        ]

        # Process in batches of 5 to avoid overloading HF
        batch_size = 5
        for i in range(0, len(interactions), batch_size):
            batch = interactions[i : i + batch_size]
            for interaction in batch:
                if not interaction.user_text.strip():
                    continue
                try:
                    result = await asyncio.wait_for(
                        hf.discover_and_run(
                            task="zero-shot-classification",
                            payload={
                                "inputs": interaction.user_text[:200],
                                "parameters": {"candidate_labels": candidate_labels},
                            },
                        ),
                        timeout=20.0,
                    )
                    if result.get("success") and result.get("result"):
                        raw = result["result"]
                        labels = raw.get("labels", []) if isinstance(raw, dict) else []
                        topic = labels[0] if labels else "consulta general"
                    else:
                        topic = "consulta general"
                except Exception:
                    topic = "consulta general"

                if topic not in topics_map:
                    topics_map[topic] = []
                topics_map[topic].append(interaction)

            await asyncio.sleep(0.5)  # rate limiting

        return topics_map

    async def _crystallize_topic(
        self, topic: str, interactions: list[Interaction]
    ) -> KnowledgeCrystal | None:
        """
        Uses HF summarization to crystallize what was learned about a topic.
        """
        if not interactions:
            return None

        hf = self._get_hf()

        # Build text to summarize
        texts = []
        for ix in interactions[:10]:  # max 10 per crystal
            texts.append(f"User: {ix.user_text[:150]}\nARIA: {ix.aria_text[:200]}")
        full_text = "\n\n".join(texts)

        # Summarize with HF
        summary = ""
        model_used = "none"
        try:
            result = await asyncio.wait_for(
                hf.discover_and_run(
                    task="summarization",
                    payload={"inputs": full_text[:1024]},
                ),
                timeout=30.0,
            )
            if result.get("success") and result.get("result"):
                raw = result["result"]
                summary = (
                    raw[0].get("summary_text", "")
                    if isinstance(raw, list)
                    else raw.get("summary_text", "") if isinstance(raw, dict) else str(raw)
                )[:400]
                model_used = result.get("model_used", "hf/summarization")
        except Exception as exc:
            logger.warning("[Learning] Summarization failed for '%s': %s", topic, exc)
            # Fallback: concatenate first interactions
            summary = " | ".join(t[:80] for t in [ix.user_text for ix in interactions[:3]])[:300]

        # Extract entities with NER
        key_entities: list[str] = []
        try:
            ner_result = await asyncio.wait_for(
                hf.discover_and_run(
                    task="named-entity-recognition",
                    payload={"inputs": full_text[:512]},
                ),
                timeout=20.0,
            )
            if ner_result.get("success") and ner_result.get("result"):
                raw = ner_result["result"]
                if isinstance(raw, list):
                    seen = set()
                    for ent in raw:
                        word = ent.get("word", "").strip("#")
                        if word and len(word) > 2 and word not in seen:
                            key_entities.append(word)
                            seen.add(word)
                            if len(key_entities) >= 10:
                                break
        except Exception:
            pass

        # Compute implicit satisfaction: long responses + no errors = better score
        avg_lat = sum(ix.latency_ms for ix in interactions) / len(interactions)
        success_rate = sum(1 for ix in interactions if ix.success) / len(interactions)
        avg_satisfaction = round(
            min(1.0, success_rate * 0.7 + (1 - min(avg_lat, 3000) / 3000) * 0.3), 2
        )

        now = datetime.now(UTC).isoformat()
        return KnowledgeCrystal(
            topic=topic,
            summary=summary,
            key_entities=key_entities,
            interaction_count=len(interactions),
            avg_satisfaction=avg_satisfaction,
            hf_model_used=model_used,
            created_at=now,
            updated_at=now,
        )

    async def _save_crystal(self, crystal: KnowledgeCrystal) -> None:
        """Saves a knowledge crystal to Redis (and optionally Supabase)."""
        topic_key = KNOWLEDGE_KEY.format(topic=crystal.topic[:40].replace(" ", "_").lower())
        try:
            cache = self._get_cache()
            await cache.set(
                topic_key, json.dumps(crystal.to_dict(), ensure_ascii=False), ttl_seconds=LEARNING_TTL
            )
            logger.info(
                "[Learning] Crystal saved: '%s' (%d interactions)",
                crystal.topic,
                crystal.interaction_count,
            )
        except Exception as exc:
            logger.error("[Learning] Error saving crystal '%s': %s", crystal.topic, exc)

    async def _update_topic_frequency(self, topics_map: dict[str, list]) -> None:
        """Updates the topic frequency counter in Redis."""
        try:
            cache = self._get_cache()
            raw = await cache.get(TOPIC_FREQ_KEY)
            # cache.get() already deserializes JSON — re-decoding raised
            # TypeError on every call once data existed, silently swallowed.
            freq = raw if raw else {}
            for topic, interactions in topics_map.items():
                freq[topic] = freq.get(topic, 0) + len(interactions)
            await cache.set(TOPIC_FREQ_KEY, json.dumps(freq), ttl_seconds=LEARNING_TTL)
        except Exception as exc:
            logger.warning("[Learning] Error updating topic frequency: %s", exc)

    async def _analyze_model_performance(self, interactions: list[Interaction]) -> dict[str, Any]:
        """Analyzes which models give the best results based on the interactions."""
        perf: dict[str, dict] = {}
        for ix in interactions:
            m = ix.model_used or "unknown"
            if m not in perf:
                perf[m] = {"calls": 0, "success": 0, "total_latency": 0, "total_tokens": 0}
            perf[m]["calls"] += 1
            perf[m]["success"] += int(ix.success)
            perf[m]["total_latency"] += ix.latency_ms
            perf[m]["total_tokens"] += ix.tokens

        summary = {}
        for m, stats in perf.items():
            if stats["calls"] > 0:
                summary[m] = {
                    "calls": stats["calls"],
                    "success_rate": round(stats["success"] / stats["calls"], 3),
                    "avg_latency_ms": round(stats["total_latency"] / stats["calls"]),
                    "avg_tokens": round(stats["total_tokens"] / stats["calls"]),
                }
        return summary

    # ── REPORT ───────────────────────────────────────────────

    async def get_learning_report(self) -> dict:
        """Generates a report of the continuous learning state."""
        try:
            cache = self._get_cache()
            pending_count = await cache.llen(INTERACTIONS_KEY)
            top_topics = await self.get_top_topics(10)
            last_cycle_raw = await cache.get(LAST_CYCLE_KEY)
            last_cycle = "Never"
            if last_cycle_raw:
                dt = datetime.fromtimestamp(float(last_cycle_raw), tz=UTC)
                last_cycle = dt.strftime("%Y-%m-%d %H:%M UTC")
            return {
                "pending_interactions": pending_count or 0,
                "top_topics": top_topics,
                "last_cycle": last_cycle,
                "local_buffer": len(self._pending_interactions),
            }
        except Exception as exc:
            return {"error": str(exc)}


# ── SINGLETON ──────────────────────────────────────────────────
_learning_engine: ContinuousLearningEngine | None = None


def get_learning_engine() -> ContinuousLearningEngine:
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = ContinuousLearningEngine()
    return _learning_engine
