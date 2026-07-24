"""Regression tests for QA audit batch 3 (config.py, auth.py, auth_accounts.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.config import Settings


class TestSupabaseUrlFix:
    def test_bare_project_root(self):
        s = Settings(SUPABASE_URL="https://supabase.com/dashboard/project/abcxyz")
        assert s.SUPABASE_URL == "https://abcxyz.supabase.co"

    def test_url_with_editor_suffix_previously_broke_this(self):
        s = Settings(SUPABASE_URL="https://supabase.com/dashboard/project/abcxyz/editor")
        assert s.SUPABASE_URL == "https://abcxyz.supabase.co"

    def test_url_with_query_string(self):
        s = Settings(SUPABASE_URL="https://supabase.com/dashboard/project/abcxyz?tab=sql")
        assert s.SUPABASE_URL == "https://abcxyz.supabase.co"

    def test_already_correct_url_untouched(self):
        s = Settings(SUPABASE_URL="https://abcxyz.supabase.co")
        assert s.SUPABASE_URL == "https://abcxyz.supabase.co"

    def test_empty_stays_empty(self):
        s = Settings(SUPABASE_URL="")
        assert s.SUPABASE_URL == ""


@pytest.mark.asyncio
async def test_create_account_race_is_closed_by_atomic_write(monkeypatch):
    """Two concurrent signups for the same email: only the first must win."""
    from apps.core import auth_accounts

    store: dict[str, str] = {}

    async def fake_set_if_not_exists(key, value, ttl_seconds=3600):
        if key in store:
            return False
        store[key] = value
        return True

    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)  # account_exists() fast-path sees nothing yet
    cache.set_if_not_exists = fake_set_if_not_exists

    async def fake_cache():
        return cache

    monkeypatch.setattr(auth_accounts, "_cache", fake_cache)

    ok1, err1 = await auth_accounts.create_account("racer@example.com", "password123", "First")
    ok2, err2 = await auth_accounts.create_account("racer@example.com", "different99", "Second")

    assert ok1 is True and err1 == ""
    assert ok2 is False and "already exists" in err2
    # Only the first write's hash survives.
    import json

    stored = json.loads(store["aria:account:racer@example.com"])
    assert stored["name"] == "First"


@pytest.mark.asyncio
async def test_remember_user_trims_the_list(monkeypatch):
    from apps.core import auth

    cache = MagicMock()
    cache.rpush = AsyncMock(return_value=1)
    cache.ltrim = AsyncMock(return_value=True)
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        await auth.remember_user({"email": "a@example.com"})
    cache.rpush.assert_awaited_once()
    cache.ltrim.assert_awaited_once_with("aria:users", -5000, -1)


@pytest.mark.asyncio
async def test_list_users_reads_most_recent_not_oldest(monkeypatch):
    """Regression for the admin user list going stale once aria:users exceeds
    500 entries (rpush + head-read meant new users could become invisible)."""
    import apps.core.main as main_module

    cache = MagicMock()

    async def fake_lrange(key, start, stop):
        assert (start, stop) == (-500, -1), "must read from the tail, not the head"
        return ['{"email": "new@example.com", "name": "New", "provider": "google"}']

    cache.lrange = fake_lrange
    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        users = await main_module._list_users()
    assert users == [{"email": "new@example.com", "name": "New", "provider": "google"}]
