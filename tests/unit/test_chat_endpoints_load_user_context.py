"""Regression test: apps/core/main.py's HTTP /api/v1/chat already loaded
long-term memory context before calling AriaMind.handle(), but /ws/chat
(the WebSocket twin) never did — WebSocket users got no memory injection at
all. Both entrypoints now call the shared
apps.core.memory.context_loader.load_user_context(), scoped to the
authenticated caller's own email, before handle().

Exercised through the real FastAPI app (TestClient), the way
test_unauthenticated_access.py already tests /ws/chat auth, so this covers
the actual wiring rather than just the helper function in isolation
(covered separately in test_context_loader.py).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import apps.core.main as main_module
from apps.core import auth

client = TestClient(main_module.app)


class _Resp:
    text = "hi there"
    caption = ""
    tool_used = "chat"
    image_bytes = None


def test_ws_chat_loads_user_context_scoped_to_caller_email(monkeypatch):
    token = auth.sign_user("user-a@example.com", "User A", "google")

    fake_mind = AsyncMock()
    fake_mind.handle = AsyncMock(return_value=_Resp())

    async def fake_get_user_plan(email):
        return "free"

    async def fake_consume_quota(email):
        return True, 10

    fake_load_context = AsyncMock(
        return_value="[What I remember about this user:\n- likes concise replies]"
    )

    monkeypatch.setattr(main_module, "_get_user_plan", fake_get_user_plan)
    monkeypatch.setattr(main_module, "_consume_free_quota", fake_consume_quota)
    monkeypatch.setattr(main_module, "_record_ai_cost", AsyncMock())
    with (
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
        patch("apps.core.memory.context_loader.load_user_context", fake_load_context),
    ):
        with client.websocket_connect("/ws/chat", cookies={auth.USER_COOKIE: token}) as ws:
            ws.send_text('{"message": "what do you know about me", "session_id": "s1"}')
            data = ws.receive_json()

    assert data["reply"] == "hi there"
    fake_load_context.assert_awaited_once_with("user-a@example.com", "what do you know about me")
    # The recalled memory must actually reach AriaMind.handle() as user_context.
    _, kwargs = fake_mind.handle.call_args
    assert kwargs["user_context"] == "[What I remember about this user:\n- likes concise replies]"
    assert kwargs["email"] == "user-a@example.com"


def test_ws_chat_skips_context_loading_when_load_fails(monkeypatch):
    """load_user_context() is designed to swallow its own errors and return
    "" rather than raise — this locks in that a WS chat turn still completes
    even if that contract were ever violated by a future change."""
    token = auth.sign_user("user-b@example.com", "User B", "google")

    fake_mind = AsyncMock()
    fake_mind.handle = AsyncMock(return_value=_Resp())

    async def fake_get_user_plan(email):
        return "free"

    async def fake_consume_quota(email):
        return True, 10

    monkeypatch.setattr(main_module, "_get_user_plan", fake_get_user_plan)
    monkeypatch.setattr(main_module, "_consume_free_quota", fake_consume_quota)
    monkeypatch.setattr(main_module, "_record_ai_cost", AsyncMock())
    with (
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
        patch(
            "apps.core.memory.context_loader.load_user_context",
            AsyncMock(return_value=""),
        ),
    ):
        with client.websocket_connect("/ws/chat", cookies={auth.USER_COOKIE: token}) as ws:
            ws.send_text('{"message": "hello", "session_id": "s1"}')
            data = ws.receive_json()

    assert data["reply"] == "hi there"
