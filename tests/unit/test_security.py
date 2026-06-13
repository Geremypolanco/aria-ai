"""
Tests for the governance/security layer: capabilities, RBAC, policy engine.
"""
from __future__ import annotations

import pytest


class TestPolicyEngine:
    @pytest.fixture
    def engine(self):
        from apps.core.security.capabilities import PolicyEngine
        return PolicyEngine()

    def test_owner_has_all_capabilities(self, engine):
        from apps.core.security.capabilities import Role, Capability
        for cap in Capability:
            assert engine.allows(Role.OWNER, cap, audit=False)

    def test_anonymous_denied_most_capabilities(self, engine):
        from apps.core.security.capabilities import Role, Capability
        denied_caps = [
            Capability.INCOME_CYCLE,
            Capability.CHARGE_PAYMENT,
            Capability.WRITE_DB,
            Capability.MODIFY_POLICIES,
            Capability.DEPLOY,
        ]
        for cap in denied_caps:
            assert not engine.allows(Role.ANONYMOUS, cap, audit=False), f"Anonymous should not have {cap}"

    def test_anonymous_can_check_status(self, engine):
        from apps.core.security.capabilities import Role, Capability
        assert engine.allows(Role.ANONYMOUS, Capability.CHECK_STATUS, audit=False)

    def test_aria_agent_can_run_income_cycle(self, engine):
        from apps.core.security.capabilities import Role, Capability
        assert engine.allows(Role.ARIA_AGENT, Capability.INCOME_CYCLE, audit=False)

    def test_aria_agent_cannot_deploy(self, engine):
        from apps.core.security.capabilities import Role, Capability
        assert not engine.allows(Role.ARIA_AGENT, Capability.DEPLOY, audit=False)

    def test_aria_agent_cannot_modify_policies(self, engine):
        from apps.core.security.capabilities import Role, Capability
        assert not engine.allows(Role.ARIA_AGENT, Capability.MODIFY_POLICIES, audit=False)

    def test_reader_can_search(self, engine):
        from apps.core.security.capabilities import Role, Capability
        assert engine.allows(Role.READER, Capability.WEB_SEARCH, audit=False)

    def test_reader_cannot_write(self, engine):
        from apps.core.security.capabilities import Role, Capability
        assert not engine.allows(Role.READER, Capability.WRITE_DB, audit=False)

    def test_dynamic_denial_overrides_policy(self, engine):
        from apps.core.security.capabilities import Role, Capability
        # ARIA_AGENT normally can run income cycles
        assert engine.allows(Role.ARIA_AGENT, Capability.INCOME_CYCLE, audit=False)

        # Runtime denial (e.g., emergency stop)
        engine.deny(Role.ARIA_AGENT, Capability.INCOME_CYCLE, reason="Emergency stop")
        assert not engine.allows(Role.ARIA_AGENT, Capability.INCOME_CYCLE, audit=False)

        # Revoke denial
        engine.revoke_denial(Role.ARIA_AGENT, Capability.INCOME_CYCLE)
        assert engine.allows(Role.ARIA_AGENT, Capability.INCOME_CYCLE, audit=False)

    def test_requires_raises_on_denied(self, engine):
        from apps.core.security.capabilities import Role, Capability
        with pytest.raises(PermissionError, match="does not have capability"):
            engine.requires(Role.READER, Capability.CHARGE_PAYMENT)

    def test_requires_passes_on_allowed(self, engine):
        from apps.core.security.capabilities import Role, Capability
        engine.requires(Role.OWNER, Capability.DEPLOY)  # should not raise

    def test_audit_log_records_decisions(self, engine):
        from apps.core.security.capabilities import Role, Capability
        engine.allows(Role.READER, Capability.WEB_SEARCH)
        engine.allows(Role.ANONYMOUS, Capability.INCOME_CYCLE)  # denied

        log = engine.get_audit_log()
        assert len(log) == 2
        assert any(entry["allowed"] for entry in log)
        assert any(not entry["allowed"] for entry in log)

    def test_denied_count(self, engine):
        from apps.core.security.capabilities import Role, Capability
        engine.allows(Role.ANONYMOUS, Capability.INCOME_CYCLE)
        engine.allows(Role.ANONYMOUS, Capability.DEPLOY)
        engine.allows(Role.OWNER, Capability.DEPLOY)

        assert engine.denied_count() == 2

    def test_summary_structure(self, engine):
        from apps.core.security.capabilities import Role, Capability
        engine.allows(Role.OWNER, Capability.INCOME_CYCLE)
        engine.allows(Role.ANONYMOUS, Capability.DEPLOY)  # denied

        summary = engine.summary()
        assert "total_decisions" in summary
        assert "allowed" in summary
        assert "denied" in summary
        assert "denial_rate" in summary
        assert summary["total_decisions"] == 2

    def test_capabilities_for_role(self, engine):
        from apps.core.security.capabilities import Role, Capability
        reader_caps = engine.capabilities_for(Role.READER)
        assert Capability.WEB_SEARCH in reader_caps
        assert Capability.DEPLOY not in reader_caps

    @pytest.mark.asyncio
    async def test_guard_decorator_denies(self):
        from apps.core.security.capabilities import guard, Capability, Role

        @guard(Capability.DEPLOY, role=Role.READER)
        async def protected_fn():
            return "ran"

        with pytest.raises(PermissionError):
            await protected_fn()

    @pytest.mark.asyncio
    async def test_guard_decorator_allows(self):
        from apps.core.security.capabilities import guard, Capability, Role

        @guard(Capability.WEB_SEARCH, role=Role.READER)
        async def allowed_fn():
            return "ran"

        result = await allowed_fn()
        assert result == "ran"


class TestCapabilityEnum:
    def test_all_capabilities_are_strings(self):
        from apps.core.security.capabilities import Capability
        for cap in Capability:
            assert isinstance(cap.value, str)
            assert len(cap.value) > 0

    def test_role_enum_has_expected_values(self):
        from apps.core.security.capabilities import Role
        roles = {r.value for r in Role}
        assert "owner" in roles
        assert "aria_agent" in roles
        assert "reader" in roles
        assert "anonymous" in roles
