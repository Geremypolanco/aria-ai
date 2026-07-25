"""HTTP-layer tests for the Mission Control memory-inspector admin endpoint
(apps/core/main.py):

  GET /admin/api/mission-control/memory/{email}

Owner-only, read-only. Must reflect exactly what each real memory source
returns (thread history/state, cross-thread episodic recall, durable facts,
and the two global stores) — nothing fabricated, nothing edited.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.core import auth
from apps.core.main import app

OWNER_EMAIL = "owner@aria.test"
OTHER_EMAIL = "someone-else@example.com"
TARGET_EMAIL = "buyer@example.com"


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
def fake_mind():
    mind = AsyncMock()
    mind._load_history = AsyncMock(return_value=[{"role": "user", "content": "hi"}])
    mind._load_state = AsyncMock(return_value={"focus": "pricing", "confidence": 0.8})
    mind._load_goals = AsyncMock(return_value=[{"text": "grow revenue", "priority": 5}])
    mind._load_learned = AsyncMock(return_value=["never discount below cost"])
    with patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=mind):
        yield mind


@pytest.fixture
def fake_episodic():
    ep = AsyncMock()
    ep.get_recent = AsyncMock(return_value=[{"type": "conversation", "content": "asked about SEO"}])
    with patch("apps.core.cognition.episodic_memory.get_episodic_memory", return_value=ep):
        yield ep


@pytest.fixture
def fake_facts():
    store = AsyncMock()
    store.list_all = AsyncMock(
        return_value=[
            {"id": "mem-1", "content": "prefers email over Slack", "category": "preference"}
        ]
    )
    with patch("apps.core.memory.user_facts.get_user_facts", return_value=store):
        yield store


def test_memory_inspector_rejects_non_owner(client, fake_mind, fake_episodic, fake_facts):
    _as(client, OTHER_EMAIL)
    resp = client.get(f"/admin/api/mission-control/memory/{TARGET_EMAIL}")
    assert resp.status_code == 403


def test_memory_inspector_rejects_unauthenticated(client, fake_mind, fake_episodic, fake_facts):
    resp = client.get(f"/admin/api/mission-control/memory/{TARGET_EMAIL}")
    assert resp.status_code == 403


def test_memory_inspector_assembles_all_real_sources(client, fake_mind, fake_episodic, fake_facts):
    _as(client, OWNER_EMAIL)
    resp = client.get(f"/admin/api/mission-control/memory/{TARGET_EMAIL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == TARGET_EMAIL
    assert body["conversation_id"] == f"u:{TARGET_EMAIL}"
    assert body["thread"]["history"] == [{"role": "user", "content": "hi"}]
    assert body["thread"]["state"]["focus"] == "pricing"
    assert body["episodic"] == [{"type": "conversation", "content": "asked about SEO"}]
    assert body["facts"][0]["content"] == "prefers email over Slack"
    assert body["global"]["goals"] == [{"text": "grow revenue", "priority": 5}]
    assert body["global"]["learned"] == ["never discount below cost"]
    assert "not scoped to this email" in body["note"]


def test_memory_inspector_normalizes_email_case(client, fake_mind, fake_episodic, fake_facts):
    _as(client, OWNER_EMAIL)
    resp = client.get(f"/admin/api/mission-control/memory/{TARGET_EMAIL.upper()}")

    assert resp.status_code == 200
    assert resp.json()["email"] == TARGET_EMAIL
    fake_episodic.get_recent.assert_awaited_once_with(TARGET_EMAIL, n=20)
    fake_facts.list_all.assert_awaited_once_with(TARGET_EMAIL, limit=50)


def test_memory_inspector_reflects_empty_sources_honestly(client):
    empty_mind = AsyncMock()
    empty_mind._load_history = AsyncMock(return_value=[])
    empty_mind._load_state = AsyncMock(return_value={"focus": "", "confidence": 0.7})
    empty_mind._load_goals = AsyncMock(return_value=[])
    empty_mind._load_learned = AsyncMock(return_value=[])
    empty_episodic = AsyncMock()
    empty_episodic.get_recent = AsyncMock(return_value=[])
    empty_facts = AsyncMock()
    empty_facts.list_all = AsyncMock(return_value=[])

    with (
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=empty_mind),
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory", return_value=empty_episodic
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=empty_facts),
    ):
        _as(client, OWNER_EMAIL)
        resp = client.get(f"/admin/api/mission-control/memory/{TARGET_EMAIL}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["thread"]["history"] == []
    assert body["episodic"] == []
    assert body["facts"] == []
    assert body["global"]["goals"] == []
    assert body["global"]["learned"] == []
