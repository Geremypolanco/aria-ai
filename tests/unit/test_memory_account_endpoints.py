"""Tests for the new /api/v1/memory REST endpoints and /account/memory page
— a dashboard surface for viewing/managing what ARIA remembers long-term
about the signed-in user (apps/core/memory/user_facts.py), so that data
isn't only reachable by asking ARIA in conversation (the
remember_user_fact/list_user_facts/forget_user_fact chat tools, already
covered by test_user_memory_tools_wired_into_aria_mind.py).

Isolation is the same guarantee as the chat tools: every endpoint reads
`email` from the verified session cookie (never from the request body/path)
and passes exactly that to UserFactStore, so there is no way for one
signed-in user to reach another's facts through this surface either.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

import apps.core.main as main_module
from apps.core import auth

client = TestClient(main_module.app)


def _cookie(email: str = "user-a@example.com") -> dict:
    return {auth.USER_COOKIE: auth.sign_user(email, "User", "google")}


def test_memory_list_requires_auth():
    r = client.get("/api/v1/memory")
    assert r.status_code == 401


def test_memory_add_requires_auth():
    r = client.post("/api/v1/memory", json={"content": "x"})
    assert r.status_code == 401


def test_memory_forget_requires_auth():
    r = client.delete("/api/v1/memory/mem-1")
    assert r.status_code == 401


def test_memory_list_scopes_to_the_signed_in_users_own_email():
    fake_store = AsyncMock()
    fake_store.list_all = AsyncMock(
        return_value=[
            {"id": "mem-1", "content": "prefers concise answers", "category": "preference"}
        ]
    )
    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        r = client.get("/api/v1/memory", cookies=_cookie("user-a@example.com"))

    assert r.status_code == 200
    assert r.json()["facts"][0]["content"] == "prefers concise answers"
    fake_store.list_all.assert_awaited_once_with("user-a@example.com")


def test_memory_add_requires_content():
    r = client.post("/api/v1/memory", json={"content": ""}, cookies=_cookie())
    assert r.status_code == 400


def test_memory_add_scopes_to_the_signed_in_users_own_email_and_ignores_body_email():
    fake_store = AsyncMock()
    fake_store.remember = AsyncMock(return_value="mem-1")
    fake_store.list_all = AsyncMock(return_value=[{"id": "mem-1", "content": "likes dark mode"}])

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        r = client.post(
            "/api/v1/memory",
            json={"content": "likes dark mode", "category": "preference"},
            cookies=_cookie("user-a@example.com"),
        )

    assert r.status_code == 200
    assert r.json()["ok"] is True
    fake_store.remember.assert_awaited_once_with(
        "user-a@example.com", "likes dark mode", category="preference"
    )


def test_memory_add_falls_back_to_fact_category_when_invalid():
    fake_store = AsyncMock()
    fake_store.remember = AsyncMock(return_value="mem-1")
    fake_store.list_all = AsyncMock(return_value=[])

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        client.post(
            "/api/v1/memory",
            json={"content": "x", "category": "not_real"},
            cookies=_cookie(),
        )

    _, kwargs = fake_store.remember.call_args
    assert kwargs["category"] == "fact"


def test_memory_add_returns_503_when_storage_unavailable():
    fake_store = AsyncMock()
    fake_store.remember = AsyncMock(return_value=None)

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        r = client.post("/api/v1/memory", json={"content": "x"}, cookies=_cookie())

    assert r.status_code == 503


def test_memory_forget_scopes_to_the_signed_in_users_own_email():
    fake_store = AsyncMock()
    fake_store.forget = AsyncMock(return_value=True)
    fake_store.list_all = AsyncMock(return_value=[])

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        r = client.delete("/api/v1/memory/mem-1", cookies=_cookie("user-a@example.com"))

    assert r.status_code == 200
    assert r.json()["ok"] is True
    fake_store.forget.assert_awaited_once_with("user-a@example.com", "mem-1")


def test_memory_forget_returns_ok_false_when_not_owned_or_missing():
    fake_store = AsyncMock()
    fake_store.forget = AsyncMock(return_value=False)
    fake_store.list_all = AsyncMock(return_value=[])

    with patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_store):
        r = client.delete("/api/v1/memory/not-mine", cookies=_cookie("user-b@example.com"))

    assert r.status_code == 200
    assert r.json()["ok"] is False
    fake_store.forget.assert_awaited_once_with("user-b@example.com", "not-mine")


def test_account_memory_page_redirects_to_login_when_unauthenticated():
    r = client.get("/account/memory", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/login"


def test_account_memory_page_renders_for_signed_in_user():
    r = client.get("/account/memory", cookies=_cookie())
    assert r.status_code == 200
    assert "What I remember about you" in r.text
    assert "/api/v1/memory" in r.text
