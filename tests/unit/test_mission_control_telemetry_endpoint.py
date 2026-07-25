"""HTTP-layer tests for the Mission Control telemetry admin endpoint
(apps/core/main.py):

  GET /admin/api/mission-control/telemetry

Owner-only. Must reflect exactly what CostLedger has recorded — no
fabricated users, costs, or samples.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.main import app
from apps.core.ops.cost_ledger import CostLedger

OWNER_EMAIL = "owner@aria.test"
OTHER_EMAIL = "someone-else@example.com"
# The endpoint queries the ledger with the real current time (no override), so
# seeded records must land in the real current month too, not a fixed date.
NOW = datetime.now(UTC)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_owner():
    with patch("apps.core.auth.owner_emails", return_value={OWNER_EMAIL}):
        yield


def _as(client, email):
    client.cookies.set(auth.USER_COOKIE, auth.sign_user(email, "U", "test"))
    return client


@pytest.fixture
def ledger():
    """A real CostLedger (process-local, no Redis needed) shared across the
    request via get_ledger()."""
    led = CostLedger()
    with patch("apps.core.ops.cost_ledger.get_ledger", return_value=led):
        yield led


def test_telemetry_rejects_non_owner(client, ledger):
    _as(client, OTHER_EMAIL)
    resp = client.get("/admin/api/mission-control/telemetry")
    assert resp.status_code == 403


def test_telemetry_rejects_unauthenticated(client, ledger):
    resp = client.get("/admin/api/mission-control/telemetry")
    assert resp.status_code == 403


def test_telemetry_reflects_real_recorded_costs(client, ledger):
    ledger.record("buyer@example.com", "claude-sonnet-5", 1_000_000, 0, now=NOW)
    with patch("apps.core.main._get_user_plan", return_value="pro"):
        _as(client, OWNER_EMAIL)
        resp = client.get("/admin/api/mission-control/telemetry")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["users"]) == 1
    user = body["users"][0]
    assert user["email"] == "buyer@example.com"
    assert user["plan"] == "pro"
    assert user["month_cost_usd"] == 3.0
    assert user["budget_usd"] == 8.00
    assert user["frozen"] is False
    assert len(body["samples"]) == 1
    assert body["samples"][0]["email"] == "buyer@example.com"


def test_telemetry_marks_frozen_users(client, ledger):
    import asyncio

    ledger.record("frozen@example.com", "claude-sonnet-5", 3_000_000, 0, now=NOW)
    asyncio.run(ledger.freeze("frozen@example.com", now=NOW))

    with patch("apps.core.main._get_user_plan", return_value="pro"):
        _as(client, OWNER_EMAIL)
        resp = client.get("/admin/api/mission-control/telemetry")

    body = resp.json()
    assert body["users"][0]["frozen"] is True


def test_telemetry_marks_users_frozen_only_in_the_shared_store(client, ledger):
    """Regression: the endpoint used to check membership in
    CostLedger.frozen_users() (explicitly local-only — see its docstring),
    so a user frozen by a *different* process (only visible via the shared
    Redis store that is_frozen() checks) was wrongly reported as unfrozen."""
    ledger.record("remotely-frozen@example.com", "claude-sonnet-5", 3_000_000, 0, now=NOW)
    assert "remotely-frozen@example.com" not in ledger.frozen_users()

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value="1")
    with (
        patch("apps.core.main._get_user_plan", return_value="pro"),
        patch("apps.core.memory.redis_client.get_cache", return_value=fake_cache),
    ):
        _as(client, OWNER_EMAIL)
        resp = client.get("/admin/api/mission-control/telemetry")

    body = resp.json()
    assert body["users"][0]["frozen"] is True


def test_telemetry_empty_when_nothing_recorded(client, ledger):
    _as(client, OWNER_EMAIL)
    resp = client.get("/admin/api/mission-control/telemetry")

    assert resp.status_code == 200
    body = resp.json()
    assert body["users"] == []
    assert body["samples"] == []


def test_telemetry_sorts_users_by_cost_descending(client, ledger):
    ledger.record("small@example.com", "claude-sonnet-5", 100_000, 0, now=NOW)
    ledger.record("big@example.com", "claude-sonnet-5", 2_000_000, 0, now=NOW)

    with patch("apps.core.main._get_user_plan", return_value="pro"):
        _as(client, OWNER_EMAIL)
        resp = client.get("/admin/api/mission-control/telemetry")

    emails = [u["email"] for u in resp.json()["users"]]
    assert emails == ["big@example.com", "small@example.com"]
