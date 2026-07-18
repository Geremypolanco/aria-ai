"""
Tests for real email+password accounts (apps/core/auth_accounts.py) and the
/signup + /login routes — the change that lets any user actually create an
account and reach the dashboard (no more waitlist / GitHub-only).

A fake in-memory cache stands in for Redis, so everything is hermetic.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.core import auth, auth_accounts
from apps.core import main as core_main
from apps.core.main import app


class FakeCache:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list] = {}

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ttl_seconds=None):
        self.kv[key] = value

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)


@pytest.fixture(autouse=True)
def _fake_cache(monkeypatch):
    cache = FakeCache()
    # Both auth_accounts and auth.remember_user resolve the cache via this import.
    monkeypatch.setattr("apps.core.memory.redis_client.get_cache", lambda: cache)
    core_main._RATE_HITS.clear()
    yield cache
    core_main._RATE_HITS.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ── ACCOUNT STORE ────────────────────────────────────────────────────────────


async def test_create_and_verify(_fake_cache):
    ok, err = await auth_accounts.create_account("New@Aria.Test", "hunter2pass", "Neo")
    assert ok and err == ""
    assert await auth_accounts.account_exists("new@aria.test")  # normalized
    prof = await auth_accounts.verify_credentials("new@aria.test", "hunter2pass")
    assert prof == {"email": "new@aria.test", "name": "Neo", "provider": "email"}


async def test_wrong_password_rejected(_fake_cache):
    await auth_accounts.create_account("u@aria.test", "correcthorse", "U")
    assert await auth_accounts.verify_credentials("u@aria.test", "wrong") is None


async def test_unknown_user_rejected(_fake_cache):
    assert await auth_accounts.verify_credentials("ghost@aria.test", "whatever") is None


async def test_duplicate_rejected(_fake_cache):
    ok1, _ = await auth_accounts.create_account("dup@aria.test", "password1", "A")
    ok2, err2 = await auth_accounts.create_account("dup@aria.test", "password2", "B")
    assert ok1 is True
    assert ok2 is False and "already" in err2.lower()


async def test_weak_password_rejected(_fake_cache):
    ok, err = await auth_accounts.create_account("w@aria.test", "short", "W")
    assert ok is False and "8" in err


async def test_bad_email_rejected(_fake_cache):
    ok, err = await auth_accounts.create_account("not-an-email", "password1", "X")
    assert ok is False and "valid email" in err.lower()


async def test_password_hash_is_salted(_fake_cache):
    await auth_accounts.create_account("h@aria.test", "password1", "H")
    raw = await _fake_cache.get("aria:account:h@aria.test")
    rec = json.loads(raw)
    assert rec["pwhash"] != "password1"  # never stored in the clear
    assert len(rec["salt"]) >= 16


# ── ROUTES ───────────────────────────────────────────────────────────────────


def test_signup_page_has_password_form(client):
    r = client.get("/signup")
    assert r.status_code == 200
    assert 'name="password"' in r.text and 'name="email"' in r.text


def test_signup_creates_account_and_signs_in(client):
    r = client.post(
        "/signup",
        data={"name": "Founder", "email": "founder@aria.test", "password": "launchit123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/app"
    assert auth.USER_COOKIE in r.headers.get("set-cookie", "")


def test_signup_duplicate_shows_error(client):
    data = {"name": "A", "email": "again@aria.test", "password": "password12"}
    client.post("/signup", data=data, follow_redirects=False)
    r2 = client.post("/signup", data=data, follow_redirects=False)
    assert r2.status_code == 400
    assert "already" in r2.text.lower()


def test_login_with_valid_credentials(client):
    client.post(
        "/signup",
        data={"name": "L", "email": "loginok@aria.test", "password": "password12"},
        follow_redirects=False,
    )
    r = client.post(
        "/login",
        data={"email": "loginok@aria.test", "password": "password12"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/app"
    assert auth.USER_COOKIE in r.headers.get("set-cookie", "")


def test_login_wrong_password_401(client):
    client.post(
        "/signup",
        data={"name": "L", "email": "loginbad@aria.test", "password": "password12"},
        follow_redirects=False,
    )
    r = client.post(
        "/login",
        data={"email": "loginbad@aria.test", "password": "nope"},
        follow_redirects=False,
    )
    assert r.status_code == 401
    assert "wrong email or password" in r.text.lower()
