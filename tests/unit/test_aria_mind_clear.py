"""Regression test: /clear used to claim it reset the conversation without
actually deleting anything from Redis, so the next message still carried
the old history in context."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


async def test_clear_actually_deletes_history_and_state():
    cache = MagicMock()
    cache.delete = AsyncMock(return_value=True)

    with patch("apps.core.memory.redis_client.get_cache", return_value=cache):
        mind = AriaMind()
        resp = await mind.handle("/clear", "chat-42")

    assert "reiniciada" in resp.text.lower()
    deleted_keys = {call.args[0] for call in cache.delete.await_args_list}
    assert "aria:mind:history:chat-42" in deleted_keys
    assert "aria:mind:state:chat-42" in deleted_keys
    assert "aria:mind:icount:chat-42" in deleted_keys
    # Global, persistent memory must never be touched by a per-chat /clear.
    assert not any(k in ("aria:mind:goals", "aria:mind:learned") for k in deleted_keys)
