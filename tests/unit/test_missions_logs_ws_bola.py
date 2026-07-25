"""Regression test: /ws/logs/{task_id} authenticated but never checked
ownership — any signed-in user who obtained a task_id (unguessable, but
that's not the same as authorized) could read another user's live mission
logs. GET /api/v1/missions/{id} already enforced this; the WebSocket sibling
now matches it.

Also covers a second bug: both endpoints' owner-bypass checked only
settings.OWNER_EMAIL directly instead of auth.is_owner_email()/
auth.owner_emails() — a second, driftable source of truth. An owner listed
only in auth.OWNER_EMAILS (not settings.OWNER_EMAIL) would incorrectly get
a 403/4403 on someone else's mission despite being a real owner everywhere
else in the app (aria_mind.py's _OWNER_ONLY_TOOLS, etc.)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import apps.core.main as main_module
from apps.core import auth

client = TestClient(main_module.app)


def test_logs_ws_rejects_a_different_users_mission(monkeypatch):
    owner_token = auth.sign_user("owner-of-task@example.com", "Owner", "google")
    other_token = auth.sign_user("someone-else@example.com", "Other", "google")

    async def fake_status(task_id):
        return {"id": task_id, "user_email": "owner-of-task@example.com", "state": "running"}

    with patch("apps.core.routes.missions.get_queue") as get_queue:
        get_queue.return_value.get_status = AsyncMock(side_effect=fake_status)
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/ws/logs/task_abc123", cookies={auth.USER_COOKIE: other_token}
            ):
                pass


def test_logs_ws_allows_the_owning_user():
    owner_token = auth.sign_user("owner-of-task@example.com", "Owner", "google")

    async def fake_status(task_id):
        return {"id": task_id, "user_email": "owner-of-task@example.com", "state": "running"}

    async def fake_subscribe(task_id):
        yield "line one"

    with (
        patch("apps.core.routes.missions.get_queue") as get_queue,
        patch("apps.core.scale.log_bus.subscribe", fake_subscribe),
    ):
        get_queue.return_value.get_status = AsyncMock(side_effect=fake_status)
        with client.websocket_connect(
            "/ws/logs/task_abc123", cookies={auth.USER_COOKIE: owner_token}
        ) as ws:
            assert ws.receive_text() == "line one"


def test_logs_ws_allows_an_owner_listed_only_in_auth_owner_emails():
    """auth.OWNER_EMAILS (not settings.OWNER_EMAIL) is the other legitimate
    source of ownership — the fix must recognize it too, not just the
    settings-configured address."""
    owner_email = next(iter(auth.OWNER_EMAILS))
    owner_token = auth.sign_user(owner_email, "Owner", "google")

    async def fake_status(task_id):
        return {"id": task_id, "user_email": "someone-else@example.com", "state": "running"}

    async def fake_subscribe(task_id):
        yield "line one"

    with (
        patch("apps.core.routes.missions.get_queue") as get_queue,
        patch("apps.core.scale.log_bus.subscribe", fake_subscribe),
    ):
        get_queue.return_value.get_status = AsyncMock(side_effect=fake_status)
        with client.websocket_connect(
            "/ws/logs/task_abc123", cookies={auth.USER_COOKIE: owner_token}
        ) as ws:
            assert ws.receive_text() == "line one"


def test_mission_status_allows_an_owner_listed_only_in_auth_owner_emails():
    owner_email = next(iter(auth.OWNER_EMAILS))
    owner_token = auth.sign_user(owner_email, "Owner", "google")

    async def fake_status(task_id):
        return {
            "user_email": "someone-else@example.com",
            "state": "done",
            "result": "ok",
            "error": None,
        }

    with patch("apps.core.routes.missions.get_queue") as get_queue:
        get_queue.return_value.get_status = AsyncMock(side_effect=fake_status)
        resp = client.get("/api/v1/missions/task_abc123", cookies={auth.USER_COOKIE: owner_token})

    assert resp.status_code == 200
