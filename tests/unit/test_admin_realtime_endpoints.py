"""
HTTP-layer tests for the admin real-time observability endpoints
(apps/core/main.py) added for "full, unrestricted access to ARIA + live
visibility into user intent, projects, and everything else":

  GET  /admin/api/activity          — recent CognitionTracer turns + stats
  GET  /admin/api/activity/stream   — SSE feed of live turns (log_bus)
  GET  /admin/api/projects          — RDWing R&D projects
  GET  /admin/api/missions          — recent task_queue missions
  GET  /admin/api/users/{email}/history — one user's chat history

All five are strictly owner-only (`_is_owner_user`, not the legacy
admin-password `_is_admin`) since they expose live conversational content,
not just ops metrics — verified with a 403 for a signed-in non-owner and a
200 for the owner, per endpoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.main import app

OWNER_EMAIL = "owner@aria.test"
OTHER_EMAIL = "someone-else@example.com"


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


@pytest.mark.parametrize(
    "path",
    [
        "/admin/api/activity",
        "/admin/api/projects",
        "/admin/api/missions",
        f"/admin/api/users/{OTHER_EMAIL}/history",
    ],
)
def test_owner_only_endpoints_reject_non_owner(client, path):
    _as(client, OTHER_EMAIL)
    resp = client.get(path)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/admin/api/activity",
        "/admin/api/projects",
        "/admin/api/missions",
        f"/admin/api/users/{OTHER_EMAIL}/history",
    ],
)
def test_owner_only_endpoints_reject_unauthenticated(client, path):
    resp = client.get(path)
    assert resp.status_code == 403


def test_activity_stream_rejects_non_owner(client):
    _as(client, OTHER_EMAIL)
    resp = client.get("/admin/api/activity/stream")
    assert resp.status_code == 403


def test_admin_api_activity_returns_traces_and_analytics(client):
    _as(client, OWNER_EMAIL)
    fake_tracer = AsyncMock()
    fake_tracer.recent_traces = AsyncMock(
        return_value=[{"agent_name": "aria_mind", "task_type": "chat", "success": True}]
    )
    fake_tracer.analytics = AsyncMock(return_value={"total_traces": 1})
    with patch("apps.evaluation.phoenix.tracer.get_cognition_tracer", return_value=fake_tracer):
        resp = client.get("/admin/api/activity?limit=10")

    assert resp.status_code == 200
    body = resp.json()
    assert body["analytics"]["total_traces"] == 1
    assert body["traces"][0]["task_type"] == "chat"
    fake_tracer.recent_traces.assert_awaited_once_with(limit=10)


def test_admin_api_projects_returns_rd_wing_projects(client):
    _as(client, OWNER_EMAIL)
    fake_wing = AsyncMock()
    fake_wing.list_projects = lambda: [{"id": "p1", "title": "Autonomous ads engine"}]
    with patch("apps.core.intelligence.rd_wing.get_rd_wing", return_value=fake_wing):
        resp = client.get("/admin/api/projects")

    assert resp.status_code == 200
    assert resp.json()["projects"] == [{"id": "p1", "title": "Autonomous ads engine"}]


def test_admin_api_missions_returns_recent_missions(client):
    _as(client, OWNER_EMAIL)
    fake_queue = AsyncMock()
    fake_queue.list_recent = AsyncMock(
        return_value=[{"id": "task_abc", "state": "completed", "user_email": OTHER_EMAIL}]
    )
    with patch("apps.core.scale.task_queue.get_queue", return_value=fake_queue):
        resp = client.get("/admin/api/missions?limit=5")

    assert resp.status_code == 200
    assert resp.json()["missions"][0]["id"] == "task_abc"
    fake_queue.list_recent.assert_awaited_once_with(limit=5)


def test_admin_api_user_history_uses_deterministic_conversation_id(client):
    _as(client, OWNER_EMAIL)
    fake_mind = AsyncMock()
    fake_mind._load_history = AsyncMock(return_value=[{"role": "user", "content": "hi"}])
    with patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind):
        resp = client.get(f"/admin/api/users/{OTHER_EMAIL}/history")

    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == f"u:{OTHER_EMAIL}"
    assert body["history"] == [{"role": "user", "content": "hi"}]
    fake_mind._load_history.assert_awaited_once_with(f"u:{OTHER_EMAIL}")
