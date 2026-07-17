"""
HTTP-layer tests for POST /api/v1/workflow (apps/core/main.py).

The engine itself is unit-tested in test_dynamic_workflow.py; here we pin the
*route* contract — the guards that protect a costly multi-agent call:

  - unauthenticated → 401 auth JSON
  - global panic freeze → 503
  - happy path → 200 with the engine's to_dict() payload + processing_time_ms
  - per-client rate limit (6 / 300s) → 429 on the 7th call

The engine is stubbed so no network/LLM calls happen; a signed-in *free* user
is used so the burn-cap/ledger path is skipped (hermetic).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core import main as core_main
from apps.core.main import app

WF_EMAIL = "wf@aria.test"


class _FakeResult:
    def __init__(self, goal: str):
        self._goal = goal

    def to_dict(self) -> dict:
        return {
            "goal": self._goal,
            "ok": True,
            "synthesis": "INTEGRATED ANSWER",
            "subtasks": [
                {"id": "t1", "title": "Analyze", "kind": "reason", "ok": True, "verified": True},
                {"id": "t2", "title": "Draft", "kind": "creative", "ok": True, "repaired": True},
            ],
            "plan_size": 2,
            "total_tokens": 128,
            "duration_ms": 7,
            "started_at": "2026-07-17T00:00:00+00:00",
        }


class _FakeWorkflow:
    async def run(self, goal: str, context=None):
        return _FakeResult(goal)


async def _fake_get_workflow(*args, **kwargs):
    return _FakeWorkflow()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_engine_and_reset(monkeypatch):
    # No network: the route imports get_dynamic_workflow from this module at call
    # time, so patching the attribute here intercepts it.
    monkeypatch.setattr(
        "apps.core.orchestration.dynamic_workflow.get_dynamic_workflow",
        _fake_get_workflow,
    )
    # Deterministic plan lookup + clean rate + panic state each test.
    monkeypatch.setattr(core_main, "_get_user_plan", _async_free)
    core_main._RATE_HITS.clear()
    core_main._PANIC["on"] = False
    yield
    core_main._RATE_HITS.clear()
    core_main._PANIC["on"] = False


async def _async_free(_email: str) -> str:
    return "free"


def _auth_client(client: TestClient) -> TestClient:
    client.cookies.set(auth.USER_COOKIE, auth.sign_user(WF_EMAIL, "W", "free"))
    return client


# ── AUTH ─────────────────────────────────────────────────────────────────────


def test_workflow_requires_auth(client):
    r = client.post("/api/v1/workflow", json={"goal": "do a thing"})
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "auth"


# ── HAPPY PATH ───────────────────────────────────────────────────────────────


def test_workflow_success_shape(client):
    _auth_client(client)
    r = client.post("/api/v1/workflow", json={"goal": "Plan a launch"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["synthesis"] == "INTEGRATED ANSWER"
    assert body["goal"] == "Plan a launch"
    assert len(body["subtasks"]) == 2
    assert body["total_tokens"] == 128
    # The route stamps its own wall-clock on top of the engine payload.
    assert "processing_time_ms" in body
    assert isinstance(body["processing_time_ms"], int)


def test_workflow_passes_goal_through(client):
    _auth_client(client)
    r = client.post("/api/v1/workflow", json={"goal": "unique-goal-42"})
    assert r.json()["goal"] == "unique-goal-42"


# ── PANIC FREEZE ─────────────────────────────────────────────────────────────


def test_workflow_blocked_by_panic(client):
    _auth_client(client)
    core_main._PANIC["on"] = True
    r = client.post("/api/v1/workflow", json={"goal": "do a thing"})
    assert r.status_code == 503
    assert r.json()["error"] == "paused"


# ── RATE LIMIT ───────────────────────────────────────────────────────────────


def test_workflow_rate_limited_after_six(client):
    _auth_client(client)
    # 6 allowed in the window, the 7th is throttled.
    for i in range(6):
        r = client.post("/api/v1/workflow", json={"goal": f"goal {i}"})
        assert r.status_code == 200, f"call {i} should pass"
    r = client.post("/api/v1/workflow", json={"goal": "one too many"})
    assert r.status_code == 429
    assert r.json()["error"] == "rate_limited"
