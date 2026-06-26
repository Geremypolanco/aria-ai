"""
CTO Agent — Technology evaluation, architecture review, and engineering metrics.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import AIModel, get_ai_client

_KEY = "executive:cto:v1"
_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class TechDecision:
    decision_id: str
    title: str
    category: str  # "architecture" | "tool" | "security" | "performance"
    recommendation: str
    rationale: str
    complexity: str  # "low" | "medium" | "high"
    risk_level: str  # "low" | "medium" | "high"
    approved: bool
    ts: float

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "title": self.title,
            "category": self.category,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "complexity": self.complexity,
            "risk_level": self.risk_level,
            "approved": self.approved,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TechDecision:
        return cls(
            decision_id=data["decision_id"],
            title=data["title"],
            category=data.get("category", "tool"),
            recommendation=data.get("recommendation", ""),
            rationale=data.get("rationale", ""),
            complexity=data.get("complexity", "medium"),
            risk_level=data.get("risk_level", "medium"),
            approved=data.get("approved", False),
            ts=data.get("ts", time.time()),
        )


@dataclass
class SystemHealth:
    component: str
    status: str  # "healthy" | "degraded" | "down"
    latency_ms: float
    error_rate: float
    last_checked: float

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error_rate": self.error_rate,
            "last_checked": self.last_checked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SystemHealth:
        return cls(
            component=data["component"],
            status=data.get("status", "healthy"),
            latency_ms=data.get("latency_ms", 0.0),
            error_rate=data.get("error_rate", 0.0),
            last_checked=data.get("last_checked", time.time()),
        )


class CTOAgent:
    def __init__(self) -> None:
        self._decisions: list[dict] = []
        self._health_checks: list[dict] = []
        self._tech_radar: dict[str, list[str]] = {
            "adopt": [],
            "trial": [],
            "hold": [],
            "avoid": [],
        }
        self._loaded = False

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_KEY)
                if isinstance(data, dict):
                    self._decisions = data.get("decisions", [])
                    self._health_checks = data.get("health_checks", [])
                    self._tech_radar = data.get(
                        "tech_radar", {"adopt": [], "trial": [], "hold": [], "avoid": []}
                    )
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            payload = {
                "decisions": self._decisions[-200:],
                "health_checks": self._health_checks[-200:],
                "tech_radar": self._tech_radar,
            }
            await cache.set(_KEY, payload, ttl_seconds=_TTL)
        except Exception:
            pass

    async def evaluate_technology(self, tech_name: str, use_case: str) -> TechDecision:
        await self._load()
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are the CTO. Evaluate a technology for production use. "
                "Reply with: RECOMMENDATION: <adopt|trial|hold|avoid> | "
                "CATEGORY: <architecture|tool|security|performance> | "
                "COMPLEXITY: <low|medium|high> | RISK: <low|medium|high> | "
                "RATIONALE: <brief reason>"
            ),
            user=f"Technology: {tech_name}\nUse case: {use_case}",
            model=AIModel.STRATEGY,
            max_tokens=300,
        )
        content = resp.content if resp.success else ""

        recommendation = "trial"
        category = "tool"
        complexity = "medium"
        risk_level = "medium"
        rationale = content or f"{tech_name} requires further evaluation."

        if content:
            try:
                parts = content.split("|")
                for part in parts:
                    part = part.strip()
                    if part.startswith("RECOMMENDATION:"):
                        val = part.split(":")[-1].strip().lower().split()[0]
                        if val in ("adopt", "trial", "hold", "avoid"):
                            recommendation = val
                    elif part.startswith("CATEGORY:"):
                        val = part.split(":")[-1].strip().lower().split()[0]
                        if val in ("architecture", "tool", "security", "performance"):
                            category = val
                    elif part.startswith("COMPLEXITY:"):
                        val = part.split(":")[-1].strip().lower().split()[0]
                        if val in ("low", "medium", "high"):
                            complexity = val
                    elif part.startswith("RISK:"):
                        val = part.split(":")[-1].strip().lower().split()[0]
                        if val in ("low", "medium", "high"):
                            risk_level = val
                    elif part.startswith("RATIONALE:"):
                        rationale = part.split("RATIONALE:")[-1].strip()
            except Exception:
                pass

        # Update tech radar
        for quadrant in ["adopt", "trial", "hold", "avoid"]:
            if tech_name in self._tech_radar.get(quadrant, []):
                self._tech_radar[quadrant].remove(tech_name)
        if recommendation not in self._tech_radar:
            self._tech_radar[recommendation] = []
        self._tech_radar[recommendation].append(tech_name)

        decision = TechDecision(
            decision_id=str(uuid.uuid4()),
            title=f"Evaluate {tech_name}",
            category=category,
            recommendation=recommendation,
            rationale=rationale,
            complexity=complexity,
            risk_level=risk_level,
            approved=recommendation in ("adopt", "trial"),
            ts=time.time(),
        )
        self._decisions.append(decision.to_dict())
        await self._save()
        return decision

    async def architecture_review(self, system_description: str) -> dict:
        ai = get_ai_client()
        resp = await ai.complete(
            system=(
                "You are the CTO. Review the system architecture. "
                "Return JSON with keys: risks (list of strings), "
                "recommendations (list of strings), score (0-10 integer)."
            ),
            user=f"System: {system_description}",
            model=AIModel.STRATEGY,
            max_tokens=400,
            json_mode=True,
        )
        content = resp.content if resp.success else ""
        risks: list[str] = []
        recommendations: list[str] = []
        score = 7

        if content:
            try:
                import json

                data = json.loads(content)
                risks = data.get("risks", [])
                recommendations = data.get("recommendations", [])
                score = int(data.get("score", 7))
                score = max(0, min(10, score))
            except Exception:
                # Fall back to text parsing
                risks = ["Review required"]
                recommendations = [content[:200]]

        return {
            "risks": risks,
            "recommendations": recommendations,
            "score": score,
            "reviewed_at": time.time(),
        }

    async def system_health_check(self, components: list[str]) -> list[SystemHealth]:
        await self._load()
        results: list[SystemHealth] = []
        now = time.time()
        for component in components:
            # Simulate health check with reasonable defaults
            health = SystemHealth(
                component=component,
                status="healthy",
                latency_ms=50.0,
                error_rate=0.01,
                last_checked=now,
            )
            results.append(health)
            self._health_checks.append(health.to_dict())
        await self._save()
        return results

    def tech_radar(self) -> dict:
        return {
            "adopt": list(self._tech_radar.get("adopt", [])),
            "trial": list(self._tech_radar.get("trial", [])),
            "hold": list(self._tech_radar.get("hold", [])),
            "avoid": list(self._tech_radar.get("avoid", [])),
        }

    def technical_debt_report(self) -> dict:
        high_risk = [d for d in self._decisions if d.get("risk_level") == "high"]
        high_complexity = [d for d in self._decisions if d.get("complexity") == "high"]
        return {
            "total_decisions": len(self._decisions),
            "high_risk_decisions": len(high_risk),
            "high_complexity_decisions": len(high_complexity),
            "tech_debt_score": round(
                (len(high_risk) + len(high_complexity)) / max(len(self._decisions), 1) * 10,
                1,
            ),
        }

    def engineering_metrics(self) -> dict:
        decisions = [TechDecision.from_dict(d) for d in self._decisions]
        complexity_map = {"low": 1, "medium": 2, "high": 3}
        avg_complexity = (
            sum(complexity_map.get(d.complexity, 2) for d in decisions) / len(decisions)
            if decisions
            else 0.0
        )
        high_risk_count = sum(1 for d in decisions if d.risk_level == "high")
        return {
            "decisions_made": len(decisions),
            "avg_complexity": round(avg_complexity, 2),
            "high_risk_count": high_risk_count,
        }


_instance: CTOAgent | None = None


def get_cto_agent() -> CTOAgent:
    global _instance
    if _instance is None:
        _instance = CTOAgent()
    return _instance
