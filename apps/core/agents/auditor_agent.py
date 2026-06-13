"""
AuditorAgent — Auditor de élite para ARIA AI.

Actúa como tech lead senior de Google/Anthropic: criterioso, directo, sin contemplaciones.
Detecta errores, gaps lógicos y problemas de calidad ANTES de que lleguen a producción.
Siempre responde en JSON estructurado.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.core.agents.base_agent import BaseAgent
from apps.core.tools.ai_client import AIModel

logger = logging.getLogger("aria.auditor_agent")

_SYSTEM_PROMPT = (
    "Eres el auditor de élite de ARIA AI. Actúas como tech lead senior de Google/Anthropic: "
    "criterioso, directo, sin contemplaciones. Tu trabajo es detectar errores, gaps lógicos y "
    "problemas de calidad ANTES de que lleguen a producción. "
    "Siempre respondes en JSON estructurado."
)


@dataclass
class AuditIssue:
    severity: str   # "critical" | "high" | "medium" | "low"
    category: str   # e.g. "security", "logic", "performance", "completeness"
    description: str
    fix: str


@dataclass
class AuditResult:
    score: int                              # 0-100
    passed: bool
    verdict: str                            # "PASS" | "WARN" | "FAIL"
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
    Agente auditor que revisa planes, outputs y código antes de que lleguen a producción.
    Brutalmente honesto. Sin sugar-coating.
    """

    def __init__(self) -> None:
        super().__init__(
            name="auditor",
            description="Auditor de élite — revisa planes, outputs y código con criterio de tech lead senior",
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
        Revisa un plan antes de su ejecución.
        Detecta: gaps lógicos, pasos faltantes, suposiciones irreales, riesgos de seguridad.
        """
        user_prompt = (
            f"MISIÓN: {mission}\n\n"
            f"PLAN A AUDITAR:\n{plan}\n\n"
            "Audita este plan con criterio de tech lead senior. Busca:\n"
            "1. Gaps lógicos o pasos faltantes\n"
            "2. Suposiciones no verificadas o irreales\n"
            "3. Riesgos de seguridad o datos\n"
            "4. Dependencias no declaradas\n"
            "5. Estimaciones poco realistas\n\n"
            "Responde ÚNICAMENTE con JSON (sin markdown, sin texto extra):\n"
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
        Revisa trabajo completado.
        Detecta: tarea incompleta, baja calidad, imprecisiones, partes faltantes.
        """
        output_str = json.dumps(output, ensure_ascii=False, default=str) if not isinstance(output, str) else output
        plan_section = f"\nPLAN ORIGINAL:\n{original_plan}\n" if original_plan else ""

        user_prompt = (
            f"MISIÓN: {mission}\n"
            f"{plan_section}\n"
            f"OUTPUT COMPLETADO:\n{output_str}\n\n"
            "Audita este output con criterio de tech lead senior. Evalúa:\n"
            "1. ¿Se completó la tarea al 100%?\n"
            "2. ¿La calidad es suficiente para producción?\n"
            "3. ¿Hay imprecisiones o datos incorrectos?\n"
            "4. ¿Faltan partes críticas?\n"
            "5. ¿Qué mejoraría significativamente el resultado?\n\n"
            "Responde ÚNICAMENTE con JSON (sin markdown, sin texto extra):\n"
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
        Revisa código específicamente.
        Detecta: bugs, huecos de seguridad, problemas de performance, manejo de errores faltante.
        """
        req_section = f"\nREQUISITOS:\n{requirements}\n" if requirements else ""

        user_prompt = (
            f"LENGUAJE: {language}\n"
            f"{req_section}\n"
            f"CÓDIGO A AUDITAR:\n```{language}\n{code}\n```\n\n"
            "Audita este código como tech lead senior de Google. Busca:\n"
            "1. Bugs lógicos o de runtime\n"
            "2. Vulnerabilidades de seguridad (inyección, autenticación, exposición de datos)\n"
            "3. Problemas de performance (N+1, loops innecesarios, bloqueos)\n"
            "4. Manejo de errores ausente o insuficiente\n"
            "5. Violaciones de principios SOLID / DRY / KISS\n\n"
            "Responde ÚNICAMENTE con JSON (sin markdown, sin texto extra):\n"
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
        Parsea la respuesta de la IA en un AuditResult estructurado.
        Fallback a WARN con score=60 si el JSON es inválido.
        """
        try:
            # Strip markdown code fences if present
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                cleaned = "\n".join(
                    line for line in lines if not line.startswith("```")
                ).strip()

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
                "[AuditorAgent] No se pudo parsear respuesta de auditoría (%s): %s",
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
                        description=f"No se pudo parsear la respuesta del auditor para '{context_type}'.",
                        fix="Revisar manualmente el output.",
                    )
                ],
                suggestions=["Revisar respuesta cruda del auditor manualmente."],
                reasoning=f"Parse error — respuesta cruda: {response[:200]}",
            )

    # ── EXECUTE ───────────────────────────────────────────

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Punto de entrada genérico.
        - Si el contexto contiene 'output' → audit_output
        - Si el contexto contiene 'code' → audit_code
        - Por defecto → audit_plan
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
