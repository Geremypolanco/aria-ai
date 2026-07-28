"""Regression tests for two things fixed together while wiring real RLS
into the long-term memory store:

  1. apps/core/memory/user_facts.py's _client_for(user_id) — prefers the
     RLS-enforced anon+JWT client (apps/core/memory/rls_client.py) when
     it's configured, and falls back to today's service-role client
     (apps/core/memory/supabase_client.py) otherwise. This must never
     regress existing behavior: with RLS unconfigured (the default, and
     production's current state), every call must still go through the
     service-role client exactly as before.

  2. apps/core/memory/supabase_client.py's AriaDatabase had no .rpc()
     passthrough (only .table()) — meaning UserFactStore.recall()'s
     pgvector similarity call (`db.rpc("match_user_memories", ...)`) hit an
     AttributeError on every single call when running against the
     service-role client, silently swallowed by recall()'s broad except
     block and falling back to keyword search unconditionally. Vector
     search never actually worked in production until this fix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.memory.supabase_client import AriaDatabase
from apps.core.memory.user_facts import UserFactStore, _client_for

pytestmark = pytest.mark.asyncio


def _service_role_settings():
    return patch.multiple(
        "apps.core.memory.user_facts.settings",
        SUPABASE_URL="https://fake.supabase.co",
        SUPABASE_KEY="fake-service-role-key",
    )


async def test_client_for_falls_back_to_service_role_when_rls_not_configured():
    fake_service_client = MagicMock(name="service-role-client")

    with (
        patch("apps.core.memory.rls_client.get_rls_client", return_value=None),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_service_client),
    ):
        client = _client_for("user-a@example.com")

    assert client is fake_service_client


async def test_client_for_prefers_rls_client_when_configured():
    fake_rls_client = MagicMock(name="rls-scoped-client")
    fake_service_client = MagicMock(name="service-role-client")

    with (
        patch("apps.core.memory.rls_client.get_rls_client", return_value=fake_rls_client),
        patch("apps.core.memory.supabase_client.get_db", return_value=fake_service_client),
    ):
        client = _client_for("user-a@example.com")

    assert client is fake_rls_client
    assert client is not fake_service_client


async def test_remember_uses_the_rls_client_when_configured():
    fake_rls_client = MagicMock()
    fake_rls_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1"}]
    )

    store = UserFactStore()
    with (
        _service_role_settings(),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=None)),
        patch("apps.core.memory.rls_client.get_rls_client", return_value=fake_rls_client),
    ):
        memory_id = await store.remember("user-a@example.com", "likes dark mode")

    assert memory_id == "mem-1"
    fake_rls_client.table.assert_called_with("aria_user_memories")


async def test_ariadatabase_rpc_passthrough_calls_underlying_client():
    """Before this fix, AriaDatabase.rpc() didn't exist at all, so
    recall()'s vector-search RPC call raised AttributeError against the
    real service-role client used everywhere in production."""
    db = AriaDatabase.__new__(AriaDatabase)
    fake_underlying = MagicMock()
    db._client = fake_underlying

    db.rpc("match_user_memories", {"p_user_id": "user-a@example.com"})

    fake_underlying.rpc.assert_called_once_with(
        "match_user_memories", {"p_user_id": "user-a@example.com"}
    )


async def test_recall_vector_path_actually_works_against_the_service_role_client():
    """End-to-end regression for the AttributeError bug: recall() with an
    available embedding must reach match_user_memories() successfully
    (not silently fall back to keyword search) when using the plain
    service-role AriaDatabase client, exactly like production does today
    with RLS unconfigured."""
    db = AriaDatabase.__new__(AriaDatabase)
    fake_underlying = MagicMock()
    fake_underlying.rpc.return_value.execute.return_value = MagicMock(
        data=[{"id": "mem-1", "content": "prefers dark mode"}]
    )
    db._client = fake_underlying

    store = UserFactStore()
    with (
        _service_role_settings(),
        patch("apps.core.memory.embeddings.embed_text", AsyncMock(return_value=[0.1, 0.2, 0.3])),
        patch("apps.core.memory.rls_client.get_rls_client", return_value=None),
        patch("apps.core.memory.supabase_client.get_db", return_value=db),
    ):
        results = await store.recall("user-a@example.com", "what do they prefer")

    assert results == [{"id": "mem-1", "content": "prefers dark mode"}]
    fake_underlying.rpc.assert_called_once()
