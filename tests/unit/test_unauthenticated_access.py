"""Regression tests for two critical findings from the QA audit:

1. /api/v1/content/operate (+ /runs, /selftest) had no auth check at all —
   anyone could trigger real AI generation + real external publishing.
2. /ws/chat had no auth check — a free, unauthenticated, unlimited bypass
   of every guard (sign-in, daily quota, burn cap, panic freeze) that
   /api/v1/chat enforces.

Both are now owner-only / sign-in-required respectively.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import apps.core.main as main_module
from apps.core import auth

client = TestClient(main_module.app)


def test_content_operate_rejects_unauthenticated():
    r = client.post("/api/v1/content/operate", json={"product": "Widget"})
    assert r.status_code == 403


def test_content_operate_rejects_non_owner(monkeypatch):
    monkeypatch.setattr(main_module, "_is_owner_user", lambda request: False)
    r = client.post("/api/v1/content/operate", json={"product": "Widget"})
    assert r.status_code == 403


def test_content_operate_allows_owner(monkeypatch):
    monkeypatch.setattr(main_module, "_is_owner_user", lambda request: True)

    async def fake_rate_ok(*a, **k):
        return True

    monkeypatch.setattr(main_module, "_rate_ok", fake_rate_ok)
    fake_operator = AsyncMock()
    fake_operator.run_once = AsyncMock(return_value={"success": True})
    with patch(
        "apps.core.tools.content_operator.get_content_operator", return_value=fake_operator
    ):
        r = client.post("/api/v1/content/operate", json={"product": "Widget"})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_content_runs_and_selftest_reject_unauthenticated():
    assert client.get("/api/v1/content/runs").status_code == 403
    assert client.get("/api/v1/content/selftest").status_code == 403


def test_ws_chat_rejects_unauthenticated():
    with pytest.raises(Exception):  # WebSocketDisconnect on the 4401 close
        with client.websocket_connect("/ws/chat"):
            pass


def test_ws_chat_accepts_authenticated_and_replies(monkeypatch):
    token = auth.sign_user("user@example.com", "User", "google")

    class _Resp:
        text = "hi there"
        caption = ""
        tool_used = "chat"

    fake_mind = AsyncMock()
    fake_mind.handle = AsyncMock(return_value=_Resp())

    async def fake_get_user_plan(email):
        return "free"

    async def fake_consume_quota(email):
        return True, 10

    monkeypatch.setattr(main_module, "_get_user_plan", fake_get_user_plan)
    monkeypatch.setattr(main_module, "_consume_free_quota", fake_consume_quota)
    monkeypatch.setattr(main_module, "_record_ai_cost", AsyncMock())
    with patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind):
        with client.websocket_connect("/ws/chat", cookies={auth.USER_COOKIE: token}) as ws:
            ws.send_text('{"message": "hello", "session_id": "s1"}')
            data = ws.receive_json()
    assert data["reply"] == "hi there"
