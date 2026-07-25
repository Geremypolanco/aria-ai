"""Regression test: the Guardrails kill switch (apps/core/safety/guardrails.py
Layer 4) gates the same HTTP request paths as the existing Global Panic
button, via apps.core.main._is_globally_frozen(). Two independent freeze
mechanisms — a manual, in-process-only Global Panic and a Redis-persisted
kill switch that can trip itself (KillSwitch.record_and_check_anomaly) — on
purpose: either one halts execution, so a bug in one doesn't remove the
other.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth, main as core_main
from apps.core.main import app


@pytest.fixture(autouse=True)
def _reset_panic():
    core_main._PANIC["on"] = False
    yield
    core_main._PANIC["on"] = False


@pytest.mark.asyncio
async def test_is_globally_frozen_false_by_default():
    with patch("apps.core.safety.guardrails.get_kill_switch") as mock_ks:
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        assert await core_main._is_globally_frozen() is False


@pytest.mark.asyncio
async def test_is_globally_frozen_true_when_panic_flag_set():
    core_main._PANIC["on"] = True
    with patch("apps.core.safety.guardrails.get_kill_switch") as mock_ks:
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        assert await core_main._is_globally_frozen() is True


@pytest.mark.asyncio
async def test_is_globally_frozen_true_when_kill_switch_active_without_panic():
    """The kill switch alone (no manual panic) must be enough to freeze —
    this is what lets the anomaly watcher auto-freeze without a human
    having clicked Global Panic."""
    with patch("apps.core.safety.guardrails.get_kill_switch") as mock_ks:
        mock_ks.return_value.is_active = AsyncMock(return_value=True)
        assert await core_main._is_globally_frozen() is True


@pytest.mark.asyncio
async def test_is_globally_frozen_fails_open_on_kill_switch_error():
    """A broken safety check must not itself 503 every user — Global Panic
    remains the reliable fallback."""
    with patch(
        "apps.core.safety.guardrails.get_kill_switch", side_effect=RuntimeError("redis down")
    ):
        assert await core_main._is_globally_frozen() is False


def test_admin_overview_surfaces_guardrails_killswitch_field():
    client = TestClient(app)
    owner_email = "owner@aria.test"
    with (
        patch("apps.core.auth.owner_emails", return_value={owner_email}),
        patch("apps.core.safety.guardrails.get_kill_switch") as mock_ks,
    ):
        mock_ks.return_value.is_active = AsyncMock(return_value=False)
        client.cookies.set(auth.USER_COOKIE, auth.sign_user(owner_email, "Owner", "test"))
        resp = client.get("/admin/api/overview")

    assert resp.status_code == 200
    assert "guardrails_killswitch" in resp.json()
