"""
deep_think.py — Extended reasoning for ARIA AI.

Inspired by Claude 3.7 Sonnet "Hybrid Reasoning":
  - Standard mode: fast response with no visible thinking
  - Thinking mode: step-by-step thinking with a token budget (up to 128K)
  - Ultra mode: maximum budget, for high-complexity problems

ARIA uses deep_think for:
  - Complex strategic analysis
  - Debugging difficult problems
  - Business decisions with multiple variables
  - Research requiring deep synthesis
  - Planning large projects
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("aria.deep_think")


@dataclass
class ThinkingResult:
    answer: str
    thinking_trace: str | None
    thinking_tokens: int
    total_tokens: int
    duration_ms: int
    model_used: str
    depth: str  # fast | standard | deep | ultra

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "model": self.model_used,
            "depth": self.depth,
            "has_trace": bool(self.thinking_trace),
        }


class DeepThink:
    """
    Extended reasoning engine for ARIA.
    Automatically selects the thinking level based on detected complexity.
    """

    # Thinking token budgets (similar to Claude 3.7)
    BUDGETS = {
        "fast": 0,  # No explicit thinking
        "standard": 2000,  # Brief thinking
        "deep": 8000,  # Deep thinking
        "ultra": 32000,  # Maximum reasoning
    }

    # Keywords indicating deep thinking is needed
    # NOTE: intentionally bilingual (English + Spanish) — this list matches
    # against free-text questions a caller may ask in either language, so
    # do not translate the keyword values themselves.
    DEEP_TRIGGERS = [
        "estrategia",
        "strategy",
        "analiza",
        "analyze",
        "evalúa",
        "evaluate",
        "decide",
        "decisión",
        "decision",
        "complejo",
        "complex",
        "optimiza",
        "optimize",
        "diseña arquitectura",
        "arquitectura",
        "architecture",
        "por qué",
        "why",
        "cómo debería",
        "how should",
        "mejor forma",
        "trade-off",
        "trade off",
        "compara",
        "compare",
        "prioriza",
        "planifica",
        "roadmap",
        "debug difícil",
        "razona",
        "think through",
        "investiga a fondo",
        "analiza en profundidad",
        "deep dive",
    ]

    async def think(
        self,
        question: str,
        context: str = "",
        depth: str = "auto",
        system: str = "",
        show_trace: bool = False,
    ) -> ThinkingResult:
        """
        Reasons about a question at the appropriate depth level.

        depth: "auto" detects automatically, "fast"|"standard"|"deep"|"ultra" forces a level.
        show_trace: includes the reasoning process in the response.
        """
        t0 = time.monotonic()

        if depth == "auto":
            depth = self._detect_depth(question)

        budget = self.BUDGETS.get(depth, 0)

        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()

        sys_prompt = system or (
            "You are ARIA, an autonomous business AI with advanced reasoning capabilities. "
            "You think in a structured way: first you understand the problem, consider multiple angles, "
            "evaluate trade-offs, and then formulate a complete, actionable response. "
            "You are direct, honest, and avoid generic answers."
        )

        full_prompt = question
        if context:
            full_prompt = f"Context:\n{context}\n\nQuestion: {question}"

        if budget > 0:
            # Extended thinking: prepend thinking instruction
            thinking_instruction = (
                f"\n\n<thinking_mode>Use step-by-step reasoning before answering. "
                f"Think out loud about: the central problem, key considerations, "
                f"possible approaches, trade-offs, and your final conclusion. "
                f"Maximum {budget} thinking tokens.</thinking_mode>"
            )
            full_prompt = full_prompt + thinking_instruction
            model = AIModel.STRATEGY
        else:
            model = AIModel.FAST

        response = await client.complete(
            model=model,
            system=sys_prompt,
            user=full_prompt,
            max_tokens=min(4096, budget + 2000) if budget > 0 else 2000,
        )

        duration_ms = int((time.monotonic() - t0) * 1000)

        # Extract thinking trace if present
        thinking_trace = None
        answer = (response.content if hasattr(response, "content") else str(response)) or ""

        if budget > 0 and "<think>" in answer:
            import re

            trace_m = re.search(r"<think>(.*?)</think>", answer, re.DOTALL)
            if trace_m:
                thinking_trace = trace_m.group(1).strip()
                answer = answer.replace(trace_m.group(0), "").strip()

        # Estimate token counts
        thinking_tokens = len((thinking_trace or "").split()) * 4 // 3
        total_tokens = len(answer.split()) * 4 // 3 + thinking_tokens

        logger.info(
            "[DeepThink] depth=%s budget=%d duration=%dms ~%d tokens",
            depth,
            budget,
            duration_ms,
            total_tokens,
        )

        return ThinkingResult(
            answer=answer,
            thinking_trace=thinking_trace if show_trace else None,
            thinking_tokens=thinking_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            model_used=model.value if hasattr(model, "value") else str(model),
            depth=depth,
        )

    async def think_and_plan(
        self, objective: str, context: str = "", constraints: list[str] = None
    ) -> dict[str, Any]:
        """
        Structured reasoning for project planning.
        Returns a detailed plan with phases, resources, and risks.
        """
        constraints_text = "\n".join(f"- {c}" for c in (constraints or []))
        prompt = (
            f"Objective: {objective}\n"
            + (f"Constraints:\n{constraints_text}\n" if constraints_text else "")
            + "\nCreate a detailed execution plan with:\n"
            "1. Analysis of the current situation\n"
            "2. Implementation phases (with estimated duration)\n"
            "3. Necessary resources\n"
            "4. Risks and mitigations\n"
            "5. Success KPIs\n"
            "6. Next 3 immediate steps\n"
        )

        result = await self.think(prompt, context=context, depth="deep")
        return {
            "plan": result.answer,
            "thinking_depth": result.depth,
            "duration_ms": result.duration_ms,
        }

    async def analyze_decision(
        self,
        question: str,
        options: list[str],
        criteria: list[str] = None,
    ) -> dict[str, Any]:
        """
        Structured decision framework with multi-criteria analysis.
        Like a McKinsey consultant thinking out loud.
        """
        options_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
        criteria_text = "\n".join(
            f"  - {c}" for c in (criteria or ["impact", "effort", "risk", "cost"])
        )

        prompt = (
            f"Decision to make: {question}\n\n"
            f"Options:\n{options_text}\n\n"
            f"Evaluation criteria:\n{criteria_text}\n\n"
            "Analyze each option against the criteria, identify the best decision, "
            "and justify it with solid reasoning. Be direct about which one you recommend."
        )

        result = await self.think(prompt, depth="deep")
        return {
            "recommendation": result.answer,
            "depth": result.depth,
            "duration_ms": result.duration_ms,
        }

    async def debug_problem(
        self,
        problem: str,
        context: str = "",
        error_trace: str = "",
    ) -> dict[str, Any]:
        """
        Deep debugging — thinks like a senior engineer with 20 years of experience.
        """
        prompt = (
            f"Problem: {problem}\n"
            + (f"Error:\n```\n{error_trace}\n```\n" if error_trace else "")
            + (f"Context: {context}\n" if context else "")
            + "\nDiagnose the root cause, explain why it occurs, "
            "and provide the exact solution with code if applicable."
        )

        result = await self.think(
            prompt,
            depth="deep",
            system=(
                "You are a senior engineer with 20 years of experience. "
                "You diagnose problems methodically: symptoms → root cause → solution. "
                "You never give vague answers. Always provide runnable code when applicable."
            ),
        )
        return {
            "diagnosis": result.answer,
            "depth": result.depth,
            "duration_ms": result.duration_ms,
        }

    async def think_verified(
        self,
        question: str,
        context: str = "",
        paths: int = 2,
        system: str = "",
    ) -> ThinkingResult:
        """
        Test-Time Compute: generates `paths` independent answers in parallel,
        self-evaluates them with an internal judge, and returns the best one.
        Inspired by GPT-5 / Claude 4.5 inference-time scaling.
        """
        import time as _time

        t0 = _time.monotonic()

        # Generate N candidate answers in parallel
        tasks = [
            self.think(question, context=context, depth="deep", system=system) for _ in range(paths)
        ]
        candidates: list[ThinkingResult] = await asyncio.gather(*tasks, return_exceptions=True)
        candidates = [r for r in candidates if isinstance(r, ThinkingResult) and r.answer]

        if not candidates:
            return await self.think(question, context=context, depth="deep", system=system)
        if len(candidates) == 1:
            return candidates[0]

        # Self-evaluation: ask the model to pick the best answer
        from apps.core.tools.ai_client import AIModel, get_ai_client

        client = get_ai_client()
        eval_prompt = (
            f"Original question: {question}\n\n"
            + "\n\n".join(f"ANSWER {i+1}:\n{c.answer[:1500]}" for i, c in enumerate(candidates))
            + "\n\nEvaluate each answer on: accuracy, completeness, and practical usefulness. "
            "Respond with ONLY the number of the best answer (1, 2, etc.) and a brief justification."
        )
        eval_resp = await client.complete(
            model=AIModel.FAST,
            system="You are a critical judge who evaluates the quality of AI answers.",
            user=eval_prompt,
            max_tokens=200,
        )
        eval_text = eval_resp.content if hasattr(eval_resp, "content") else ""

        # Parse choice
        import re

        m = re.search(r"\b([1-9])\b", eval_text or "")
        chosen_idx = (int(m.group(1)) - 1) if m and int(m.group(1)) <= len(candidates) else 0
        best = candidates[chosen_idx]

        logger.info(
            "[DeepThink/verified] paths=%d chosen=%d duration=%dms",
            paths,
            chosen_idx + 1,
            int((_time.monotonic() - t0) * 1000),
        )
        return best

    def _detect_depth(self, question: str) -> str:
        """Automatically detects the required thinking level."""
        q_lower = question.lower()
        word_count = len(question.split())

        # Very long or complex questions → deep
        if word_count > 50:
            return "deep"

        # High-complexity keywords → deep
        deep_count = sum(1 for kw in self.DEEP_TRIGGERS if kw in q_lower)
        if deep_count >= 2:
            return "deep"
        if deep_count == 1:
            return "standard"

        # Short, simple questions → fast
        return "fast"


# ══════════════════════════════════════════════════════════════
# PROGRESS STREAMING — Manus-style progress updates
# ══════════════════════════════════════════════════════════════


class ProgressStream:
    """
    Streams real-time progress updates during long tasks.
    Inspired by the Manus `message` tool — agent-to-user updates.
    """

    def __init__(self, session_id: str, task_name: str) -> None:
        self.session_id = session_id
        self.task_name = task_name
        self._steps: list[dict] = []

    async def update(self, step: str, detail: str = "", icon: str = "⚡") -> None:
        """Sends a progress update to the user."""
        entry = {"step": step, "detail": detail, "icon": icon}
        self._steps.append(entry)
        logger.info("[Progress:%s] %s %s", self.task_name, icon, step)

        # Send to Telegram if the session is a Telegram session
        if self.session_id.startswith("telegram:"):
            chat_id = self.session_id.replace("telegram:", "")
            if chat_id.isdigit():
                try:
                    from apps.core.tools.telegram_bot import get_bot

                    msg = f"{icon} **{step}**" + (f"\n_{detail}_" if detail else "")
                    await get_bot()._send_message(int(chat_id), msg)
                except Exception:
                    pass

        # Push to WebSocket activity log
        try:
            from apps.core.routes.api import _log_activity

            _log_activity("INFO", f"[{self.task_name}] {step}", category="progress")
        except Exception:
            pass

    async def complete(self, message: str = "") -> None:
        await self.update(message or f"{self.task_name} completed", icon="✅")

    async def error(self, message: str) -> None:
        await self.update(f"Error: {message}", icon="❌")

    def get_steps(self) -> list[dict]:
        return list(self._steps)


# Singleton
_deep_think: DeepThink | None = None


def get_deep_think() -> DeepThink:
    global _deep_think
    if _deep_think is None:
        _deep_think = DeepThink()
    return _deep_think
