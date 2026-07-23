"""
AuditorAgent — Elite auditor for ARIA AI.

Acts as a senior Google/Anthropic tech lead: judicious, direct, no sugarcoating.
Detects errors, logical gaps, and quality issues BEFORE they reach production.
Always responds in structured JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.auditor_agent")

_SYSTEM_PROMPT = (
    "You are ARIA AI's elite auditor. You act as a senior Google/Anthropic tech lead: "
    "judicious, direct, no sugarcoating. Your job is to detect errors, logical gaps, and "
    "quality issues BEFORE they reach production. "
    "You always respond in structured JSON."
)


@dataclass
class AuditIssue:
    severity: str  # "critical" | "high" | "medium" | "low"
    category: str  # e.g. "security", "logic", "performance", "completeness"
    description: str
    fix: str


@dataclass
class AuditResult:
    score: int  # 0-100
    passed: bool
    verdict: str  # "PASS" | "WARN" | "FAIL"
    issues: list[AuditIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "passed": self.passed,
            "verdict": self.verdict,
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "description": i.description,
                    "fix": i.fix,
                }
                for i in self.issues
            ],
            "suggestions": self.suggestions,
            "reasoning": self.reasoning,
        }


class AuditorAgent(BaseAgent):
    """
    Auditor agent that reviews plans, outputs, and code before they reach production.
    Brutally honest. No sugar-coating.
    """

    def __init__(self) -> None:
        super().__init__(
            name="auditor",
            description="Elite auditor — reviews plans, outputs, and code with senior tech lead judgment",
            capabilities=[
                "plan_audit",
                "output_audit",
                "code_audit",
                "quality_assurance",
                "risk_detection",
            ],
        )

    # ── AUDIT METHODS ─────────────────────────────────────

    async def audit_plan(self, plan: str, mission: str) -> AuditResult:
        """
        Reviews a plan before execution.
        Detects: logical gaps, missing steps, unrealistic assumptions, security risks.
        """
        user_prompt = (
            f"MISSION: {mission}\n\n"
            f"PLAN TO AUDIT:\n{plan}\n\n"
            "Audit this plan with senior tech lead judgment. Look for:\n"
            "1. Logical gaps or missing steps\n"
            "2. Unverified or unrealistic assumptions\n"
            "3. Security or data risks\n"
            "4. Undeclared dependencies\n"
            "5. Unrealistic estimates\n\n"
            "Respond ONLY with JSON (no markdown, no extra text):\n"
            '{"score": <0-100>, "issues": [{"severity": "critical|high|medium|low", '
            '"category": "...", "description": "...", "fix": "..."}], '
            '"suggestions": ["..."], "reasoning": "..."}'
        )
        response = await self.think(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        return self._parse_audit_response(response or "", context_type="plan")

    async def audit_output(
        self,
        output: Any,
        mission: str,
        original_plan: str = "",
    ) -> AuditResult:
        """
        Reviews completed work.
        Detects: incomplete tasks, low quality, inaccuracies, missing parts.
        """
        output_str = (
            json.dumps(output, ensure_ascii=False, default=str)
            if not isinstance(output, str)
            else output
        )
        plan_section = f"\nORIGINAL PLAN:\n{original_plan}\n" if original_plan else ""

        user_prompt = (
            f"MISSION: {mission}\n"
            f"{plan_section}\n"
            f"COMPLETED OUTPUT:\n{output_str}\n\n"
            "Audit this output with senior tech lead judgment. Evaluate:\n"
            "1. Was the task completed 100%?\n"
            "2. Is the quality sufficient for production?\n"
            "3. Are there inaccuracies or incorrect data?\n"
            "4. Are critical parts missing?\n"
            "5. What would significantly improve the result?\n\n"
            "Respond ONLY with JSON (no markdown, no extra text):\n"
            '{"score": <0-100>, "issues": [{"severity": "critical|high|medium|low", '
            '"category": "...", "description": "...", "fix": "..."}], '
            '"suggestions": ["..."], "reasoning": "..."}'
        )
        response = await self.think(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            model=AIModel.STRATEGY,
            json_mode=True,
        )
        return self._parse_audit_response(response or "", context_type="output")

    async def audit_code(
        self,
        code: str,
        language: str,
        requirements: str = "",
    ) -> AuditResult:
        """
        Reviews code specifically.
        Detects: bugs, security holes, performance issues, missing error handling.
        """
        req_section = f"\nREQUIREMENTS:\n{requirements}\n" if requirements else ""

        user_prompt = (
            f"LANGUAGE: {language}\n"
            f"{req_section}\n"
            f"CODE TO AUDIT:\n```{language}\n{code}\n```\n\n"
            "Audit this code as a senior Google tech lead. Look for:\n"
            "1. Logical or runtime bugs\n"
            "2. Security vulnerabilities (injection, authentication, data exposure)\n"
            "3. Performance issues (N+1, unnecessary loops, blocking calls)\n"
            "4. Missing or insufficient error handling\n"
            "5. Violations of SOLID / DRY / KISS principles\n\n"
            "Respond ONLY with JSON (no markdown, no extra text):\n"
            '{"score": <0-100>, "issues": [{"severity": "critical|high|medium|low", '
            '"category": "...", "description": "...", "fix": "..."}], '
            '"suggestions": ["..."], "reasoning": "..."}'
        )
        response = await self.think(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            model=AIModel.CODE,
            json_mode=True,
        )
        return self._parse_audit_response(response or "", context_type="code")

    # ── PARSING ───────────────────────────────────────────

    def _parse_audit_response(self, response: str, context_type: str) -> AuditResult:
        """
        Parses the AI response into a structured AuditResult.
        Falls back to WARN with score=60 if the JSON is invalid.
        """
        try:
            # Strip markdown code fences if present
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                cleaned = "\n".join(line for line in lines if not line.startswith("```")).strip()

            data = json.loads(cleaned)

            score = int(data.get("score", 60))
            score = max(0, min(100, score))  # clamp to [0, 100]

            issues: list[AuditIssue] = []
            for raw_issue in data.get("issues", []):
                issues.append(
                    AuditIssue(
                        severity=str(raw_issue.get("severity", "medium")),
                        category=str(raw_issue.get("category", context_type)),
                        description=str(raw_issue.get("description", "")),
                        fix=str(raw_issue.get("fix", "")),
                    )
                )

            suggestions = [str(s) for s in data.get("suggestions", [])]
            reasoning = str(data.get("reasoning", ""))

            # Determine verdict from score
            if score >= 80:
                verdict = "PASS"
                passed = True
            elif score >= 50:
                verdict = "WARN"
                passed = True
            else:
                verdict = "FAIL"
                passed = False

            return AuditResult(
                score=score,
                passed=passed,
                verdict=verdict,
                issues=issues,
                suggestions=suggestions,
                reasoning=reasoning,
            )

        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            logger.warning(
                "[AuditorAgent] Could not parse audit response (%s): %s",
                context_type,
                exc,
            )
            return AuditResult(
                score=60,
                passed=True,
                verdict="WARN",
                issues=[
                    AuditIssue(
                        severity="medium",
                        category="parse_error",
                        description=f"Could not parse the auditor response for '{context_type}'.",
                        fix="Manually review the output.",
                    )
                ],
                suggestions=["Manually review the auditor's raw response."],
                reasoning=f"Parse error — raw response: {response[:200]}",
            )

    # ── EXECUTE ───────────────────────────────────────────

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Generic entry point.
        - If the context contains 'output' → audit_output
        - If the context contains 'code' → audit_code
        - Otherwise → audit_plan
        """
        mission = context.get("mission", "")

        if "code" in context:
            language = context.get("language", "python")
            requirements = context.get("requirements", "")
            result = await self.audit_code(
                code=context["code"],
                language=language,
                requirements=requirements,
            )
        elif "output" in context:
            original_plan = context.get("plan", "")
            result = await self.audit_output(
                output=context["output"],
                mission=mission,
                original_plan=original_plan,
            )
        else:
            plan = context.get("plan", "")
            result = await self.audit_plan(plan=plan, mission=mission)

        return {
            "success": True,
            "agent": self.name,
            "audit": result.to_dict(),
        }
