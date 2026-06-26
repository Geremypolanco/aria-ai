"""
ARIA Capability & Governance System — Policy-driven action authorization.

Every tool call ARIA makes passes through this layer. Without it:
  - ARIA can spend unlimited money (API calls, Stripe charges)
  - ARIA can modify data without approval
  - No audit trail for autonomous actions
  - Impossible to debug what ARIA decided and why

Design:
  - Capability = a named action class (not a specific function)
  - Role = a principal's permission level
  - Policy = role → allowed capabilities mapping
  - ActionGuard = sync check before execution
  - AuditLog = append-only record of every policy decision

This is OPA (Open Policy Agent) concepts implemented in pure Python.
The interface is designed to swap in real OPA when the system requires it.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger("aria.security")


class Capability(StrEnum):
    # Read-only operations
    WEB_SEARCH = "web_search"
    READ_MEMORY = "read_memory"
    READ_DB = "read_db"
    CHECK_STATUS = "check_status"

    # Write operations
    WRITE_MEMORY = "write_memory"
    WRITE_DB = "write_db"
    SEND_NOTIFICATION = "send_notification"

    # External API calls (potentially costly)
    API_CALL_AI = "api_call_ai"
    API_CALL_PAYMENT = "api_call_payment"
    API_CALL_SOCIAL = "api_call_social"
    API_CALL_COMMERCE = "api_call_commerce"
    API_CALL_EMAIL = "api_call_email"

    # Code and file operations
    CODE_EXECUTE = "code_execute"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"

    # Business operations (high risk)
    INCOME_CYCLE = "income_cycle"
    PUBLISH_CONTENT = "publish_content"
    CREATE_PRODUCT = "create_product"
    CHARGE_PAYMENT = "charge_payment"

    # System operations (critical)
    MODIFY_GOALS = "modify_goals"
    MODIFY_POLICIES = "modify_policies"
    SPAWN_AGENT = "spawn_agent"
    DEPLOY = "deploy"


class Role(StrEnum):
    OWNER = "owner"  # full access — the human principal
    OPERATOR = "operator"  # trusted human with limited permissions
    ARIA_AGENT = "aria_agent"  # ARIA's own execution role
    READER = "reader"  # read-only access
    WEBHOOK = "webhook"  # external webhook callbacks
    ANONYMOUS = "anonymous"  # unauthenticated — nearly no access


# ── Policy Definitions ────────────────────────────────────────────────────
#
# Every row is (Role, frozenset of allowed Capabilities).
# ARIA_AGENT deliberately cannot MODIFY_POLICIES or DEPLOY — those require OWNER.

_POLICY: dict[Role, frozenset[Capability]] = {
    Role.OWNER: frozenset(Capability),  # all capabilities
    Role.OPERATOR: frozenset(
        {
            Capability.WEB_SEARCH,
            Capability.READ_MEMORY,
            Capability.READ_DB,
            Capability.WRITE_MEMORY,
            Capability.API_CALL_AI,
            Capability.API_CALL_SOCIAL,
            Capability.INCOME_CYCLE,
            Capability.PUBLISH_CONTENT,
            Capability.SEND_NOTIFICATION,
            Capability.CHECK_STATUS,
        }
    ),
    Role.ARIA_AGENT: frozenset(
        {
            Capability.WEB_SEARCH,
            Capability.READ_MEMORY,
            Capability.READ_DB,
            Capability.WRITE_MEMORY,
            Capability.WRITE_DB,
            Capability.API_CALL_AI,
            Capability.API_CALL_SOCIAL,
            Capability.API_CALL_COMMERCE,
            Capability.API_CALL_EMAIL,
            Capability.INCOME_CYCLE,
            Capability.PUBLISH_CONTENT,
            Capability.CREATE_PRODUCT,
            Capability.SEND_NOTIFICATION,
            Capability.FILE_READ,
            Capability.MODIFY_GOALS,
            Capability.CHECK_STATUS,
        }
    ),
    Role.READER: frozenset(
        {
            Capability.WEB_SEARCH,
            Capability.READ_MEMORY,
            Capability.READ_DB,
            Capability.CHECK_STATUS,
        }
    ),
    Role.WEBHOOK: frozenset(
        {
            Capability.WRITE_MEMORY,
            Capability.CHECK_STATUS,
            Capability.SEND_NOTIFICATION,
        }
    ),
    Role.ANONYMOUS: frozenset({Capability.CHECK_STATUS}),
}


@dataclass
class AuditEntry:
    id: str
    ts: str
    role: str
    capability: str
    allowed: bool
    context: dict[str, Any]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class PolicyEngine:
    """
    Evaluates capability requests against the role-based policy.

    Usage:
        engine = PolicyEngine()
        if engine.allows(Role.ARIA_AGENT, Capability.INCOME_CYCLE):
            await run_income_cycle()
        else:
            logger.warning("Policy denied income cycle for ARIA_AGENT")
    """

    def __init__(self) -> None:
        self._audit_log: list[AuditEntry] = []
        self._custom_denials: set[tuple[Role, Capability]] = set()

    # ── Evaluation ────────────────────────────────────────────────────────

    def allows(
        self,
        role: Role,
        capability: Capability,
        context: dict[str, Any] | None = None,
        audit: bool = True,
    ) -> bool:
        allowed = capability in _POLICY.get(role, frozenset())

        # Check custom runtime denials (dynamic policy updates)
        if (role, capability) in self._custom_denials:
            allowed = False

        if audit:
            self._record(role, capability, allowed, context or {})

        return allowed

    def requires(self, role: Role, capability: Capability) -> None:
        """Assert that role has capability. Raises PermissionError if not."""
        if not self.allows(role, capability, audit=False):
            raise PermissionError(
                f"Role '{role.value}' does not have capability '{capability.value}'"
            )

    def capabilities_for(self, role: Role) -> frozenset[Capability]:
        """Return all capabilities granted to a role."""
        base = _POLICY.get(role, frozenset())
        denied = {cap for (r, cap) in self._custom_denials if r == role}
        return base - denied

    # ── Dynamic Policy ────────────────────────────────────────────────────

    def deny(self, role: Role, capability: Capability, reason: str = "") -> None:
        """Runtime policy: deny a capability from a role until revoked."""
        self._custom_denials.add((role, capability))
        logger.info("[Security] Runtime denial: %s.%s — %s", role.value, capability.value, reason)

    def revoke_denial(self, role: Role, capability: Capability) -> None:
        self._custom_denials.discard((role, capability))

    # ── Audit ─────────────────────────────────────────────────────────────

    def _record(self, role: Role, capability: Capability, allowed: bool, context: dict) -> None:
        entry = AuditEntry(
            id=uuid.uuid4().hex[:8],
            ts=datetime.now(UTC).isoformat(),
            role=role.value,
            capability=capability.value,
            allowed=allowed,
            context=context,
            reason="policy_matrix" if allowed else "not_in_policy",
        )
        self._audit_log.append(entry)
        if not allowed:
            logger.warning(
                "[Security] DENIED: %s attempted %s — not in policy",
                role.value,
                capability.value,
            )

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        return [e.to_dict() for e in self._audit_log[-limit:]]

    def denied_count(self) -> int:
        return sum(1 for e in self._audit_log if not e.allowed)

    async def persist_audit(self) -> None:
        """Persist recent audit log to Redis for cross-restart analysis."""
        try:
            from apps.core.memory.redis_client import get_cache

            cache = get_cache()
            if cache:
                recent = self.get_audit_log(limit=100)
                await cache.set(
                    "aria:security:audit",
                    json.dumps(recent),
                    ttl_seconds=86400 * 7,
                )
        except Exception as exc:
            logger.debug("[Security] Audit persist failed: %s", exc)

    def summary(self) -> dict:
        total = len(self._audit_log)
        denied = self.denied_count()
        return {
            "total_decisions": total,
            "allowed": total - denied,
            "denied": denied,
            "denial_rate": round(denied / total, 3) if total else 0.0,
            "custom_denials_active": len(self._custom_denials),
        }


_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine


def guard(capability: Capability, role: Role = Role.ARIA_AGENT):
    """
    Decorator that enforces a capability check before the function runs.

    Usage:
        @guard(Capability.INCOME_CYCLE)
        async def run_income():
            ...
    """

    def decorator(fn):
        import functools

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            engine = get_policy_engine()
            if not engine.allows(role, capability):
                raise PermissionError(
                    f"Capability '{capability.value}' denied for role '{role.value}'"
                )
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
