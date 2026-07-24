"""
reflection_engine.py — ARIA AI's real reflection engine.

ARIA analyzes its own failures, adapts its behavior, and improves its future decisions.
No simulation. Uses real Fly.io logs + task history + skill scores.

Cycle:
  1. Gather evidence: error logs, failed tasks, weak skills
  2. Analyze with HuggingFace (Qwen2.5-72B) what went wrong and why
  3. Generate concrete improvement decisions
  4. Persist the decisions in Redis/Supabase
  5. Agents consult these decisions before executing
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.reflection")


class ReflectionEngine:
    """
    ARIA's reflection and adaptation engine.
    Detects failure patterns and generates concrete improvement strategies.
    """

    # Minimum interval between reflections (sec)
    MIN_REFLECTION_INTERVAL = 900  # 15 min

    def __init__(self) -> None:
        self._last_reflection = 0.0
        self._decisions: list[dict] = []
        self._reflection_history: list[dict] = []

    # ── MAIN REFLECTION ─────────────────────────────────────────

    async def reflect(self, context: dict = None) -> dict[str, Any]:
        """
        Full reflection cycle. Analyzes the current state and generates improvements.
        """
        now = time.time()
        if now - self._last_reflection < self.MIN_REFLECTION_INTERVAL:
            remaining = int(self.MIN_REFLECTION_INTERVAL - (now - self._last_reflection))
            return {
                "skipped": True,
                "reason": f"Next reflection in {remaining}s",
                "decisions": self._decisions,
            }

        self._last_reflection = now
        logger.info("[Reflection] Starting reflection cycle...")

        evidence = await self._gather_evidence(context or {})
        if not evidence.get("has_issues"):
            return {
                "reflected": True,
                "issues": 0,
                "decisions": [],
                "message": "System healthy — no changes needed",
            }

        decisions = await self._analyze_and_decide(evidence)
        self._decisions = decisions
        await self._persist_decisions(decisions)

        reflection = {
            "reflected": True,
            "timestamp": datetime.now(UTC).isoformat(),
            "issues_found": len(evidence.get("issues", [])),
            "decisions": decisions,
            "evidence_summary": {
                "failed_tasks": len(evidence.get("failed_tasks", [])),
                "weak_skills": evidence.get("weak_skills", []),
                "error_patterns": evidence.get("error_patterns", []),
            },
        }

        self._reflection_history.append(reflection)
        if len(self._reflection_history) > 50:
            self._reflection_history = self._reflection_history[-50:]

        logger.info("[Reflection] Cycle complete: %d decisions generated", len(decisions))
        return reflection

    # ── EVIDENCE GATHERING ──────────────────────────────────────

    async def _gather_evidence(self, context: dict) -> dict[str, Any]:
        evidence = {"issues": [], "has_issues": False}

        # 1. Trainer skill scores
        try:
            from apps.core.training.continuous_trainer import get_trainer

            trainer = get_trainer()
            status = trainer.get_status()
            weak_skills = [k for k, v in status.get("skill_scores", {}).items() if v < 50]
            if weak_skills:
                evidence["weak_skills"] = weak_skills
                evidence["issues"].append(f"Weak skills: {', '.join(weak_skills)}")
        except Exception as exc:
            logger.debug("[Reflection] Could not get skill scores: %s", exc)

        # 2. Failed tasks from WorldState
        try:
            from apps.core.cognition.world_state import get_world_state

            ws = get_world_state()
            failed = ws.get_failed_tasks()
            if failed:
                evidence["failed_tasks"] = failed[-10:]
                evidence["issues"].append(f"{len(failed)} failed tasks in world state")
        except Exception:
            evidence["failed_tasks"] = []

        # 3. Negative experiences from the trainer
        try:
            from apps.core.training.continuous_trainer import get_trainer

            trainer = get_trainer()
            errors = [
                e for e in trainer._experiences if e.get("type") in ("training_error", "env_issue")
            ]
            if errors:
                patterns = list({e.get("error", "")[:50] for e in errors[-20:] if e.get("error")})
                evidence["error_patterns"] = patterns[:5]
                evidence["issues"].append(f"{len(errors)} recent training errors")
        except Exception:
            pass

        # 4. Fly.io logs
        try:
            from apps.core.training.environment_monitor import get_env_monitor

            monitor = get_env_monitor()
            snapshot = await monitor.get_cached_snapshot()
            fly_issues = snapshot.get("critical_issues", [])
            if fly_issues:
                evidence["fly_issues"] = fly_issues
                evidence["issues"].extend(fly_issues)
        except Exception:
            pass

        evidence["has_issues"] = len(evidence["issues"]) > 0
        return evidence

    # ── ANALYSIS AND DECISIONS ──────────────────────────────────

    async def _analyze_and_decide(self, evidence: dict) -> list[dict]:
        """Uses HuggingFace to analyze the issues and generate concrete decisions."""
        issues_text = "\n".join(f"- {i}" for i in evidence.get("issues", []))
        weak = evidence.get("weak_skills", [])
        errors = evidence.get("error_patterns", [])

        prompt = f"""You are ARIA AI's reflection system. Analyze these issues and generate CONCRETE improvement decisions.

