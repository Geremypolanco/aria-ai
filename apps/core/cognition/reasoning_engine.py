"""
ARIA Reasoning Engine — Chain-of-thought with iterative self-critique.

Design:
  - Every non-trivial decision passes through this engine
  - Phase 1 THINK: Generate reasoning chain (up to N steps)
  - Phase 2 CRITIQUE: Self-evaluate for logical gaps, missing data, bias
  - Phase 3 REVISE: Produce improved conclusion from critique
  - Phase 4 VERIFY: Confidence scoring + uncertainty tagging
  - Results persist in Redis for retrospective analysis and learning

This replaces ad-hoc "let me think step by step" prompting with a
structured, auditable reasoning loop that ARIA can introspect on.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("aria.reasoning")

MAX_REASONING_STEPS = 8
MAX_CRITIQUE_ROUNDS = 2
REASON_TTL = 3600 * 24  # 24 hours


@dataclass
class ReasoningStep:
    step: int
    thought: str
    evidence: list[str]  # supporting facts cited
    uncertainty: float  # 0.0 = certain, 1.0 = complete guess
    leads_to: str  # what this step concludes

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Critique:
    round: int
    issues: list[str]  # logical gaps, assumptions, missing info
    strengths: list[str]  # what the reasoning got right
    confidence_adjustment: float  # -1.0 to +1.0
    recommendation: str  # how to improve

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReasoningResult:
    id: str
    question: str
    context: dict[str, Any]
    steps: list[ReasoningStep]
    critiques: list[Critique]
    conclusion: str
    confidence: float  # 0.0 to 1.0
    uncertainty_flags: list[str]  # areas where ARIA is uncertain
    action_recommendation: str  # concrete next action
    reasoning_time_ms: int
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "context": self.context,
            "steps": [s.to_dict() for s in self.steps],
            "critiques": [c.to_dict() for c in self.critiques],
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "uncertainty_flags": self.uncertainty_flags,
            "action_recommendation": self.action_recommendation,
            "reasoning_time_ms": self.reasoning_time_ms,
            "created_at": self.created_at,
        }

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.75

    @property
    def summary(self) -> str:
        conf_label = (
            "HIGH" if self.confidence >= 0.75 else ("MEDIUM" if self.confidence >= 0.5 else "LOW")
        )
        return (
            f"[{conf_label} confidence={self.confidence:.0%}] {self.conclusion}\n"
            f"Action: {self.action_recommendation}"
        )


class ReasoningEngine:
    """
    Chain-of-thought reasoning with self-critique for ARIA.

    Usage:
        engine = ReasoningEngine(ai_client)
        result = await engine.reason(
            question="Should ARIA launch a Shopify store for AI tools?",
            context={"current_revenue": 0, "skills": ["content", "ai"]},
        )
        print(result.summary)
    """

    def __init__(self, ai_client=None) -> None:
        self._ai = ai_client
        self._history: list[ReasoningResult] = []

    def set_ai_client(self, ai_client) -> None:
        self._ai = ai_client

    # ── Main Entry Point ─────────────────────────────────────────────────

    async def reason(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        max_steps: int = MAX_REASONING_STEPS,
        critique_rounds: int = MAX_CRITIQUE_ROUNDS,
    ) -> ReasoningResult:
        """
        Full reasoning pipeline: Think → Critique → Revise → Score.
        Falls back to a single-step result if AI is unavailable.
        """
        start = time.monotonic()
        context = context or {}
        reason_id = str(uuid.uuid4())[:8]

        logger.info("[Reasoning] Starting chain-of-thought for: %s", question[:100])

        if self._ai is None:
            return self._fallback_result(reason_id, question, context, start)

        # Phase 1: Generate reasoning chain
        steps = await self._think(question, context, max_steps)

        # Phase 2: Self-critique
        critiques: list[Critique] = []
        for round_num in range(critique_rounds):
            critique = await self._critique(question, steps, round_num + 1)
            critiques.append(critique)
            if not critique.issues:
                break  # reasoning is solid — stop early

        # Phase 3: Revise conclusion incorporating critiques
        conclusion, confidence, uncertainty_flags, action = await self._revise(
            question, steps, critiques, context
        )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        result = ReasoningResult(
            id=reason_id,
            question=question,
            context=context,
            steps=steps,
            critiques=critiques,
            conclusion=conclusion,
            confidence=confidence,
            uncertainty_flags=uncertainty_flags,
            action_recommendation=action,
            reasoning_time_ms=elapsed_ms,
        )

        self._history.append(result)
        await self._persist(result)

        logger.info(
            "[Reasoning] Done in %dms — confidence=%.0f%% — %s",
            elapsed_ms,
            confidence * 100,
            conclusion[:80],
        )
        return result

    # ── Phase 1: Think ───────────────────────────────────────────────────

    async def _think(self, question: str, context: dict, max_steps: int) -> list[ReasoningStep]:
        system = (
            "You are ARIA's reasoning module. Generate a structured chain of thought.\n\n"
            "For each step, identify:\n"
            "  - The specific THOUGHT (what are you reasoning about)\n"
            "  - EVIDENCE (facts, data, or known constraints that support this step)\n"
            "  - UNCERTAINTY (0.0=certain, 1.0=pure guess)\n"
            "  - What this step LEADS TO (partial conclusion)\n\n"
            "Return JSON:\n"
            "{\n"
            '  "steps": [\n'
            "    {\n"
            '      "thought": "<the reasoning>",\n'
            '      "evidence": ["<fact1>", "<fact2>"],\n'
            '      "uncertainty": 0.2,\n'
            '      "leads_to": "<partial conclusion>"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Use 3–{max_steps} steps. Be specific — no generic reasoning. "
            "Cite actual facts from the context or acknowledged gaps."
        )

        user_msg = (
            f"Question: {question}\n\n" f"Context: {json.dumps(context, ensure_ascii=False)[:3000]}"
        )

        try:
            raw = await self._ai.complete_json(system=system, user=user_msg)
            raw_steps = raw.get("steps", [])[:max_steps]
            return [
                ReasoningStep(
                    step=i,
                    thought=s.get("thought", ""),
                    evidence=s.get("evidence", []),
                    uncertainty=float(s.get("uncertainty", 0.5)),
                    leads_to=s.get("leads_to", ""),
                )
                for i, s in enumerate(raw_steps)
            ]
        except Exception as exc:
            logger.warning("[Reasoning] Think phase failed: %s", exc)
            return [
                ReasoningStep(
                    step=0,
                    thought=f"Unable to complete full reasoning chain: {exc}",
                    evidence=[],
                    uncertainty=0.9,
                    leads_to="Reasoning degraded — low confidence conclusion",
                )
            ]

    # ── Phase 2: Critique ────────────────────────────────────────────────

    async def _critique(
        self, question: str, steps: list[ReasoningStep], round_num: int
    ) -> Critique:
        chain_text = "\n".join(
            f"Step {s.step}: {s.thought} → {s.leads_to} (uncertainty={s.uncertainty:.0%})"
            for s in steps
        )

        system = (
            "You are ARIA's self-critique module. Evaluate a reasoning chain for:\n"
            "  - Logical gaps or non-sequiturs\n"
            "  - Unwarranted assumptions stated as facts\n"
            "  - Missing important considerations\n"
            "  - Bias or one-sided analysis\n"
            "  - Conclusions that don't follow from the steps\n\n"
            "Be ruthless but fair. Also note what the reasoning got right.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "issues": ["<issue1>", "<issue2>"],\n'
            '  "strengths": ["<strength1>"],\n'
            '  "confidence_adjustment": -0.1,\n'
            '  "recommendation": "<how to improve>"\n'
            "}"
        )

        user_msg = (
            f"Question being reasoned about: {question}\n\n"
            f"Reasoning chain (round {round_num}):\n{chain_text}"
        )

        try:
            raw = await self._ai.complete_json(system=system, user=user_msg)
            return Critique(
                round=round_num,
                issues=raw.get("issues", []),
                strengths=raw.get("strengths", []),
                confidence_adjustment=float(raw.get("confidence_adjustment", 0.0)),
                recommendation=raw.get("recommendation", ""),
            )
        except Exception as exc:
            logger.warning("[Reasoning] Critique phase failed: %s", exc)
            return Critique(
                round=round_num,
                issues=[],
                strengths=["Critique unavailable"],
                confidence_adjustment=0.0,
                recommendation="",
            )

    # ── Phase 3: Revise and Score ────────────────────────────────────────

    async def _revise(
        self,
        question: str,
        steps: list[ReasoningStep],
        critiques: list[Critique],
        context: dict,
    ) -> tuple[str, float, list[str], str]:
        chain_text = "\n".join(f"Step {s.step}: {s.thought}" for s in steps)
        critique_text = "\n".join(
            f"Round {c.round}: Issues={c.issues} | Recommendation={c.recommendation}"
            for c in critiques
        )

        # Base confidence from step uncertainties
        if steps:
            avg_uncertainty = sum(s.uncertainty for s in steps) / len(steps)
            base_confidence = 1.0 - avg_uncertainty
        else:
            base_confidence = 0.3

        # Apply critique adjustments
        for c in critiques:
            base_confidence = max(0.05, min(0.99, base_confidence + c.confidence_adjustment))

        system = (
            "You are ARIA's synthesis module. Given a reasoning chain and its self-critique, "
            "produce the best possible conclusion.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "conclusion": "<clear, actionable conclusion — 1-2 sentences>",\n'
            '  "uncertainty_flags": ["<area where you are uncertain>"],\n'
            '  "action": "<the single most important next action ARIA should take>",\n'
            '  "confidence_delta": 0.05\n'
            "}\n\n"
            "The conclusion must directly answer the original question. "
            "The action must be concrete and immediately executable. "
            "uncertainty_flags: list the 1-3 most important things ARIA doesn't know."
        )

        user_msg = (
            f"Original question: {question}\n\n"
            f"Reasoning chain:\n{chain_text}\n\n"
            f"Self-critique:\n{critique_text}\n\n"
            f"Context: {json.dumps(context, ensure_ascii=False)[:1000]}"
        )

        try:
            raw = await self._ai.complete_json(system=system, user=user_msg)
            delta = float(raw.get("confidence_delta", 0.0))
            final_confidence = max(0.05, min(0.99, base_confidence + delta))
            return (
                raw.get("conclusion", "Unable to synthesize conclusion."),
                final_confidence,
                raw.get("uncertainty_flags", []),
                raw.get("action", "Gather more information before proceeding."),
            )
        except Exception as exc:
            logger.warning("[Reasoning] Revision phase failed: %s", exc)
            last_step = steps[-1] if steps else None
            return (
                last_step.leads_to if last_step else "Reasoning engine degraded.",
                base_confidence * 0.7,
                ["AI synthesis unavailable"],
                "Retry with more context.",
            )

    # ── Fallback ─────────────────────────────────────────────────────────

    def _fallback_result(
        self, reason_id: str, question: str, context: dict, start: float
    ) -> ReasoningResult:
        return ReasoningResult(
            id=reason_id,
            question=question,
            context=context,
            steps=[
                ReasoningStep(
                    step=0,
                    thought="AI client not available — cannot reason.",
                    evidence=[],
                    uncertainty=1.0,
                    leads_to="No conclusion available",
                )
            ],
            critiques=[],
            conclusion="AI client unavailable. Cannot reason about this question.",
            confidence=0.0,
            uncertainty_flags=["AI client not configured"],
            action_recommendation="Configure AI client and retry.",
            reasoning_time_ms=int((time.monotonic() - start) * 1000),
        )

    # ── Persistence ──────────────────────────────────────────────────────

    async def _persist(self, result: ReasoningResult) -> None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                key = f"aria:reasoning:{result.id}"
                await cache.set(key, json.dumps(result.to_dict()), ttl_seconds=REASON_TTL)
                # Maintain index of recent reasoning IDs
                await cache.rpush("aria:reasoning:index", result.id)
        except Exception as exc:
            logger.debug("[Reasoning] Could not persist result %s: %s", result.id, exc)

    async def get_history(self, limit: int = 10) -> list[dict]:
        return [r.to_dict() for r in self._history[-limit:]]

    async def load_from_redis(self, reason_id: str) -> ReasoningResult | None:
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                raw = await cache.get(f"aria:reasoning:{reason_id}")
                if raw:
                    d = json.loads(raw)
                    steps = [ReasoningStep(**s) for s in d.get("steps", [])]
                    critiques = [Critique(**c) for c in d.get("critiques", [])]
                    return ReasoningResult(
                        id=d["id"],
                        question=d["question"],
                        context=d.get("context", {}),
                        steps=steps,
                        critiques=critiques,
                        conclusion=d["conclusion"],
                        confidence=d["confidence"],
                        uncertainty_flags=d.get("uncertainty_flags", []),
                        action_recommendation=d["action_recommendation"],
                        reasoning_time_ms=d["reasoning_time_ms"],
                        created_at=d["created_at"],
                    )
        except Exception as exc:
            logger.debug("[Reasoning] Could not load result %s: %s", reason_id, exc)
        return None


_engine: ReasoningEngine | None = None


def get_reasoning_engine(ai_client=None) -> ReasoningEngine:
    global _engine
    if _engine is None:
        _engine = ReasoningEngine(ai_client)
    elif ai_client is not None and _engine._ai is None:
        _engine.set_ai_client(ai_client)
    return _engine
