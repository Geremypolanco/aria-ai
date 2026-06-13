"""
Deterministic rule engine — no LLM calls.

Rules are Condition → Action pairs evaluated against a context dict.
Used for routing, validation, threshold enforcement, and guard rails that
MUST be deterministic (permissions, rate limits, budget caps, tool selection).

LLMs must NOT be used for these decisions; they introduce nondeterminism and
latency into paths that should be O(1) and predictable.

Design:
  - Conditions are callables that accept a context dict and return bool
  - Actions are callables that accept the context dict and may mutate it
  - Rules have priority (lower = higher priority, evaluated first)
  - Rules can be tagged for selective evaluation (e.g. "income", "security")
  - Engine returns a RuleEvalResult with all matched rules and their outcomes
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


Condition = Callable[[dict[str, Any]], bool]
Action    = Callable[[dict[str, Any]], Any]


@dataclass
class Rule:
    id: str
    description: str
    condition: Condition
    action: Action
    priority: int = 100
    tags: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class RuleMatch:
    rule_id: str
    description: str
    action_result: Any
    evaluated_at: float = field(default_factory=time.time)


@dataclass
class RuleEvalResult:
    context: dict[str, Any]
    matches: list[RuleMatch]
    evaluated_count: int
    duration_ms: float

    @property
    def matched(self) -> bool:
        return bool(self.matches)

    @property
    def first_result(self) -> Any:
        return self.matches[0].action_result if self.matches else None


class RuleEngine:
    """
    Synchronous (intentionally not async) rule evaluator.
    Deterministic: same context always produces same result.
    """

    def __init__(self) -> None:
        self._rules: list[Rule] = []

    def add_rule(
        self,
        rule_id: str,
        description: str,
        condition: Condition,
        action: Action,
        priority: int = 100,
        tags: Optional[list[str]] = None,
    ) -> "RuleEngine":
        self._rules.append(Rule(
            id=rule_id,
            description=description,
            condition=condition,
            action=action,
            priority=priority,
            tags=tags or [],
        ))
        self._rules.sort(key=lambda r: r.priority)
        return self

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        return len(self._rules) < before

    def enable(self, rule_id: str) -> None:
        for r in self._rules:
            if r.id == rule_id:
                object.__setattr__(r, "enabled", True) if hasattr(r, "__slots__") else setattr(r, "enabled", True)

    def disable(self, rule_id: str) -> None:
        for r in self._rules:
            if r.id == rule_id:
                r.enabled = False

    def evaluate(
        self,
        context: dict[str, Any],
        tags: Optional[list[str]] = None,
        stop_on_first: bool = False,
    ) -> RuleEvalResult:
        """Evaluate all enabled rules against context. Returns all matches."""
        t0 = time.monotonic()
        matches: list[RuleMatch] = []
        evaluated = 0

        for rule in self._rules:
            if not rule.enabled:
                continue
            if tags and not any(t in rule.tags for t in tags):
                continue
            evaluated += 1
            try:
                if rule.condition(context):
                    result = rule.action(context)
                    matches.append(RuleMatch(
                        rule_id=rule.id,
                        description=rule.description,
                        action_result=result,
                    ))
                    if stop_on_first:
                        break
            except Exception:
                pass

        return RuleEvalResult(
            context=context,
            matches=matches,
            evaluated_count=evaluated,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def first_match(self, context: dict[str, Any], tags: Optional[list[str]] = None) -> Optional[Any]:
        """Convenience: evaluate and return the first action result, or None."""
        result = self.evaluate(context, tags=tags, stop_on_first=True)
        return result.first_result

    def all_match(self, context: dict[str, Any], tags: Optional[list[str]] = None) -> list[Any]:
        result = self.evaluate(context, tags=tags)
        return [m.action_result for m in result.matches]

    def rule_count(self, tag: Optional[str] = None) -> int:
        if tag is None:
            return len(self._rules)
        return sum(1 for r in self._rules if tag in r.tags)

    def summary(self) -> dict:
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules if r.enabled),
            "tags": list({t for r in self._rules for t in r.tags}),
        }


# ── Built-in rule builders ────────────────────────────────────────────────────

def threshold_rule(
    rule_id: str,
    field: str,
    operator: str,
    threshold: float,
    action: Action,
    description: str = "",
    priority: int = 50,
    tags: Optional[list[str]] = None,
) -> Rule:
    """Factory for numeric threshold rules: field >/</>=/<=/==/!= threshold."""
    ops = {">": float.__gt__, "<": float.__lt__, ">=": float.__ge__,
           "<=": float.__le__, "==": float.__eq__, "!=": float.__ne__}
    op_fn = ops.get(operator, float.__gt__)

    def condition(ctx: dict) -> bool:
        val = ctx.get(field)
        return val is not None and op_fn(float(val), threshold)

    return Rule(
        id=rule_id,
        description=description or f"{field} {operator} {threshold}",
        condition=condition,
        action=action,
        priority=priority,
        tags=tags or [],
    )


def pattern_rule(
    rule_id: str,
    field: str,
    pattern: str,
    action: Action,
    description: str = "",
    priority: int = 50,
    tags: Optional[list[str]] = None,
) -> Rule:
    """Factory for regex pattern rules on string fields."""
    compiled = re.compile(pattern, re.IGNORECASE)

    def condition(ctx: dict) -> bool:
        val = ctx.get(field, "")
        return bool(compiled.search(str(val)))

    return Rule(
        id=rule_id,
        description=description or f"{field} matches {pattern}",
        condition=condition,
        action=action,
        priority=priority,
        tags=tags or [],
    )


def build_aria_rules() -> RuleEngine:
    """
    Bootstrap the canonical ARIA rule set.
    These rules enforce deterministic governance without any LLM involvement.
    """
    engine = RuleEngine()

    # Budget enforcement
    engine.add_rule(
        rule_id="budget_hard_cap",
        description="Block execution if daily spend exceeds hard cap",
        condition=lambda ctx: float(ctx.get("daily_spend_usd", 0)) >= float(ctx.get("budget_cap_usd", 50)),
        action=lambda ctx: {"blocked": True, "reason": "daily_budget_exceeded"},
        priority=1,
        tags=["budget", "safety"],
    )

    # Tool reliability gate
    engine.add_rule(
        rule_id="tool_reliability_gate",
        description="Skip tools with success_rate below 0.3",
        condition=lambda ctx: float(ctx.get("tool_success_rate", 1.0)) < 0.3,
        action=lambda ctx: {"skip_tool": True, "reason": "low_reliability"},
        priority=10,
        tags=["tools", "quality"],
    )

    # Income cycle rate limit
    engine.add_rule(
        rule_id="income_rate_limit",
        description="Block income cycle if last run was < 15 minutes ago",
        condition=lambda ctx: float(ctx.get("minutes_since_last_income_cycle", 99)) < 15,
        action=lambda ctx: {"blocked": True, "reason": "income_cycle_rate_limited"},
        priority=20,
        tags=["income", "safety"],
    )

    # High-value opportunity fast-track
    engine.add_rule(
        rule_id="high_roi_fast_track",
        description="Prioritize opportunities with ROI score > 100",
        condition=lambda ctx: float(ctx.get("roi_score", 0)) > 100,
        action=lambda ctx: {"priority": "critical", "fast_track": True},
        priority=30,
        tags=["income", "routing"],
    )

    # Memory conflict alert
    engine.add_rule(
        rule_id="memory_conflict_alert",
        description="Flag when conflict rate exceeds threshold",
        condition=lambda ctx: int(ctx.get("memory_conflicts", 0)) > 5,
        action=lambda ctx: {"alert": "memory_conflict_high", "severity": "medium"},
        priority=40,
        tags=["memory", "quality"],
    )

    # Agent recursion depth limit
    engine.add_rule(
        rule_id="max_recursion_depth",
        description="Block delegation if depth exceeds 5",
        condition=lambda ctx: int(ctx.get("delegation_depth", 0)) >= 5,
        action=lambda ctx: {"blocked": True, "reason": "max_delegation_depth"},
        priority=5,
        tags=["agents", "safety"],
    )

    return engine


_engine: Optional[RuleEngine] = None


def get_rule_engine() -> RuleEngine:
    global _engine
    if _engine is None:
        _engine = build_aria_rules()
    return _engine
