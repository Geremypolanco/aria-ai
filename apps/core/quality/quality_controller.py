"""Autonomous quality control: architecture audits, regression detection, health scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class QualityFinding:
    id: str
    category: str
    severity: Severity
    title: str
    description: str
    affected_component: str
    remediation: str = ""
    detected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved: bool = False
    resolved_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "affected_component": self.affected_component,
            "remediation": self.remediation,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }


@dataclass
class AuditReport:
    audit_id: str
    scope: str
    started_at: str
    finished_at: str | None = None
    findings: list[QualityFinding] = field(default_factory=list)
    health_score: float = 1.0
    summary: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL and not f.resolved)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH and not f.resolved)

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "scope": self.scope,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "findings": [f.to_dict() for f in self.findings],
            "health_score": self.health_score,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "summary": self.summary,
        }


class QualityController:
    """
    Autonomous quality control. Runs architecture checks, tracks regressions,
    and computes a system health score. Designed to run as a scheduled background task.
    """

    def __init__(self) -> None:
        self._findings: dict[str, QualityFinding] = {}
        self._audits: list[AuditReport] = []
        self._baseline_metrics: dict[str, float] = {}
        self._finding_counter = 0

    def _new_id(self, prefix: str = "qf") -> str:
        self._finding_counter += 1
        return f"{prefix}_{self._finding_counter:04d}"

    async def run_architecture_audit(self) -> AuditReport:
        import uuid

        report = AuditReport(
            audit_id=f"audit_{uuid.uuid4().hex[:8]}",
            scope="architecture",
            started_at=datetime.now(UTC).isoformat(),
        )

        findings = []
        findings.extend(await self._check_memory_systems())
        findings.extend(await self._check_agent_health())
        findings.extend(await self._check_tool_reliability())

        for f in findings:
            self._findings[f.id] = f
            report.findings.append(f)

        report.health_score = self._compute_health_score(report.findings)
        report.finished_at = datetime.now(UTC).isoformat()
        report.summary = self._generate_summary(report)
        self._audits.append(report)
        return report

    async def _check_memory_systems(self) -> list[QualityFinding]:
        findings = []
        try:
            from apps.core.memory.semantic_memory import get_semantic_memory

            mem = get_semantic_memory()
            stats = mem.summary() if hasattr(mem, "summary") else {}
            fact_count = stats.get("total_facts", 0)
            if fact_count == 0:
                findings.append(
                    QualityFinding(
                        id=self._new_id(),
                        category="memory",
                        severity=Severity.MEDIUM,
                        title="Semantic memory empty",
                        description="No facts stored in semantic memory. ARIA may lack grounding.",
                        affected_component="semantic_memory",
                        remediation="Ensure income cycles and tool calls record facts to semantic memory.",
                    )
                )
        except Exception as exc:
            findings.append(
                QualityFinding(
                    id=self._new_id(),
                    category="memory",
                    severity=Severity.HIGH,
                    title="Semantic memory unavailable",
                    description=str(exc),
                    affected_component="semantic_memory",
                )
            )

        try:
            from apps.core.memory.orchestrator import get_memory_orchestrator

            orch = get_memory_orchestrator()
            s = orch.summary()
            if s.get("conflicts_detected", 0) > 10:
                findings.append(
                    QualityFinding(
                        id=self._new_id(),
                        category="memory",
                        severity=Severity.MEDIUM,
                        title="High memory conflict count",
                        description=f"Memory orchestrator detected {s['conflicts_detected']} conflicts.",
                        affected_component="memory_orchestrator",
                        remediation="Review conflicting facts and prune stale semantic memory entries.",
                    )
                )
        except Exception:
            pass

        return findings

    async def _check_agent_health(self) -> list[QualityFinding]:
        findings = []
        try:
            from apps.core.agents.hierarchy.agent_hierarchy import get_agent_hierarchy

            hier = get_agent_hierarchy()
            s = hier.summary()
            rate = s.get("delegation_success_rate", 1.0)
            if rate < 0.7 and s.get("total_delegations", 0) >= 5:
                findings.append(
                    QualityFinding(
                        id=self._new_id(),
                        category="agents",
                        severity=Severity.HIGH,
                        title="Low agent delegation success rate",
                        description=f"Delegation success rate is {rate:.0%} (threshold: 70%).",
                        affected_component="agent_hierarchy",
                        remediation="Inspect failing agents; check handlers and capability routing.",
                    )
                )
        except Exception:
            pass
        return findings

    async def _check_tool_reliability(self) -> list[QualityFinding]:
        findings = []
        try:
            from apps.core.tools.intelligence.tool_registry import get_tool_registry

            registry = get_tool_registry()
            failing = registry.failing_tools(threshold=0.3)
            for tool in failing[:3]:
                findings.append(
                    QualityFinding(
                        id=self._new_id(),
                        category="tools",
                        severity=Severity.HIGH,
                        title=f"Tool '{tool.name}' has low reliability",
                        description=f"Success rate: {tool.success_rate:.0%} over {tool.call_count} calls.",
                        affected_component=f"tool:{tool.name}",
                        remediation=f"Investigate errors: {tool.error_patterns[-1] if tool.error_patterns else 'none recorded'}",
                    )
                )
        except Exception:
            pass
        return findings

    def _compute_health_score(self, findings: list[QualityFinding]) -> float:
        active = [f for f in findings if not f.resolved]
        if not active:
            return 1.0
        score = 1.0
        for f in active:
            if f.severity == Severity.CRITICAL:
                score -= 0.25
            elif f.severity == Severity.HIGH:
                score -= 0.10
            elif f.severity == Severity.MEDIUM:
                score -= 0.05
            elif f.severity == Severity.LOW:
                score -= 0.01
        return round(max(0.0, min(1.0, score)), 4)

    def _generate_summary(self, report: AuditReport) -> str:
        if not report.findings:
            return f"System healthy. Score: {report.health_score:.0%}."
        parts = []
        if report.critical_count:
            parts.append(f"{report.critical_count} critical")
        if report.high_count:
            parts.append(f"{report.high_count} high")
        med = sum(1 for f in report.findings if f.severity == Severity.MEDIUM and not f.resolved)
        if med:
            parts.append(f"{med} medium")
        return f"Score: {report.health_score:.0%}. Issues: {', '.join(parts)}."

    def resolve_finding(self, finding_id: str) -> bool:
        f = self._findings.get(finding_id)
        if f is None:
            return False
        f.resolved = True
        f.resolved_at = datetime.now(UTC).isoformat()
        return True

    def set_baseline(self, metric_name: str, value: float) -> None:
        self._baseline_metrics[metric_name] = value

    def detect_regression(
        self, metric_name: str, current_value: float, tolerance: float = 0.1
    ) -> QualityFinding | None:
        baseline = self._baseline_metrics.get(metric_name)
        if baseline is None:
            return None
        delta = (current_value - baseline) / max(abs(baseline), 0.001)
        if delta < -tolerance:
            f = QualityFinding(
                id=self._new_id("reg"),
                category="regression",
                severity=Severity.HIGH,
                title=f"Regression detected: {metric_name}",
                description=f"Baseline: {baseline:.4f}, Current: {current_value:.4f}, Drop: {delta:.1%}",
                affected_component=metric_name,
                remediation="Compare recent commits/changes to identify root cause.",
            )
            self._findings[f.id] = f
            return f
        return None

    def open_findings(self, severity: Severity | None = None) -> list[QualityFinding]:
        result = [f for f in self._findings.values() if not f.resolved]
        if severity is not None:
            result = [f for f in result if f.severity == severity]
        return sorted(
            result,
            key=lambda f: ["critical", "high", "medium", "low", "info"].index(f.severity.value),
        )

    def system_health(self) -> dict:
        all_open = self.open_findings()
        score = self._compute_health_score(all_open)
        return {
            "health_score": score,
            "health_label": (
                "healthy" if score >= 0.85 else "degraded" if score >= 0.6 else "critical"
            ),
            "open_findings": len(all_open),
            "critical": sum(1 for f in all_open if f.severity == Severity.CRITICAL),
            "high": sum(1 for f in all_open if f.severity == Severity.HIGH),
            "medium": sum(1 for f in all_open if f.severity == Severity.MEDIUM),
            "total_audits": len(self._audits),
            "last_audit": self._audits[-1].finished_at if self._audits else None,
        }


_controller: QualityController | None = None


def get_quality_controller() -> QualityController:
    global _controller
    if _controller is None:
        _controller = QualityController()
    return _controller
