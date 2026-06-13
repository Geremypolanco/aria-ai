"""
Constraint validators — deterministic, no LLM.

Constraints are invariants that MUST hold. Violations are never silently ignored;
they raise ConstraintViolation or return a ConstraintResult with details.

Used for:
- Input validation at system boundaries
- Pre/post-condition checking in workflows
- Schema enforcement without Pydantic overhead
- Budget / capability guardrails
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


class ConstraintViolation(Exception):
    def __init__(self, constraint_id: str, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.constraint_id = constraint_id
        self.context = context or {}


@dataclass
class ConstraintResult:
    valid: bool
    violations: list[dict[str, str]] = field(default_factory=list)

    def raise_if_invalid(self) -> None:
        if not self.valid:
            msg = "; ".join(v["message"] for v in self.violations)
            raise ConstraintViolation("composite", msg)

    def merge(self, other: "ConstraintResult") -> "ConstraintResult":
        return ConstraintResult(
            valid=self.valid and other.valid,
            violations=self.violations + other.violations,
        )


# ── Primitive validators ──────────────────────────────────────────────────────

def require_str(value: Any, field_name: str, min_len: int = 1, max_len: int = 10_000) -> ConstraintResult:
    if not isinstance(value, str):
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must be a string"}])
    if len(value) < min_len:
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} is too short (min {min_len})"}])
    if len(value) > max_len:
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} is too long (max {max_len})"}])
    return ConstraintResult(True)


def require_float(value: Any, field_name: str, min_val: float = 0.0, max_val: float = 1e12) -> ConstraintResult:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must be numeric"}])
    if v < min_val:
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must be >= {min_val}"}])
    if v > max_val:
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must be <= {max_val}"}])
    return ConstraintResult(True)


def require_in(value: Any, allowed: set, field_name: str) -> ConstraintResult:
    if value not in allowed:
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must be one of {sorted(str(a) for a in allowed)}"}])
    return ConstraintResult(True)


def require_pattern(value: str, pattern: str, field_name: str) -> ConstraintResult:
    if not re.fullmatch(pattern, str(value)):
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must match pattern {pattern!r}"}])
    return ConstraintResult(True)


def require_dict_keys(d: Any, required_keys: set[str], field_name: str = "payload") -> ConstraintResult:
    if not isinstance(d, dict):
        return ConstraintResult(False, [{"field": field_name, "message": f"{field_name} must be a dict"}])
    missing = required_keys - set(d.keys())
    if missing:
        return ConstraintResult(False, [{"field": field_name, "message": f"Missing required keys: {sorted(missing)}"}])
    return ConstraintResult(True)


# ── Domain constraint sets ────────────────────────────────────────────────────

def validate_opportunity_input(data: dict) -> ConstraintResult:
    results = [
        require_str(data.get("name", ""), "name", min_len=2, max_len=200),
        require_in(data.get("category", ""), {"content", "ecommerce", "affiliate", "saas", "service", "general"}, "category"),
        require_float(data.get("estimated_revenue_usd", -1), "estimated_revenue_usd", min_val=0.0, max_val=1_000_000),
        require_float(data.get("estimated_effort_hours", -1), "estimated_effort_hours", min_val=0.1, max_val=10_000),
        require_float(data.get("risk_level", -1), "risk_level", min_val=0.0, max_val=1.0),
        require_float(data.get("confidence", -1), "confidence", min_val=0.0, max_val=1.0),
    ]
    combined = ConstraintResult(True)
    for r in results:
        combined = combined.merge(r)
    return combined


def validate_tool_call(data: dict) -> ConstraintResult:
    results = [
        require_str(data.get("tool_name", ""), "tool_name"),
        require_float(data.get("latency_ms", -1), "latency_ms", min_val=0.0),
    ]
    combined = ConstraintResult(True)
    for r in results:
        combined = combined.merge(r)
    return combined


def validate_event_payload(event_type: str, payload: dict) -> ConstraintResult:
    """Domain-specific payload validation for event schemas."""
    required: dict[str, set[str]] = {
        "business.revenue.recorded": {"amount_usd", "source"},
        "runtime.task.enqueued": {"task_name"},
        "agent.delegated": {"from_agent", "to_agent", "task"},
    }
    keys = required.get(event_type)
    if keys is None:
        return ConstraintResult(True)
    return require_dict_keys(payload, keys, "payload")
