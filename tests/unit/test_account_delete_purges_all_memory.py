"""Regression test: /api/v1/account/delete only ever cleared profile, plan,
and connector OAuth tokens — a deleted account's conversation history
(aria_mind.py's own K_HISTORY, every session variant) and long-term memory
(episodic_memory.py + the new user_facts.py) silently outlived the account
itself, in both Redis and Supabase. This is the closest thing the app has to
a single "forget everything about me" action (forget_user_fact only ever
deletes one fact at a time).

Covers three layers:
  1. EpisodicMemory.forget_all() — new method, deletes the Redis list +
     best-effort Supabase mirror for one user.
  2. UserFactStore.forget_all() — new method, deletes every Supabase row
     for one user.
  3. The /api/v1/account/delete endpoint itself — must call both of the
     above, AND discover + clear every chat-history variant for the
     caller's email (default conversation + any custom session_id), scoped
     to the caller's own email only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

import apps.core.main as main_module
from apps.core import auth

client = TestClient(main_module.app)


def _cookie(email: str = "user-a@example.com") -> dict:
    return {auth.USER_COOKIE: auth.sign_user(email, "User", "google")}


class _FakeCache:
    def __init__(self):
        self._store: dict = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ttl_seconds=3600):
        self._store[key] = value
        return True

    async def delete(self, key):
        self._store.pop(key, None)
        return True

    async def scan_keys(self, pattern, limit=1000):
        prefix = pattern.rstrip("*")
        return [k for k in self._store if k.startswith(prefix)][:limit]


# ── EpisodicMemory.forget_all() ────────────────────────────────────────
@pytest.mark.asyncio
async def test_episodic_memory_forget_all_clears_the_redis_list():
    from apps.core.cognition.episodic_memory import EpisodicMemory

    cache = _FakeCache()
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        mem = EpisodicMemory()
        await mem.store_conversation("user-a@example.com", "hi", "hello")
        assert await mem.get_recent("user-a@example.com", n=10)

        ok = await mem.forget_all("user-a@example.com")

        assert ok is True
        assert await mem.get_recent("user-a@example.com", n=10) == []


@pytest.mark.asyncio
async def test_episodic_memory_forget_all_requires_user_id():
    from apps.core.cognition.episodic_memory import EpisodicMemory

    mem = EpisodicMemory()
    assert await mem.forget_all("") is False


@pytest.mark.asyncio
async def test_episodic_memory_forget_all_deletes_supabase_mirror_scoped_to_user():
    from apps.core.cognition.episodic_memory import EpisodicMemory

    fake_db = MagicMock()
    cache = _FakeCache()
    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        mem = EpisodicMemory()
        await mem.forget_all("user-a@example.com")

    fake_db.table.assert_called_with("aria_episodic_memory")
    fake_db.table.return_value.delete.return_value.eq.assert_called_with(
        "user_id", "user-a@example.com"
    )


# ── UserFactStore.forget_all() ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_user_facts_forget_all_requires_user_id():
    from apps.core.memory.user_facts import UserFactStore

    store = UserFactStore()
    with patch.multiple(
        "apps.core.memory.user_facts.settings",
        SUPABASE_URL="https://fake.supabase.co",
        SUPABASE_KEY="fake-key",
    ):
        assert await store.forget_all("") is False


@pytest.mark.asyncio
async def test_user_facts_forget_all_scopes_delete_to_user_id():
    from apps.core.memory.user_facts import UserFactStore

    fake_db = MagicMock()
    store = UserFactStore()
    with (
        patch.multiple(
            "apps.core.memory.user_facts.settings",
            SUPABASE_URL="https://fake.supabase.co",
            SUPABASE_KEY="fake-key",
        ),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_db),
    ):
        ok = await store.forget_all("user-a@example.com")

    assert ok is True
    fake_db.table.assert_called_with("aria_user_memories")
    fake_db.table.return_value.delete.return_value.eq.assert_called_with(
        "user_id", "user-a@example.com"
    )


# ── /api/v1/account/delete wiring ────────────────────────────────────────
def test_delete_account_requires_auth():
    r = client.post("/api/v1/account/delete")
    assert r.json()["ok"] is False


def test_delete_account_purges_episodic_and_fact_memory_scoped_to_caller():
    cache = _FakeCache()
    fake_episodic = AsyncMock()
    fake_episodic.forget_all = AsyncMock(return_value=True)
    fake_facts = AsyncMock()
    fake_facts.forget_all = AsyncMock(return_value=True)
    fake_mind = AsyncMock()
    fake_mind._clear_conversation = AsyncMock()

    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory",
            return_value=fake_episodic,
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=fake_facts),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
    ):
        r = client.post("/api/v1/account/delete", cookies=_cookie("user-a@example.com"))

    assert r.json()["ok"] is True
    fake_episodic.forget_all.assert_awaited_once_with("user-a@example.com")
    fake_facts.forget_all.assert_awaited_once_with("user-a@example.com")


def test_delete_account_clears_every_chat_history_session_variant():
    """The default conversation (u:{email}) AND a custom-session variant
    (u:{email}:s1) must both get cleared — not just the default one."""
    cache = _FakeCache()
    cache._store["aria:mind:history:u:user-a@example.com"] = [{"role": "user", "content": "hi"}]
    cache._store["aria:mind:history:u:user-a@example.com:s1"] = [{"role": "user", "content": "hey"}]
    # A different user's history must never be touched.
    cache._store["aria:mind:history:u:user-b@example.com"] = [{"role": "user", "content": "hi"}]

    fake_mind = AsyncMock()
    fake_mind._clear_conversation = AsyncMock()

    with (
        patch("apps.core.memory.redis_client.get_cache", return_value=cache),
        patch(
            "apps.core.cognition.episodic_memory.get_episodic_memory",
            return_value=AsyncMock(),
        ),
        patch("apps.core.memory.user_facts.get_user_facts", return_value=AsyncMock()),
        patch("apps.core.cognition.aria_mind.get_aria_mind", return_value=fake_mind),
    ):
        r = client.post("/api/v1/account/delete", cookies=_cookie("user-a@example.com"))

    assert r.json()["ok"] is True
    cleared_cids = {c.args[0] for c in fake_mind._clear_conversation.await_args_list}
    assert cleared_cids == {"u:user-a@example.com", "u:user-a@example.com:s1"}
