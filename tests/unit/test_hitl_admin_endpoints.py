"""HTTP-layer tests for the Mission Control HITL admin endpoints
(apps/core/main.py):

  GET  /admin/api/mission-control/hitl/queue
  POST /admin/api/mission-control/hitl/{request_id}/decision

Both are owner-only. approve/modify must actually execute the queued tool
call (via AriaMind._execute_tool) and push the outcome into the user's own
chat history — never fabricate a result. deny must never execute anything.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.main import app
from apps.core.safety.hitl_queue import HitlQueueStore

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


@pytest.fixture
def queue():
    """A real HitlQueueStore (process-local, no Redis needed) shared across
    the request via get_hitl_queue()."""
    store = HitlQueueStore()
    with patch("apps.core.safety.hitl_queue.get_hitl_queue", return_value=store):
        yield store


def test_hitl_queue_rejects_non_owner(client, queue):
    _as(client, OTHER_EMAIL)
    resp = client.get("/admin/api/mission-control/hitl/queue")
    assert resp.status_code == 403


def test_hitl_queue_rejects_unauthenticated(client, queue):
    resp = client.get("/admin/api/mission-control/hitl/queue")
    assert resp.status_code == 403


def test_hitl_queue_returns_pending_requests(client, queue):
    import asyncio

    asyncio.run(
        queue.enqueue(
            chat_id="chat-1",
            email="buyer@example.com",
            user_text="buy video credits",
            tool="provision_b2b_payment",
            tool_args={"amount_usd": 1200},
            risk_score=0.81,
            risk_reason="unfamiliar vendor",
        )
    )
    _as(client, OWNER_EMAIL)
    resp = client.get("/admin/api/mission-control/hitl/queue")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["requests"]) == 1
    assert body["requests"][0]["tool"] == "provision_b2b_payment"
    assert body["requests"][0]["status"] == "pending"


def test_decision_rejects_non_owner(client, queue):
    _as(client, OTHER_EMAIL)
    resp = client.post(
        "/admin/api/mission-control/hitl/req_x/decision", json={"decision": "approve"}
    )
    assert resp.status_code == 403


def test_decision_rejects_invalid_decision_value(client, queue):
    _as(client, OWNER_EMAIL)
    resp = client.post("/admin/api/mission-control/hitl/req_x/decision", json={"decision": "yolo"})
    assert resp.status_code == 400


def test_decision_returns_409_for_unknown_request(client, queue):
    _as(client, OWNER_EMAIL)
    resp = client.post(
        "/admin/api/mission-control/hitl/req_doesnotexist/decision",
        json={"decision": "approve"},
    )
    assert resp.status_code == 409


def test_approve_executes_the_real_tool_and_records_the_actual_result(client, queue):
    import asyncio

    req = asyncio.run(
        queue.enqueue(
            chat_id="chat-1",
            email="buyer@example.com",
            user_text="launch the flash sale",
            tool="create_flash_sale",
            tool_args={"name": "Weekend Blowout", "discount_pct": 0.25},
            risk_score=0.65,
            risk_reason="first flash sale over 20%",
        )
    )

    fake_mind = AsyncMock()
    fake_mind._execute_tool = AsyncMock(
        return_value=("Flash sale 'Weekend Blowout' created (id: sale_9).", {})
    )
    fake_mind._synthesize = AsyncMock(
        return_value="Your Weekend Blowout flash sale is live — 25% off, id sale_9."
    )
    fake_mind._looks_like_failure = lambda obs: False
    fake_mind._record_exec = AsyncMock()
    fake_mind._store_interaction = AsyncMock()

    _as(client, OWNER_EMAIL)
    with patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind):
        resp = client.post(
            f"/admin/api/mission-control/hitl/{req.request_id}/decision",
            json={"decision": "approve"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"

    fake_mind._execute_tool.assert_awaited_once_with(
        "create_flash_sale",
        {"name": "Weekend Blowout", "discount_pct": 0.25},
        email="buyer@example.com",
    )
    fake_mind._store_interaction.assert_awaited_once()
    stored_args = fake_mind._store_interaction.call_args.args
    assert stored_args[0] == "chat-1"
    assert "Weekend Blowout" in stored_args[2]

    resolved = asyncio.run(queue.get(req.request_id))
    assert resolved.status == "approved"
    assert "sale_9" in resolved.result_text


def test_modify_executes_with_the_modified_args_not_the_original():
    import asyncio

    store = HitlQueueStore()
    req = asyncio.run(
        store.enqueue(
            chat_id="chat-1",
            email="buyer@example.com",
            user_text="spend on ads",
            tool="provision_virtual_card",
            tool_args={"limit_usd": 500},
            risk_score=0.55,
            risk_reason="first use of this vendor",
        )
    )

    fake_mind = AsyncMock()
    fake_mind._execute_tool = AsyncMock(return_value=("Card provisioned.", {}))
    fake_mind._synthesize = AsyncMock(return_value="Card provisioned with a $150 limit.")
    fake_mind._looks_like_failure = lambda obs: False
    fake_mind._record_exec = AsyncMock()
    fake_mind._store_interaction = AsyncMock()

    client = TestClient(app)
    with (
        patch("apps.core.auth.owner_emails", return_value={OWNER_EMAIL}),
        patch("apps.core.safety.hitl_queue.get_hitl_queue", return_value=store),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
    ):
        _as(client, OWNER_EMAIL)
        resp = client.post(
            f"/admin/api/mission-control/hitl/{req.request_id}/decision",
            json={"decision": "modify", "modified_args": {"limit_usd": 150}},
        )

    assert resp.status_code == 200
    fake_mind._execute_tool.assert_awaited_once_with(
        "provision_virtual_card", {"limit_usd": 150}, email="buyer@example.com"
    )


def test_deny_never_executes_the_tool(client, queue):
    import asyncio

    req = asyncio.run(
        queue.enqueue(
            chat_id="chat-1",
            email="buyer@example.com",
            user_text="spend on ads",
            tool="provision_virtual_card",
            tool_args={"limit_usd": 500},
            risk_score=0.9,
            risk_reason="way over normal spend",
        )
    )

    fake_mind = AsyncMock()
    fake_mind._store_interaction = AsyncMock()

    _as(client, OWNER_EMAIL)
    with patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind):
        resp = client.post(
            f"/admin/api/mission-control/hitl/{req.request_id}/decision",
            json={"decision": "deny", "note": "vendor not vetted"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "denied"
    fake_mind._execute_tool.assert_not_called()
    fake_mind._store_interaction.assert_awaited_once()
    stored_args = fake_mind._store_interaction.call_args.args
    assert "vendor not vetted" in stored_args[2]

    resolved = asyncio.run(queue.get(req.request_id))
    assert resolved.status == "denied"
    assert resolved.tool_args == {"limit_usd": 500}  # untouched by a denial


def test_double_resolve_second_call_returns_409(client, queue):
    import asyncio

    req = asyncio.run(
        queue.enqueue(
            chat_id="chat-1",
            email="buyer@example.com",
            user_text="x",
            tool="create_flash_sale",
            tool_args={},
            risk_score=0.6,
            risk_reason="r",
        )
    )
    fake_mind = AsyncMock()
    fake_mind._execute_tool = AsyncMock(return_value=("done", {}))
    fake_mind._synthesize = AsyncMock(return_value="done")
    fake_mind._looks_like_failure = lambda obs: False

    _as(client, OWNER_EMAIL)
    with patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind):
        first = client.post(
            f"/admin/api/mission-control/hitl/{req.request_id}/decision",
            json={"decision": "approve"},
        )
        second = client.post(
            f"/admin/api/mission-control/hitl/{req.request_id}/decision",
            json={"decision": "approve"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
