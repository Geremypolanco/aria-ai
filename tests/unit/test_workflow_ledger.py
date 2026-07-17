"""
Tests for the Deep Workflow usage ledger (apps/core/ops/workflow_ledger.py) and
its HTTP surface GET /api/v1/workflow/runs.

The ledger backs the user's usage panel and the "charge per result" foundation
(deliverables = completed workflows). All in-memory, hermetic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.main import app
from apps.core.ops import workflow_ledger as wl

LED_EMAIL = "led@aria.test"


@pytest.fixture(autouse=True)
def _fresh_ledger(monkeypatch):
    # Each test gets a clean singleton.
    monkeypatch.setattr(wl, "_ledger", wl.WorkflowLedger())
    yield


def _rec(led, email="u@x.co", **kw):
    base = dict(goal="g", subtasks=3, verified=2, repaired=1, tokens=100, duration_ms=500, ok=True)
    base.update(kw)
    led.record(email, **base)


# ── LEDGER ───────────────────────────────────────────────────────────────────


def test_stats_aggregate():
    led = wl.get_workflow_ledger()
    _rec(led, subtasks=4, verified=3, tokens=200, ok=True)
    _rec(led, subtasks=2, verified=1, tokens=50, ok=False)
    s = led.stats("u@x.co")
    assert s["workflows"] == 2
    assert s["deliverables"] == 1  # only the ok=True one counts as delivered
    assert s["subagents"] == 6
    assert s["verified"] == 4
    assert s["tokens"] == 250
    assert s["verify_rate_pct"] == round(4 / 6 * 100)


def test_recent_is_newest_first():
    led = wl.get_workflow_ledger()
    _rec(led, goal="first")
    _rec(led, goal="second")
    recent = led.recent("u@x.co", 10)
    assert [r["goal"] for r in recent] == ["second", "first"]


def test_users_are_isolated():
    led = wl.get_workflow_ledger()
    _rec(led, email="a@x.co")
    _rec(led, email="b@x.co")
    _rec(led, email="b@x.co")
    assert led.stats("a@x.co")["workflows"] == 1
    assert led.stats("b@x.co")["workflows"] == 2


def test_ring_buffer_caps_history():
    led = wl.get_workflow_ledger()
    for i in range(wl.MAX_RUNS_PER_USER + 25):
        _rec(led, goal=f"g{i}")
    # workflows counter reflects only what is retained (the cap), not all-time.
    assert led.stats("u@x.co")["workflows"] == wl.MAX_RUNS_PER_USER


def test_empty_user_stats_are_zero():
    led = wl.get_workflow_ledger()
    s = led.stats("nobody@x.co")
    assert s == {
        "deliverables": 0,
        "workflows": 0,
        "subagents": 0,
        "verified": 0,
        "verify_rate_pct": 0,
        "tokens": 0,
    }


def test_goal_is_truncated():
    led = wl.get_workflow_ledger()
    _rec(led, goal="x" * 500)
    assert len(led.recent("u@x.co")[0]["goal"]) <= 160


# ── ENDPOINT ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(app)


def test_runs_requires_auth(client):
    r = client.get("/api/v1/workflow/runs")
    assert r.status_code == 401
    assert r.json()["error"] == "auth"


def test_runs_returns_stats_and_runs(client):
    # Seed the shared singleton the endpoint reads.
    led = wl.get_workflow_ledger()
    led.record(
        LED_EMAIL,
        goal="deep goal",
        subtasks=3,
        verified=3,
        repaired=0,
        tokens=90,
        duration_ms=1,
        ok=True,
    )
    client.cookies.set(auth.USER_COOKIE, auth.sign_user(LED_EMAIL, "L", "free"))
    r = client.get("/api/v1/workflow/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["stats"]["deliverables"] == 1
    assert body["stats"]["subagents"] == 3
    assert len(body["runs"]) == 1
    assert body["runs"][0]["goal"] == "deep goal"
