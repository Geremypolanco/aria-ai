"""
model_router.py — Model Discovery and Intelligent Routing Engine.

ARIA automatically discovers:
  1. All of its own functions and agents
  2. All HF models available for each task type
  3. Which model is best suited for each function/task

The ModelRouter dynamically updates HF_MODEL_ROTATION in Redis,
so that AriaAIClient always loads the optimal configuration.

Discovery cycle (runs every 24h via scheduler):
  1. Scan Aria's functions → map to HF task_type
  2. For each task_type, look up top models on the HF Hub
  3. Benchmark candidates with real prompts and measure: latency, success rate, quality
  4. Update the routing table in Redis
  5. ai_client.py loads the updated table on startup or each cycle
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.model_router")

# ── REDIS KEYS ───────────────────────────────────────────────
ROUTING_TABLE_KEY = "aria:model_router:routing_table:v3"
BENCHMARK_KEY = "aria:model_router:benchmark:{model_id}"
DISCOVERY_LOG_KEY = "aria:model_router:discovery_log"
LAST_DISCOVERY_KEY = "aria:model_router:last_discovery"
ROUTING_TTL = 60 * 60 * 24 * 7  # 7 days
DISCOVERY_INTERVAL = 60 * 60 * 24  # 24 hours


# ── ARIA FUNCTION MAP ─────────────────────────────────────────
# Each Aria function/agent → best-suited HF task_type + description
ARIA_FUNCTION_MAP: dict[str, dict] = {
    # Conversation and comprehension
    "telegram_conversation": {
        "hf_task": "text-generation",
        "priority": "speed",
        "desc": "Free-form conversational responses",
    },
    "telegram_analysis": {
        "hf_task": "text-generation",
        "priority": "quality",
        "desc": "Internal analysis before responding",
    },
    "support_agent": {
        "hf_task": "text-generation",
        "priority": "quality",
        "desc": "Support and troubleshooting",
    },
    # Analysis and classification
    "intent_detection": {
        "hf_task": "zero-shot-classification",
        "priority": "speed",
        "desc": "Detect user intent",
    },
    "topic_classification": {
        "hf_task": "zero-shot-classification",
        "priority": "speed",
        "desc": "Classify the topic of an interaction",
    },
    "sentiment_analysis": {
        "hf_task": "sentiment-analysis",
        "priority": "speed",
        "desc": "Analyze sentiment of text",
    },
    "compliance_check": {
        "hf_task": "zero-shot-classification",
        "priority": "quality",
        "desc": "Verify ethical compliance",
    },
    # Generation and content
    "content_agent": {
        "hf_task": "text-generation",
        "priority": "creative",
        "desc": "Create content for social media",
    },
    "creative_engine": {
        "hf_task": "text-generation",
        "priority": "creative",
        "desc": "Idea generation and creativity",
    },
    "marketing_agent": {
        "hf_task": "text-generation",
        "priority": "quality",
        "desc": "Marketing strategy and copy",
    },
    # Code and technical
    "dev_agent": {
        "hf_task": "text-generation",
        "priority": "code",
        "desc": "Development and code review",
    },
    "enhanced_dev_agent": {
        "hf_task": "text-generation",
        "priority": "code",
        "desc": "Advanced development with refactoring",
    },
    "code_reflector": {
        "hf_task": "text-generation",
        "priority": "code",
        "desc": "Analysis and improvement of its own code",
    },
    # Research and data
    "research_agent": {
        "hf_task": "summarization",
        "priority": "quality",
        "desc": "Research and information synthesis",
    },
    "market_intelligence": {
        "hf_task": "zero-shot-classification",
        "priority": "quality",
        "desc": "Market trend analysis",
    },
    "web_search_synthesis": {
        "hf_task": "summarization",
        "priority": "speed",
        "desc": "Summarize web search results",
    },
    # Finance and business
    "cfo_agent": {
        "hf_task": "text-generation",
        "priority": "quality",
        "desc": "Financial analysis and CFO duties",
    },
    "pm_agent": {
        "hf_task": "text-generation",
        "priority": "quality",
        "desc": "Product management and roadmap",
    },
    "ecommerce_agent": {
        "hf_task": "text-generation",
        "priority": "quality",
        "desc": "E-commerce and Shopify",
    },
    # Specialized text processing
    "entity_extraction": {
        "hf_task": "named-entity-recognition",
        "priority": "speed",
        "desc": "Extract people, companies, places",
    },
    "text_summarization": {
        "hf_task": "summarization",
        "priority": "quality",
        "desc": "Summarize long documents",
    },
    "translation": {
        "hf_task": "translation",
        "priority": "speed",
        "desc": "Translation between languages",
    },
    "document_qa": {
        "hf_task": "document-question-answering",
        "priority": "quality",
        "desc": "Questions about documents",
    },
    # Multimedia
    "image_description": {
        "hf_task": "image-to-text",
        "priority": "quality",
        "desc": "Describe images",
    },
    "image_generation": {
        "hf_task": "image-generation",
        "priority": "quality",
        "desc": "Generate images with AI",
    },
    "audio_transcription": {
        "hf_task": "automatic-speech-recognition",
        "priority": "quality",
        "desc": "Transcribe audio (Whisper)",
    },
    "text_to_speech": {
        "hf_task": "text-to-speech",
        "priority": "quality",
        "desc": "Convert text to speech",
    },
    # Embeddings and similarity
    "semantic_search": {
        "hf_task": "feature-extraction",
        "priority": "speed",
        "desc": "Semantic search and similarity",
    },
    "knowledge_retrieval": {
        "hf_task": "feature-extraction",
        "priority": "speed",
        "desc": "Retrieve relevant knowledge",
    },
}

# Extra candidate models by priority type (for benchmarking)
BENCHMARK_CANDIDATES: dict[str, list[str]] = {
    "text-generation": [
        "Qwen/Qwen2.5-72B-Instruct",
        "Qwen/Qwen2.5-7B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3",
        "HuggingFaceH4/zephyr-7b-beta",
        "microsoft/Phi-3-mini-4k-instruct",
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "google/gemma-7b-it",
    ],
    "summarization": [
        "facebook/bart-large-cnn",
        "sshleifer/distilbart-cnn-12-6",
        "google/pegasus-xsum",
        "philschmid/bart-large-cnn-samsum",
    ],
    "zero-shot-classification": [
        "facebook/bart-large-mnli",
        "cross-encoder/nli-deberta-v3-large",
        "MoritzLaurer/deberta-v3-large-zeroshot-v2.0",
        "typeform/distilbert-base-uncased-mnli",
    ],
    "sentiment-analysis": [
        "distilbert-base-uncased-finetuned-sst-2-english",
        "cardiffnlp/twitter-roberta-base-sentiment-latest",
        "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
        "nlptown/bert-base-multilingual-uncased-sentiment",
    ],
    "named-entity-recognition": [
        "dslim/bert-base-NER",
        "Jean-Baptiste/roberta-large-ner-english",
        "dbmdz/bert-large-cased-finetuned-conll03-english",
    ],
    "feature-extraction": [
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/all-mpnet-base-v2",
        "BAAI/bge-small-en-v1.5",
    ],
}

# Benchmark prompts by task
BENCHMARK_PROMPTS: dict[str, Any] = {
    "text-generation": {
        "inputs": "Explain in 2 sentences why content marketing is important for a business.",
        "parameters": {"max_new_tokens": 80, "temperature": 0.7},
    },
    "summarization": {
        "inputs": "Digital marketing is the component of marketing that uses the internet and online digital technology such as desktop computers, mobile phones, and other digital media and platforms to promote products and services.",
    },
    "zero-shot-classification": {
        "inputs": "How much money did I generate this week?",
        "parameters": {"candidate_labels": ["finance", "marketing", "support", "development"]},
    },
    "sentiment-analysis": {
        "inputs": "I'm very satisfied with today's results, everything worked perfectly.",
    },
    "named-entity-recognition": {
        "inputs": "Amazon and Google are the leading technology companies in the United States.",
    },
    "feature-extraction": {
        "inputs": "revenue growth and monetization strategy",
    },
}


@dataclass
class ModelScore:
    model_id: str
    hf_task: str
    latency_ms: int
    success: bool
    quality_score: float  # 0-1
    response_len: int
    timestamp: str

    def composite_score(self) -> float:
        if not self.success:
            return 0.0
        # Penalize latency > 5000ms, reward non-empty responses
        latency_penalty = min(1.0, self.latency_ms / 5000)
        return round(
            self.quality_score * 0.5
            + (1 - latency_penalty) * 0.3
            + min(1.0, self.response_len / 200) * 0.2,
            3,
        )


@dataclass
class RoutingEntry:
    function_name: str
    hf_task: str
    priority: str
    best_model: str
    fallback_models: list[str]
    composite_score: float
    last_benchmarked: str
    desc: str

    def to_dict(self) -> dict:
        return asdict(self)


class ModelRouter:
    """
    Intelligent HF model discovery and routing engine.

    Usage:
        router = get_model_router()

        # Get the best model for an Aria function
        model = await router.get_best_model("content_agent")

        # Run the full discovery cycle (called by the scheduler)
        report = await router.run_discovery_cycle()

        # View the full routing table
        table = await router.get_routing_table()
    """

    def __init__(self) -> None:
        self._cache = None
        self._hf = None
        self._routing_table: dict[str, RoutingEntry] = {}
        self._table_loaded = False

    def _get_cache(self):
        if not self._cache:
            from apps.core.memory.redis_client import get_cache

            self._cache = get_cache()
        return self._cache

    def _get_hf(self):
        if not self._hf:
            from apps.core.tools.hf_discovery import HFDiscovery

            self._hf = HFDiscovery()
        return self._hf

    # ── PUBLIC API ───────────────────────────────────────────

    async def get_best_model(self, function_name: str) -> str | None:
        """
        Returns the best HF model for an Aria function.
        If there is no benchmark, returns the default preferred model.
        """
        await self._ensure_table_loaded()
        entry = self._routing_table.get(function_name)
        if entry and entry.best_model:
            return entry.best_model
        # Fallback to static configuration
        func_def = ARIA_FUNCTION_MAP.get(function_name, {})
        task = func_def.get("hf_task", "text-generation")
        candidates = BENCHMARK_CANDIDATES.get(task, [])
        return candidates[0] if candidates else None

    async def get_routing_table(self) -> dict[str, Any]:
        """Returns the full routing table."""
        await self._ensure_table_loaded()
        return {k: v.to_dict() for k, v in self._routing_table.items()}

    async def get_hf_rotation_config(self) -> dict[str, list[str]]:
        """
        Generates the updated HF_MODEL_ROTATION dictionary
        based on real benchmarks. ai_client.py can use this.
        """
        await self._ensure_table_loaded()
        from apps.core.tools.ai_client import AIModel

        # Map priorities to AIModel
        priority_to_model = {
            "speed": AIModel.FAST,
            "quality": AIModel.STRATEGY,
            "code": AIModel.CODE,
            "creative": AIModel.CREATIVE,
        }

        rotation: dict[str, list[str]] = {
            AIModel.FAST.value: [],
            AIModel.STRATEGY.value: [],
            AIModel.CODE.value: [],
            AIModel.CREATIVE.value: [],
        }

        for func_name, entry in self._routing_table.items():
            func_def = ARIA_FUNCTION_MAP.get(func_name, {})
            priority = func_def.get("priority", "quality")
            if priority not in priority_to_model:
                continue
            model_key = priority_to_model[priority].value
            # Add model if not already present and it's a text-generation model
            if (
                entry.hf_task == "text-generation"
                and entry.best_model
                and entry.best_model not in rotation[model_key]
            ):
                rotation[model_key].insert(0, entry.best_model)
                for fb in entry.fallback_models[:2]:
                    if fb not in rotation[model_key]:
                        rotation[model_key].append(fb)

        # Remove empty lists
        return {k: v for k, v in rotation.items() if v}

    # ── DISCOVERY CYCLE ───────────────────────────────────────

    async def run_discovery_cycle(self) -> dict:
        """
        Full discovery cycle. Called by the scheduler every 24h.
        """
        t0 = time.time()
        logger.info("[ModelRouter] ═══ Starting discovery cycle ═══")

        # Check whether it's time
        cache = self._get_cache()
        last_raw = await cache.get(LAST_DISCOVERY_KEY)
        if last_raw:
            elapsed = time.time() - float(last_raw)
            if elapsed < DISCOVERY_INTERVAL:
                remaining_h = (DISCOVERY_INTERVAL - elapsed) / 3600
                logger.info("[ModelRouter] Next cycle in %.1fh", remaining_h)
                return {"skipped": True, "reason": f"Next cycle in {remaining_h:.1f}h"}

        results = {
            "functions_discovered": len(ARIA_FUNCTION_MAP),
            "tasks_benchmarked": 0,
            "models_evaluated": 0,
            "routing_entries_updated": 0,
            "errors": [],
            "duration_s": 0,
        }

        # Group functions by task_type to avoid benchmarking the same task twice
        task_groups: dict[str, list[str]] = {}
        for func_name, func_def in ARIA_FUNCTION_MAP.items():
            task = func_def["hf_task"]
            if task not in task_groups:
                task_groups[task] = []
            task_groups[task].append(func_name)

        # Benchmark each task_type
        task_results: dict[str, list[ModelScore]] = {}
        for task_type, func_names in task_groups.items():
            logger.info(
                "[ModelRouter] Benchmarking task: %s (%d functions)", task_type, len(func_names)
            )
            scores = await self._benchmark_task(task_type)
            task_results[task_type] = scores
            results["tasks_benchmarked"] += 1
            results["models_evaluated"] += len(scores)
            await asyncio.sleep(1)  # rate limiting between tasks

        # Build the routing table
        new_table: dict[str, RoutingEntry] = {}
        for func_name, func_def in ARIA_FUNCTION_MAP.items():
            task = func_def["hf_task"]
            scores = task_results.get(task, [])
            # Sort by composite_score
            ranked = sorted(scores, key=lambda s: s.composite_score(), reverse=True)
            successful = [s for s in ranked if s.success]

            best_model = (
                successful[0].model_id if successful else (BENCHMARK_CANDIDATES.get(task, [""])[0])
            )
            fallbacks = [s.model_id for s in successful[1:4]]

            entry = RoutingEntry(
                function_name=func_name,
                hf_task=task,
                priority=func_def["priority"],
                best_model=best_model,
                fallback_models=fallbacks,
                composite_score=successful[0].composite_score() if successful else 0.0,
                last_benchmarked=datetime.now(UTC).isoformat(),
                desc=func_def["desc"],
            )
            new_table[func_name] = entry
            results["routing_entries_updated"] += 1

        # Persist to Redis
        self._routing_table = new_table
        await self._save_routing_table()

        # Update HF_MODEL_ROTATION in Redis so ai_client uses it
        rotation = await self.get_hf_rotation_config()
        if rotation:
            await cache.set(
                "aria:model_router:hf_rotation",
                json.dumps(rotation),
                ttl_seconds=ROUTING_TTL,
            )
            logger.info("[ModelRouter] HF_MODEL_ROTATION updated: %s", list(rotation.keys()))

        # Discovery log
        log_entry = {
            "ts": datetime.now(UTC).isoformat(),
            "functions": results["functions_discovered"],
            "tasks": results["tasks_benchmarked"],
            "models": results["models_evaluated"],
            "entries": results["routing_entries_updated"],
        }
        await cache.set(LAST_DISCOVERY_KEY, str(time.time()), ttl_seconds=ROUTING_TTL)
        await cache.lpush(DISCOVERY_LOG_KEY, json.dumps(log_entry))
        await cache.ltrim(DISCOVERY_LOG_KEY, 0, 29)  # keep last 30

        results["duration_s"] = round(time.time() - t0, 1)
        logger.info(
            "[ModelRouter] ═══ Discovery completed: %d functions, %d models evaluated in %.1fs ═══",
            results["functions_discovered"],
            results["models_evaluated"],
            results["duration_s"],
        )
        return results

    async def _benchmark_task(self, task_type: str) -> list[ModelScore]:
        """Benchmarks candidate models for a task type."""
        hf = self._get_hf()
        candidates = BENCHMARK_CANDIDATES.get(task_type, [])
        prompt = BENCHMARK_PROMPTS.get(task_type)

        if not prompt or not candidates:
            return []

        scores: list[ModelScore] = []

        for model_id in candidates[:6]:  # max 6 candidates per task
            t0 = time.time()
            success = False
            quality = 0.0
            response_len = 0

            try:
                result = await asyncio.wait_for(
                    hf._run_model(model_id, prompt, binary_output=False, binary_input=False),
                    timeout=25.0,
                )
                latency_ms = int((time.time() - t0) * 1000)

                if result.get("success"):
                    success = True
                    raw = result.get("result", "")
                    text = ""
                    if isinstance(raw, list) and raw:
                        first = raw[0]
                        text = (
                            first.get("generated_text", "")
                            or first.get("summary_text", "")
                            or first.get("translation_text", "")
                            or str(first)
                        )
                    elif isinstance(raw, dict):
                        text = (
                            raw.get("generated_text", "") or raw.get("summary_text", "") or str(raw)
                        )
                    elif isinstance(raw, str):
                        text = raw
                    elif isinstance(raw, (list, dict)):
                        text = json.dumps(raw)[:200]

                    response_len = len(text)
                    # Basic quality: non-empty response, not just the prompt, reasonable length
                    quality = min(1.0, response_len / 100) if response_len > 10 else 0.1
                else:
                    latency_ms = int((time.time() - t0) * 1000)

            except TimeoutError:
                latency_ms = 25000
            except Exception as exc:
                latency_ms = int((time.time() - t0) * 1000)
                logger.debug("[ModelRouter] Benchmark %s/%s failed: %s", task_type, model_id, exc)

            score = ModelScore(
                model_id=model_id,
                hf_task=task_type,
                latency_ms=latency_ms,
                success=success,
                quality_score=quality,
                response_len=response_len,
                timestamp=datetime.now(UTC).isoformat(),
            )
            scores.append(score)

            # Cache individual benchmark
            try:
                cache = self._get_cache()
                safe_id = model_id.replace("/", "_")
                await cache.set(
                    BENCHMARK_KEY.format(model_id=safe_id),
                    json.dumps(asdict(score)),
                    ttl_seconds=ROUTING_TTL,
                )
            except Exception:
                pass

            logger.info(
                "[ModelRouter] %s | %s → %s | lat=%dms | score=%.2f",
                task_type,
                model_id.split("/")[-1],
                "✓" if success else "✗",
                latency_ms,
                score.composite_score(),
            )
            await asyncio.sleep(0.5)

        return scores

    # ── PERSISTENCE ──────────────────────────────────────────

    async def _save_routing_table(self) -> None:
        try:
            cache = self._get_cache()
            serialized = {k: v.to_dict() for k, v in self._routing_table.items()}
            await cache.set(
                ROUTING_TABLE_KEY,
                json.dumps(serialized, ensure_ascii=False),
                ttl_seconds=ROUTING_TTL,
            )
            logger.info("[ModelRouter] Routing table saved (%d entries)", len(serialized))
        except Exception as exc:
            logger.error("[ModelRouter] Error saving table: %s", exc)

    async def _ensure_table_loaded(self) -> None:
        if self._table_loaded:
            return
        try:
            cache = self._get_cache()
            raw = await cache.get(ROUTING_TABLE_KEY)
            if raw:
                data = json.loads(raw)
                self._routing_table = {k: RoutingEntry(**v) for k, v in data.items()}
                self._table_loaded = True
                logger.info(
                    "[ModelRouter] Routing table loaded: %d entries",
                    len(self._routing_table),
                )
        except Exception as exc:
            logger.warning(
                "[ModelRouter] Could not load table: %s — will be generated on next cycle", exc
            )
            self._table_loaded = True  # avoid retry loop

    # ── REPORT ───────────────────────────────────────────────

    async def get_discovery_report(self) -> dict:
        """Generates a report of the discovery engine's state."""
        await self._ensure_table_loaded()
        cache = self._get_cache()

        last_raw = await cache.get(LAST_DISCOVERY_KEY)
        last_disc = "Never"
        if last_raw:
            dt = datetime.fromtimestamp(float(last_raw), tz=UTC)
            last_disc = dt.strftime("%Y-%m-%d %H:%M UTC")

        top_entries = sorted(
            self._routing_table.values(),
            key=lambda e: e.composite_score,
            reverse=True,
        )[:10]

        return {
            "total_functions": len(ARIA_FUNCTION_MAP),
            "routing_entries": len(self._routing_table),
            "last_discovery": last_disc,
            "top_models": [
                {
                    "function": e.function_name,
                    "best_model": e.best_model,
                    "score": e.composite_score,
                    "task": e.hf_task,
                }
                for e in top_entries
            ],
        }


# ── SINGLETON ──────────────────────────────────────────────────
_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