CURRENT ISSUES:
{issues_text}

WEAK SKILLS (score <50%): {', '.join(weak) if weak else 'none'}
RECENT ERROR PATTERNS: {', '.join(errors[:3]) if errors else 'none'}

Generate 3-5 specific decisions to improve the system. Each decision must be:
- Actionable (can be implemented in code)
- Specific (not vague)
- Prioritized (most critical first)

Format each decision as:
DECISION: [what to do]
PRIORITY: [high/medium/low]
TARGET: [which component to fix]
REASON: [why this matters]
---"""

        decisions = []
        try:
            from apps.core.tools.ai_client import AIModel, get_ai_client

            client = get_ai_client()
            response = await client.complete(
                system="You are ARIA AI's reflection system, analyzing failures to generate concrete improvement decisions.",
                user=prompt,
                model=AIModel.STRATEGY,
                max_tokens=600,
            )

            if response and response.success and response.content:
                blocks = response.content.split("---")
                for block in blocks:
                    if "DECISION:" not in block:
                        continue
                    lines = block.strip().split("\n")
                    d = {}
                    for line in lines:
                        for key in ("DECISION", "PRIORITY", "TARGET", "REASON"):
                            if line.startswith(f"{key}:"):
                                d[key.lower()] = line.split(":", 1)[1].strip()
                    if d.get("decision"):
                        decisions.append(
                            {
                                **d,
                                "created_at": datetime.now(UTC).isoformat(),
                                "applied": False,
                            }
                        )
        except Exception as exc:
            logger.error("[Reflection] AI analysis failed: %s", exc)
            # Fallback: generate rule-based decisions
            if weak:
                for skill in weak[:3]:
                    decisions.append(
                        {
                            "decision": f"Investigate and fix {skill} — currently scoring <50%",
                            "priority": "high",
                            "target": skill,
                            "reason": "Skill score below acceptable threshold",
                            "created_at": datetime.now(UTC).isoformat(),
                            "applied": False,
                        }
                    )

        return decisions

    # ── PERSISTENCE ──────────────────────────────────────────────

    async def _persist_decisions(self, decisions: list[dict]) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache and decisions:
                # ttl_seconds belongs on cache.set(), not json.dumps() — the
                # old call raised TypeError on every invocation, so decisions
                # were never actually persisted (silently swallowed below).
                await cache.set(
                    "aria:reflection:decisions", json.dumps(decisions), ttl_seconds=86400
                )
        except Exception as exc:
            logger.warning("[Reflection] Redis persist failed: %s", exc)

    async def load_decisions(self) -> list[dict]:
        """Loads reflection decisions from Redis (so agents can consult them)."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                raw = await cache.get("aria:reflection:decisions")
                if raw:
                    # cache.get() already deserializes JSON.
                    return raw
        except Exception:
            pass
        return self._decisions

    def get_status(self) -> dict:
        return {
            "last_reflection": (
                datetime.fromtimestamp(self._last_reflection, tz=UTC).isoformat()
                if self._last_reflection
                else None
            ),
            "active_decisions": len(self._decisions),
            "reflection_count": len(self._reflection_history),
            "pending_decisions": [d for d in self._decisions if not d.get("applied")],
        }


_reflection_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
    return _reflection_engine
